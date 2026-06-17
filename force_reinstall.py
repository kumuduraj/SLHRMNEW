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

# Step 1: Remove from DB properly via bench mariadb
print("=== STEP 1: Remove slhrm from installed apps in DB ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/fix.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;
DELETE FROM `tabInstalled Application` WHERE app_name='slhrm';
DELETE FROM `tabModule Def` WHERE name='SLHRM';
DELETE FROM `tabWorkspace Sidebar` WHERE app='slhrm';
DELETE FROM `tabWorkspace Sidebar Item` WHERE parent IN (SELECT name FROM `tabWorkspace Sidebar` WHERE app='slhrm');
DELETE FROM `tabWorkspace` WHERE app='slhrm' OR module='SLHRM';
DELETE FROM `tabDocType` WHERE module='SLHRM';
""")
sftp.close()
run('docker cp /tmp/fix.sql frappe_docker-backend-1:/tmp/fix.sql')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/fix.sql"')

# Step 2: Remove filesystem
print("\n=== STEP 2: Remove filesystem ===")
run('docker exec frappe_docker-backend-1 bash -c "rm -rf /home/frappe/frappe-bench/apps/slhrm"')

# Step 3: Fresh get-app
print("\n=== STEP 3: Fresh get-app ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench get-app https://github.com/kumuduraj/SLHRMNEW.git 2>&1"', timeout=300)

# Step 4: Install on site (should NOT say "already installed" now)
print("\n=== STEP 4: Install-app ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk install-app slhrm 2>&1"', timeout=300)

# Step 5: Verify immediately
print("\n=== STEP 5: Verify after install ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/check3.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;
SELECT '--- DocTypes ---' as info;
SELECT name FROM tabDocType WHERE module='SLHRM';
SELECT '--- Module Def ---' as info;
SELECT name FROM `tabModule Def` WHERE name='SLHRM';
SELECT '--- Workspace ---' as info;
SELECT name FROM tabWorkspace WHERE module='SLHRM' OR app='slhrm';
SELECT '--- Workspace Sidebar ---' as info;
SELECT name FROM `tabWorkspace Sidebar` WHERE app='slhrm';
SELECT '--- Page ---' as info;
SELECT name FROM tabPage WHERE module='SLHRM';
SELECT '--- Installed Apps ---' as info;
SELECT app_name, is_setup_complete FROM `tabInstalled Application` WHERE app_name='slhrm';
""")
sftp.close()
run('docker cp /tmp/check3.sql frappe_docker-backend-1:/tmp/check3.sql')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/check3.sql"')

# Step 6: Migrate + build
print("\n=== STEP 6: Migrate ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk migrate 2>&1"', timeout=600)

print("\n=== STEP 7: Build ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench build --app slhrm 2>&1"', timeout=300)

# Step 8: Final verify
print("\n=== STEP 8: Final verify ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/check3.sql"')

# Step 9: Clear cache + restart
print("\n=== STEP 9: Clear cache + restart ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk clear-cache 2>&1"')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench restart 2>&1"')

ssh.close()
print("\nDONE")
