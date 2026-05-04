#!/usr/bin/env bash
# Pull latest code and restart the service.
# Run from: /home/ubuntu/shii
set -euo pipefail

cd /home/ubuntu/shii
git pull
uv sync
sudo systemctl restart shii
echo "Updated and restarted. Status:"
sudo systemctl status shii --no-pager
