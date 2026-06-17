import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=120):
    print(f'>>> {cmd[:200]}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip()[:3000])
    if err: print('ERR: ' + err.strip()[:1000])
    return out

# Write SQL file to host, then docker cp to container
sftp = ssh.open_sftp()
with sftp.open('/tmp/check.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;

SELECT '--- DocTypes ---' as info;
SELECT name FROM tabDocType WHERE module='SLHRM';

SELECT '--- Module Def ---' as info;
SELECT name FROM `tabModule Def` WHERE name='SLHRM';

SELECT '--- Workspace ---' as info;
SELECT name, app, module FROM tabWorkspace WHERE module='SLHRM' OR app='slhrm';

SELECT '--- Workspace Sidebar ---' as info;
SELECT name, app FROM `tabWorkspace Sidebar` WHERE app='slhrm';

SELECT '--- Custom Fields ---' as info;
SELECT name FROM tabCustomField WHERE module='SLHRM';

SELECT '--- Installed Application ---' as info;
SELECT app_name, is_setup_complete FROM `tabInstalled Application` WHERE app_name='slhrm';

SELECT '--- Module Defs Count ---' as info;
SELECT COUNT(*) as cnt FROM `tabModule Def`;

SELECT '--- All tables count ---' as info;
SELECT COUNT(*) as cnt FROM information_schema.tables WHERE table_schema=database();
""")
sftp.close()

# Copy to backend container
run('docker cp /tmp/check.sql frappe_docker-backend-1:/tmp/check.sql')

# Run via bench mariadb < /tmp/check.sql
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/check.sql"')

# Also check if custom_attendance is causing issues
run('docker exec frappe_docker-backend-1 ls /home/frappe/frappe-bench/apps/custom_attendance/')

# Check the frappe module discovery
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \\"SELECT name FROM \\\\\`tabModule Def\\\\\` LIMIT 20\\""')

ssh.close()
print("\nDONE")
