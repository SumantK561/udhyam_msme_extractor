#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dbt docs site setup (EC2 / Ubuntu)
#
# Run after setup_webapp.sh, once DNS for dbt.sumantk.in points at this
# instance's public IP:
#   bash scripts/setup_dbt_docs.sh
#
# What it does:
#   1. Runs dbt docs generate to produce catalog.json + manifest.json
#   2. Grants nginx traversal access to the dbt target directory
#   3. Installs the nginx site config for dbt.sumantk.in
#   4. Optionally runs certbot for HTTPS
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DBT_DIR="$PROJECT_DIR/udyam_dbt"
VENV="$PROJECT_DIR/.venv/bin/activate"
DEPLOY_DIR="$PROJECT_DIR/webapp/deploy"
DOMAIN="${1:-dbt.sumantk.in}"

echo "==> Project dir : $PROJECT_DIR"
echo "==> dbt dir     : $DBT_DIR"
echo "==> Domain      : $DOMAIN"

# 1. Generate dbt docs (needs the dbt profile / Snowflake creds in .env)
echo "==> Generating dbt docs..."
source "$VENV"
cd "$DBT_DIR"
dbt docs generate
deactivate
echo "==> dbt docs generated at $DBT_DIR/target/"

# 2. nginx traversal permissions for the target directory
chmod o+x "$HOME"
chmod o+x "$PROJECT_DIR"
chmod o+x "$DBT_DIR"
chmod o+x "$DBT_DIR/target"
echo "==> Permissions set on dbt target directory"

# 3. nginx site config
sed "s/dbt.sumantk.in/${DOMAIN}/g" "$DEPLOY_DIR/dbt.sumantk.in.conf" \
    | sudo tee "/etc/nginx/sites-available/${DOMAIN}.conf" > /dev/null
sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"

sudo nginx -t
sudo systemctl reload nginx
echo "==> nginx configured for ${DOMAIN}"

# 4. SSL via certbot
echo ""
echo "==> Point your domain's DNS A record at this instance's public IP"
echo "    before running certbot, or it will fail the HTTP-01 challenge."
read -rp "Is DNS for ${DOMAIN} already pointing here? [y/N]: " DNS_READY

if [[ "$DNS_READY" =~ ^[Yy]$ ]]; then
    if ! command -v certbot >/dev/null 2>&1; then
        sudo apt-get install -y certbot python3-certbot-nginx
    fi
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$(whoami)@localhost" --redirect || \
        echo "==> certbot failed -- rerun manually: sudo certbot --nginx -d ${DOMAIN}"
else
    echo "==> Skipping SSL. Once DNS propagates, run:"
    echo "      sudo certbot --nginx -d ${DOMAIN}"
fi

echo ""
echo "==> Done. dbt docs site: http://${DOMAIN}"
echo ""
echo "    To refresh docs manually:"
echo "      source $VENV && cd $DBT_DIR && dbt docs generate"
