#!/bin/bash
# SLHRM Deploy Script
# Usage: bash deploy.sh [site]
# Run from the frappe_docker directory on the VPS

SITE="${1:-desk02.evonet.lk}"
BACKEND="frappe_docker-backend-1"
FRONTEND="frappe_docker-frontend-1"

echo "=== Deploying SLHRM to ${SITE} ==="

# 1. Pull latest code
echo "[1/8] Pulling latest code..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench/apps/slhrm && git pull upstream master"

# 2. Run migrate
echo "[2/8] Running bench migrate..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench --site ${SITE} migrate"

# 3. Build ALL app assets (frappe + erpnext + hrms + slhrm)
echo "[3/8] Building all app assets..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench build --app frappe --app erpnext --app hrms --app slhrm"

# 4. Copy app to frontend container via tar
echo "[4/8] Copying app to frontend container..."
docker exec ${BACKEND} bash -c "tar cf /tmp/slhrm.tar -C /home/frappe/frappe-bench/apps slhrm"
docker cp ${BACKEND}:/tmp/slhrm.tar /tmp/slhrm.tar
docker cp /tmp/slhrm.tar ${FRONTEND}:/tmp/slhrm.tar
docker exec ${FRONTEND} bash -c "rm -rf /home/frappe/frappe-bench/apps/slhrm && cd /home/frappe/frappe-bench/apps && tar xf /tmp/slhrm.tar"

# 5. Sync ALL built assets from backend to frontend (replaces broken symlinks)
echo "[5/8] Syncing built assets to frontend..."
docker exec ${BACKEND} bash -c "tar cf /tmp/all-assets.tar -C /home/frappe/frappe-bench/sites/assets frappe/dist erpnext/dist hrms/dist slhrm css js locale assets.json assets-rtl.json 2>/dev/null"
docker cp ${BACKEND}:/tmp/all-assets.tar /tmp/all-assets.tar
docker cp /tmp/all-assets.tar ${FRONTEND}:/tmp/all-assets.tar
docker exec ${FRONTEND} bash -c "cd /home/frappe/frappe-bench/sites/assets && rm -rf frappe/dist erpnext/dist hrms/dist css js locale slhrm && tar xf /tmp/all-assets.tar"

# 6. Ensure slhrm asset symlink in backend (for future builds)
echo "[6/8] Ensuring backend asset symlink..."
docker exec ${BACKEND} bash -c "rm -rf /home/frappe/frappe-bench/sites/assets/slhrm && ln -sf /home/frappe/frappe-bench/apps/slhrm/slhrm/public /home/frappe/frappe-bench/sites/assets/slhrm"

# 7. Set up PWA files for Frappe website_route_rules serving
echo "[7/8] Setting up PWA files..."
docker exec ${FRONTEND} bash -c "mkdir -p /home/frappe/frappe-bench/sites/www/slhrm && cp /home/frappe/frappe-bench/sites/slhrm_pwa/index.html /home/frappe/frappe-bench/sites/www/slhrm/index.html && mkdir -p /home/frappe/frappe-bench/sites/assets/slhrm/frontend && cp -r /home/frappe/frappe-bench/sites/slhrm_pwa/assets/* /home/frappe/frappe-bench/sites/assets/slhrm/frontend/ && cp /home/frappe/frappe-bench/sites/slhrm_pwa/favicon.png /home/frappe/frappe-bench/sites/assets/slhrm/frontend/ && cp /home/frappe/frappe-bench/sites/slhrm_pwa/manifest.webmanifest /home/frappe/frappe-bench/sites/assets/slhrm/frontend/"

# 8. Restart containers
echo "[8/8] Restarting containers..."
cd /home/rajerp/frappe_docker && docker compose restart backend frontend

echo "=== Deploy complete: ${SITE} ==="
echo "Desk: https://${SITE}/"
echo "PWA: https://${SITE%%.*}.evonet.lk/slhrm/"
