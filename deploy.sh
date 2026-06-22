#!/bin/bash
# SLHRM Deploy Script
# Usage: bash deploy.sh [site]
# Run from the frappe_docker directory on the VPS

SITE="${1:-desk02.evonet.lk}"
BACKEND="frappe_docker-backend-1"
FRONTEND="frappe_docker-frontend-1"

echo "=== Deploying SLHRM to ${SITE} ==="

# 1. Pull latest code
echo "[1/7] Pulling latest code..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench/apps/slhrm && git pull upstream master"

# 2. Run migrate
echo "[2/7] Running bench migrate..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench --site ${SITE} migrate"

# 3. Build assets
echo "[3/7] Building assets..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench build --app slhrm"

# 4. Copy app to frontend container (fixes broken symlinks)
echo "[4/7] Copying app to frontend container..."
docker cp /home/frappe/frappe-bench/apps/slhrm ${FRONTEND}:/home/frappe/frappe-bench/apps/slhrm

# 5. Copy built assets to frontend (replace symlinks with actual files)
echo "[5/7] Syncing assets to frontend..."
docker exec ${FRONTEND} bash -c "rm -rf /home/frappe/frappe-bench/sites/assets/slhrm && cp -r /home/frappe/frappe-bench/apps/slhrm/slhrm/public /home/frappe/frappe-bench/sites/assets/slhrm"

# 6. Install nginx config for PWA (if not already installed)
echo "[6/7] Setting up PWA nginx config..."
docker exec ${FRONTEND} bash -c "cp /home/frappe/frappe-bench/apps/slhrm/nginx/slhrm-pwa.conf /etc/nginx/conf.d/slhrm-pwa.conf 2>/dev/null || true"
docker exec ${FRONTEND} bash -c "nginx -s reload 2>/dev/null || true"

# 7. Restart containers
echo "[7/7] Restarting containers..."
cd /home/rajerp/frappe_docker && docker compose restart backend frontend

echo "=== Deploy complete: ${SITE} ==="
