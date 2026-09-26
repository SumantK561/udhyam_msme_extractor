#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Public MSME search webapp setup (EC2 / Ubuntu)
#
# Run once as the ubuntu user, after DNS for the domain points at this
# instance's public IP:
#   bash scripts/setup_webapp.sh
#
# What it does:
#   1. Creates a dedicated virtualenv for the FastAPI backend
#   2. Installs dependencies
#   3. Prompts for the .env (Snowflake public-reader credentials)
#   4. Installs and starts the systemd unit for uvicorn
#   5. Installs nginx (if missing) + site config + rate-limit zone
#   6. Runs certbot to provision Let's Encrypt SSL
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WEBAPP_DIR="$PROJECT_DIR/webapp"
BACKEND_DIR="$WEBAPP_DIR/backend"
DEPLOY_DIR="$WEBAPP_DIR/deploy"
DOMAIN="${1:-msme.sumantk.in}"

echo "==> Project dir : $PROJECT_DIR"
echo "==> Domain      : $DOMAIN"

# 1. Backend virtualenv
if [ ! -d "$BACKEND_DIR/.venv" ]; then
    echo "==> Creating backend virtualenv..."
    python3 -m venv "$BACKEND_DIR/.venv"
fi

source "$BACKEND_DIR/.venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$BACKEND_DIR/requirements.txt"
deactivate

# 2. .env
if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo ""
    echo "==> Creating webapp/backend/.env -- Snowflake public-reader credentials"
    echo "    (run snowflake/part 4.sql first if you haven't already)"
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    read -rp "Snowflake account (e.g. ORGNAME-ACCOUNTNAME): " SF_ACCOUNT
    read -rsp "UDYAM_PUBLIC_SVC password: " SF_PASSWORD
    echo ""
    sed -i "s/YOUR_SNOWFLAKE_ACCOUNT/${SF_ACCOUNT}/" "$BACKEND_DIR/.env"
    sed -i "s/CHANGE_ME/${SF_PASSWORD}/" "$BACKEND_DIR/.env"
    sed -i "s#https://msme.sumantk.in#https://${DOMAIN}#" "$BACKEND_DIR/.env"
    echo "==> Wrote $BACKEND_DIR/.env"
else
    echo "==> $BACKEND_DIR/.env already exists, leaving it untouched"
fi

# 3. systemd unit for the API
sudo cp "$DEPLOY_DIR/udyam-webapp.service" /etc/systemd/system/udyam-webapp.service
sudo systemctl daemon-reload
sudo systemctl enable udyam-webapp
sudo systemctl restart udyam-webapp
echo "==> udyam-webapp systemd service installed and started"

# 4. nginx
if ! command -v nginx >/dev/null 2>&1; then
    echo "==> Installing nginx..."
    sudo apt-get update -qq
    sudo apt-get install -y nginx
fi

sudo cp "$DEPLOY_DIR/msme-ratelimit.conf" /etc/nginx/conf.d/msme-ratelimit.conf

sed "s/msme.sumantk.in/${DOMAIN}/g" "$DEPLOY_DIR/msme.sumantk.in.conf" \
    | sudo tee "/etc/nginx/sites-available/${DOMAIN}.conf" > /dev/null
sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"

sudo nginx -t
sudo systemctl reload nginx
echo "==> nginx configured for ${DOMAIN}"

# 5. SSL via certbot
echo ""
echo "==> Point your domain's DNS A record at this instance's public IP"
echo "    before running certbot, or it will fail the HTTP-01 challenge."
read -rp "Is DNS for ${DOMAIN} already pointing here? [y/N]: " DNS_READY

if [[ "$DNS_READY" =~ ^[Yy]$ ]]; then
    if ! command -v certbot >/dev/null 2>&1; then
        echo "==> Installing certbot..."
        sudo apt-get install -y certbot python3-certbot-nginx
    fi
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$(whoami)@localhost" --redirect || \
        echo "==> certbot failed -- rerun manually: sudo certbot --nginx -d ${DOMAIN}"
else
    echo "==> Skipping SSL. Once DNS propagates, run:"
    echo "      sudo certbot --nginx -d ${DOMAIN}"
fi

echo ""
echo "==> Done."
echo "    API:  http://127.0.0.1:8000/api/health (local)"
echo "    Site: http://${DOMAIN} (https:// once certbot runs)"
echo ""
echo "    Useful commands:"
echo "      sudo systemctl status udyam-webapp"
echo "      sudo journalctl -u udyam-webapp -f"
echo "      sudo nginx -t && sudo systemctl reload nginx"
