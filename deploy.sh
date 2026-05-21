#!/bin/bash
# RegisGuard deployment script
# Run on target server: bash deploy.sh [allowed_ips]
# Example: bash deploy.sh "192.168.1.100,10.0.0.50"

set -e

INSTALL_DIR="/opt/regisguard"
ALLOWED_IPS="${1:-}"

echo "=== RegisGuard Deployment ==="

# 1. Install dependencies
echo "[1/6] Installing system dependencies..."
apt update && apt install -y nginx python3-pip python3-venv certbot python3-certbot-nginx

# 2. Create install directory
echo "[2/6] Setting up install directory..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p /var/www/construction_page

# 3. Copy files
echo "[3/6] Copying application files..."
cp -r app.py config.py db.py domains.json requirements.txt "$INSTALL_DIR/"
cp -r templates static scripts "$INSTALL_DIR/"
cp regisguard.service /etc/systemd/system/regisguard.service

# 4. Install Python dependencies
echo "[4/6] Installing Python dependencies..."
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Initialize database and configure settings
echo "[5/6] Initializing database..."
source venv/bin/activate
python3 -c "
from db import init_db, set_setting
init_db()
if '$ALLOWED_IPS':
    set_setting('allowed_ips', '$ALLOWED_IPS')
    print('  Allowed IPs: $ALLOWED_IPS')
else:
    print('  No IP whitelist configured (all IPs allowed)')
"

# 6. Enable and start service
echo "[6/6] Enabling systemd service..."
systemctl daemon-reload
systemctl enable regisguard
systemctl start regisguard

echo ""
echo "=== Deployment Complete ==="
echo "Admin panel: http://<server-ip>:5000"
echo "Default password: admin123 (change via panel or REGISGUARD_ADMIN_PASSWORD env var)"
if [ -n "$ALLOWED_IPS" ]; then
    echo "IP whitelist: $ALLOWED_IPS"
fi
echo ""
echo "Check status: systemctl status regisguard"
echo "View logs:    journalctl -u regisguard -f"
