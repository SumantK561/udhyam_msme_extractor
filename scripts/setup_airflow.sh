#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Airflow setup for Udyam MSME pipeline (EC2 / Ubuntu)
#
# Run once as the ubuntu user:
#   bash scripts/setup_airflow.sh
#
# What it does:
#   1. Creates a dedicated virtualenv at ~/airflow-venv
#   2. Installs Apache Airflow (standalone, no extras)
#   3. Initialises the Airflow DB (SQLite, sufficient for single-node)
#   4. Points AIRFLOW__CORE__DAGS_FOLDER at this project's dags/ directory
#   5. Installs systemd units for scheduler and webserver
#   6. Creates an admin user (prompted interactively)
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AIRFLOW_VENV="$HOME/airflow-venv"
AIRFLOW_HOME="$HOME/airflow"
PYTHON="python3"

echo "==> Project dir : $PROJECT_DIR"
echo "==> Airflow home: $AIRFLOW_HOME"
echo "==> Airflow venv: $AIRFLOW_VENV"

# 1. Create dedicated venv
if [ ! -d "$AIRFLOW_VENV" ]; then
    echo "==> Creating Airflow virtualenv..."
    $PYTHON -m venv "$AIRFLOW_VENV"
fi

source "$AIRFLOW_VENV/bin/activate"

# 2. Install Airflow (pinned constraint file avoids resolver thrash)
AIRFLOW_VERSION=2.10.3
PYTHON_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

echo "==> Installing Apache Airflow ${AIRFLOW_VERSION}..."
pip install --quiet --upgrade pip
pip install --quiet "apache-airflow==${AIRFLOW_VERSION}" --constraint "$CONSTRAINT_URL"

# 3. Initialise Airflow DB
export AIRFLOW_HOME="$AIRFLOW_HOME"
export AIRFLOW__CORE__DAGS_FOLDER="$PROJECT_DIR/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"

mkdir -p "$AIRFLOW_HOME"
airflow db migrate

# 4. Write airflow.cfg overrides via env-based config (no file editing needed)
#    These are picked up by systemd units via EnvironmentFile.
ENV_FILE="$AIRFLOW_HOME/airflow.env"
cat > "$ENV_FILE" <<EOF
AIRFLOW_HOME=$AIRFLOW_HOME
AIRFLOW__CORE__DAGS_FOLDER=$PROJECT_DIR/dags
AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW__CORE__EXECUTOR=SequentialExecutor
AIRFLOW__WEBSERVER__WEB_SERVER_PORT=8080
EOF
echo "==> Airflow env written to $ENV_FILE"

# 5. Install systemd units
SYSTEMD_DIR="/etc/systemd/system"

sudo tee "$SYSTEMD_DIR/airflow-scheduler.service" > /dev/null <<EOF
[Unit]
Description=Airflow Scheduler
After=network.target

[Service]
User=$USER
EnvironmentFile=$ENV_FILE
ExecStart=$AIRFLOW_VENV/bin/airflow scheduler
Restart=always
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo tee "$SYSTEMD_DIR/airflow-webserver.service" > /dev/null <<EOF
[Unit]
Description=Airflow Webserver
After=network.target

[Service]
User=$USER
EnvironmentFile=$ENV_FILE
ExecStart=$AIRFLOW_VENV/bin/airflow webserver --port 8080
Restart=always
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable airflow-scheduler airflow-webserver
sudo systemctl start airflow-scheduler airflow-webserver

echo "==> Systemd units installed and started."

# 6. Create admin user
echo ""
echo "==> Creating Airflow admin user..."
read -rp "Username [admin]: " AF_USER
AF_USER="${AF_USER:-admin}"
read -rp "First name: " AF_FIRSTNAME
read -rp "Last name: " AF_LASTNAME
read -rp "Email: " AF_EMAIL
read -rsp "Password: " AF_PASSWORD
echo ""

airflow users create \
    --username "$AF_USER" \
    --firstname "$AF_FIRSTNAME" \
    --lastname "$AF_LASTNAME" \
    --role Admin \
    --email "$AF_EMAIL" \
    --password "$AF_PASSWORD"

echo ""
echo "==> Done. Airflow UI: http://<EC2-PUBLIC-IP>:8080"
echo "    Open port 8080 in your EC2 security group if not already open."
echo ""
echo "    Useful commands:"
echo "      sudo systemctl status airflow-scheduler"
echo "      sudo systemctl status airflow-webserver"
echo "      sudo journalctl -u airflow-scheduler -f"
