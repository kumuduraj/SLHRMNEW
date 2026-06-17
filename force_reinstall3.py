import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=300):
    print(f'>>> {cmd[:200]}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip()[:5000])
    if err: print('ERR: ' + err.strip()[:2000])
    return out

# Step 1: Verify current state - is app still in DB?
print("=== STEP 1: Current DB state ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/state.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;
SELECT app_name, is_setup_complete FROM `tabInstalled Application` WHERE app_name='slhrm';
""")
sftp.close()
run('docker cp /tmp/state.sql frappe_docker-backend-1:/tmp/state.sql')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/state.sql"')

# Step 2: Delete the entry individually
print("\n=== STEP 2: Delete installed app entry ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/del.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;
SET SQL_SAFE_UPDATES=0;
DELETE FROM `tabInstalled Application` WHERE app_name='slhrm';
SELECT app_name FROM `tabInstalled Application`;
""")
sftp.close()
run('docker cp /tmp/del.sql frappe_docker-backend-1:/tmp/del.sql')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/del.sql"')

# Step 3: Install-app (app files already exist from get-app)
print("\n=== STEP 3: Install-app ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk install-app slhrm 2>&1"', timeout=300)

# Step 4: Verify
print("\n=== STEP 4: Verify ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/check5.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;
SELECT '--- DocTypes ---' as info;
SELECT name FROM tabDocType WHERE module='SLHRM';
SELECT '--- Workspace ---' as info;
SELECT name FROM tabWorkspace WHERE module='SLHRM' OR app='slhrm';
SELECT '--- Sidebar ---' as info;
SELECT name FROM `tabWorkspace Sidebar` WHERE app='slhrm';
SELECT '--- Page ---' as info;
SELECT name FROM tabPage WHERE module='SLHRM';
SELECT '--- Installed ---' as info;
SELECT app_name, is_setup_complete FROM `tabInstalled Application` WHERE app_name='slhrm';
""")
sftp.close()
run('docker cp /tmp/check5.sql frappe_docker-backend-1:/tmp/check5.sql')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/check5.sql"')

# Step 5: Build + cache + restart
print("\n=== STEP 5: Build + restart ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench build --app slhrm 2>&1"', timeout=300)
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk clear-cache 2>&1"')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench restart 2>&1"')

# Step 6: Final verify
print("\n=== STEP 6: Final verify ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/check5.sql"')

ssh.close()
print("\nDONE")
