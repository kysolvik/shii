#!/usr/bin/env bash
# Full one-time setup for a fresh Ubuntu 22.04 Lightsail instance.
# Run as: bash setup.sh <github-repo-url>
# Example: bash setup.sh https://github.com/yourname/shii.git
set -euo pipefail

REPO_URL="${1:?Usage: bash setup.sh <github-repo-url>}"
APP_DIR="/home/ubuntu/shii"
SERVICE_NAME="shii"

echo "==> Updating system packages..."
sudo apt-get update -q
sudo apt-get install -y -q git nginx python3-pip

echo "==> Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "==> Cloning repo..."
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
git checkout dashboard

echo "==> Installing Python dependencies..."
uv sync

echo "==> Creating runtime directories..."
sudo mkdir -p /run/shii /var/log/shii
sudo chown ubuntu:www-data /run/shii /var/log/shii
sudo chmod 750 /run/shii

echo "==> Installing systemd service..."
sudo cp deploy/shii.service /etc/systemd/system/shii.service
sudo systemctl daemon-reload
sudo systemctl enable shii
sudo systemctl start shii

echo "==> Configuring nginx..."
sudo cp deploy/nginx-shii.conf /etc/nginx/sites-available/shii
sudo ln -sf /etc/nginx/sites-available/shii /etc/nginx/sites-enabled/shii
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "==> Done! Dashboard should be live at http://$(curl -4 ifconfig.me)"
echo "    Check status: sudo systemctl status shii"
echo "    View logs:    sudo journalctl -u shii -f"
