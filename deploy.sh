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

# 3. Build assets
echo "[3/8] Building assets..."
docker exec ${BACKEND} bash -c "cd /home/frappe/frappe-bench && bench build --app slhrm"

# 4. Copy app to frontend container via tar (backend path differs from host)
echo "[4/8] Copying app to frontend container..."
docker exec ${BACKEND} bash -c "tar cf /tmp/slhrm.tar -C /home/frappe/frappe-bench/apps slhrm"
docker cp ${BACKEND}:/tmp/slhrm.tar /tmp/slhrm.tar
docker cp /tmp/slhrm.tar ${FRONTEND}:/tmp/slhrm.tar
docker exec ${FRONTEND} bash -c "rm -rf /home/frappe/frappe-bench/apps/slhrm && cd /home/frappe/frappe-bench/apps && tar xf /tmp/slhrm.tar && rm -f /tmp/slhrm.tar"

# 5. Create asset symlink in frontend (replace broken link)
echo "[5/8] Creating asset symlink in frontend..."
docker exec ${FRONTEND} bash -c "rm -rf /home/frappe/frappe-bench/sites/assets/slhrm && ln -s /home/frappe/frappe-bench/apps/slhrm/slhrm/public /home/frappe/frappe-bench/sites/assets/slhrm"

# 6. Ensure slhrm symlink exists in backend assets too
echo "[6/8] Ensuring backend asset symlink..."
docker exec ${BACKEND} bash -c "rm -rf /home/frappe/frappe-bench/sites/assets/slhrm && ln -s /home/frappe/frappe-bench/apps/slhrm/slhrm/public /home/frappe/frappe-bench/sites/assets/slhrm"

# 7. Inject /slhrm location into frontend nginx config (idempotent)
echo "[7/8] Configuring nginx for PWA..."
docker exec ${FRONTEND} bash -c "grep -q 'location /slhrm' /etc/nginx/conf.d/frappe.conf || sed -i '/location \/assets {/i\\\\tlocation /slhrm {\\n\\t\\talias /home/frappe/frappe-bench/sites/slhrm_pwa;\\n\\t\\ttry_files \$uri \$uri/ /slhrm/index.html;\\n\\n\\t\\tlocation ~* \\\\.(?:css|js|woff2?|ttf|eot|ico|svg|gif|jpe?g|png|webp|map)$ {\\n\\t\\t\\texpires 30d;\\n\\t\\t\\tadd_header Cache-Control \"public, immutable\";\\n\\t\\t}\\n\\t}' /etc/nginx/conf.d/frappe.conf && nginx -t && nginx -s reload"

# 8. Restart containers
echo "[8/8] Restarting containers..."
cd /home/rajerp/frappe_docker && docker compose restart backend frontend

echo "=== Deploy complete: ${SITE} ==="
echo "PWA: https://${SITE%%.*}.evonet.lk/slhrm/"
