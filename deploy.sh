#!/bin/bash
# SLHRM Deploy Script
# Usage: bash deploy.sh [site]
# Run from the frappe_docker directory on the VPS

SITE="${1:-desk02.evonet.lk}"
BACKEND="frappe_docker-backend-1"
FRONTEND="frappe_docker-frontend-1"

echo "=== Deploying SLHRM to ${SITE} ==="

# 1. Pull latest code
echo "[1/9] Pulling latest code..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench/apps/slhrm && git pull upstream master"

# 2. Run migrate
echo "[2/9] Running bench migrate..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench --site ${SITE} migrate"

# 3. Build ALL app assets (frappe + erpnext + hrms + slhrm)
echo "[3/9] Building all app assets..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench build --app frappe --app erpnext --app hrms --app slhrm"

# 4. Copy app to frontend container via tar
echo "[4/9] Copying app to frontend container..."
docker exec ${BACKEND} bash -c "tar cf /tmp/slhrm.tar -C /home/frappe/frappe-bench/apps slhrm"
docker cp ${BACKEND}:/tmp/slhrm.tar /tmp/slhrm.tar
docker cp /tmp/slhrm.tar ${FRONTEND}:/tmp/slhrm.tar
docker exec ${FRONTEND} bash -c "rm -rf /home/frappe/frappe-bench/apps/slhrm && cd /home/frappe/frappe-bench/apps && tar xf /tmp/slhrm.tar"

# 5. Sync ALL built assets from backend to frontend (replaces broken symlinks)
echo "[5/9] Syncing built assets to frontend..."
docker exec ${BACKEND} bash -c "tar cf /tmp/all-assets.tar -C /home/frappe/frappe-bench/sites/assets frappe/dist erpnext/dist hrms/dist slhrm css js locale assets.json assets-rtl.json 2>/dev/null"
docker cp ${BACKEND}:/tmp/all-assets.tar /tmp/all-assets.tar
docker cp /tmp/all-assets.tar ${FRONTEND}:/tmp/all-assets.tar
docker exec ${FRONTEND} bash -c "cd /home/frappe/frappe-bench/sites/assets && rm -rf frappe/dist erpnext/dist hrms/dist css js locale slhrm && tar xf /tmp/all-assets.tar"

# 6. Ensure slhrm asset symlink in backend (for future builds)
echo "[6/9] Ensuring backend asset symlink..."
docker exec ${BACKEND} bash -c "rm -rf /home/frappe/frappe-bench/sites/assets/slhrm && ln -sf /home/frappe/frappe-bench/apps/slhrm/slhrm/public /home/frappe/frappe-bench/sites/assets/slhrm"

# 7. Inject /slhrm location into frontend nginx config (idempotent)
echo "[7/9] Configuring nginx for PWA..."
docker exec ${FRONTEND} bash -c "grep -q 'location /slhrm' /etc/nginx/conf.d/frappe.conf || sed -i '/location \/assets {/i\\\\tlocation /slhrm {\\n\\t\\talias /home/frappe/frappe-bench/sites/slhrm_pwa;\\n\\t\\ttry_files \$uri \$uri/ /slhrm/index.html;\\n\\n\\t\\tlocation ~* \\\\.(?:css|js|woff2?|ttf|eot|ico|svg|gif|jpe?g|png|webp|map)$ {\\n\\t\\t\\texpires 30d;\\n\\t\\t\\tadd_header Cache-Control \"public, immutable\";\\n\\t\\t}\\n\\t}' /etc/nginx/conf.d/frappe.conf && nginx -t && nginx -s reload"

# 8. Restart containers
echo "[8/9] Restarting containers..."
cd /home/rajerp/frappe_docker && docker compose restart backend frontend

# 9. Cleanup temp files on host
echo "[9/9] Cleaning up..."
rm -f /tmp/slhrm.tar /tmp/all-assets.tar

echo "=== Deploy complete: ${SITE} ==="
echo "Desk: https://${SITE}/"
echo "PWA: https://${SITE%%.*}.evonet.lk/slhrm/"
