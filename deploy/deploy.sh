#!/bin/bash
# SLHRM Deployment Script
# Run on VPS: bash deploy.sh
# Pulls from GitHub, rebuilds PWA, migrates, copies nginx config, restarts services
set -e

echo "=== SLHRM Deployment ==="

# 1. Pull latest code
echo "Pulling latest code..."
docker exec frappe_docker-backend-1 bash -c 'cd /home/frappe/frappe-bench/apps/slhrm && git pull'

# 2. Rebuild PWA
echo "Rebuilding PWA..."
docker exec frappe_docker-backend-1 bash -c 'cd /home/frappe/frappe-bench/apps/slhrm/SLHRM-PWA && VITE_OUT_DIR=../public/frontend npx vite build --base=/slhrm/'

# 3. Run migrate (triggers _sync_pwa_assets)
echo "Running migrate on desk01..."
docker exec frappe_docker-backend-1 bench --site desk01.evonet.lk migrate 2>&1 || true
echo "Running migrate on desk02..."
docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk migrate 2>&1 || true

# 4. Sync PWA assets to shared volume
echo "Syncing PWA assets..."
docker exec frappe_docker-backend-1 bench --site desk01.evonet.lk execute 'slhrm.install._sync_pwa_assets' 2>&1 || true

# 5. Copy nginx config to frontend container
echo "Updating nginx config..."
docker cp deploy/frappe.conf frappe_docker-frontend-1:/etc/nginx/conf.d/frappe.conf
docker exec frappe_docker-frontend-1 nginx -s reload

# 6. Restart gunicorn workers
echo "Restarting gunicorn..."
docker exec frappe_docker-backend-1 python3 -c "import os,signal; [os.kill(int(p), signal.SIGTERM) for p in os.listdir('/proc') if p.isdigit() and open(f'/proc/{p}/comm').read().strip()=='gunicorn' and int(p)!=1]" 2>/dev/null || true

echo "=== Deployment complete ==="
echo "Test: https://desk01.evonet.lk/slhrm/"
