#!/bin/bash
# Run after `bench build` to copy compiled assets into the shared assets volume.
# Needed because bench build writes to the container overlay (apps/*/public/dist/),
# while nginx reads from the shared assets volume. Without this copy, nginx serves
# stale asset hashes and gets CSS MIME type errors.
#
# Usage: ./refresh_assets.sh
# OR:    ./refresh_assets.sh "frappe erpnext slhrm"  (to refresh specific apps only)

set -e

APPS="${1:-frappe erpnext hrms slhrm crm custom_attendance}"

echo "Copying compiled assets from backend overlay into shared assets volume..."

docker exec frappe_docker-backend-1 bash -c "
BENCH=/home/frappe/frappe-bench
for app in $APPS; do
    src=\"\$BENCH/apps/\$app/\$app/public\"
    dst=\"\$BENCH/assets/\$app\"
    if [ -d \"\$src\" ]; then
        rm -rf \"\$dst\"
        mkdir -p \"\$dst\"
        cp -r \"\$src/.\" \"\$dst/\"
        echo \"  Copied \$app\"
    fi
done

# slhrm: also copy public/frontend/ (PWA) if it exists
# The symlink apps/slhrm/slhrm/public may not include frontend/,
# so copy directly from apps/slhrm/public/frontend/
SLHRM_PUB=\$BENCH/apps/slhrm/public
if [ -d \"\$SLHRM_PUB/frontend\" ]; then
    mkdir -p \"\$BENCH/assets/slhrm/frontend\"
    cp -r \"\$SLHRM_PUB/frontend/.\" \"\$BENCH/assets/slhrm/frontend/\"
    echo \"  Copied slhrm/frontend (PWA)\"
fi

cp \"\$BENCH/assets/assets.json\" \"\$BENCH/sites/assets.json\" 2>/dev/null || true
echo 'Assets copied.'
"

echo "Restarting nginx to pick up new assets..."
docker compose restart frontend

echo "Done. Both sites should now load without CSS MIME errors."
