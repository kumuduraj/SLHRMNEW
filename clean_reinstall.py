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

# Step 1: Remove slhrm and clean up
print("=== STEP 1: Clean remove ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk remove-app slhrm 2>&1 || true"')
run('docker exec frappe_docker-backend-1 bash -c "rm -rf /home/frappe/frappe-bench/apps/slhrm"')

# Step 2: Fresh get-app
print("\n=== STEP 2: Fresh get-app ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench get-app https://github.com/kumuduraj/SLHRMNEW.git 2>&1"', timeout=300)

# Step 3: Install on site
print("\n=== STEP 3: Install-app ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk install-app slhrm 2>&1"', timeout=300)

# Step 4: Migrate
print("\n=== STEP 4: Migrate ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk migrate 2>&1"', timeout=600)

# Step 5: Verify via SQL
print("\n=== STEP 5: Verify ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/check2.sql', 'w') as f:
    f.write("""USE `_1f5b1f23ca2e8149`;
SELECT '--- DocTypes ---' as info;
SELECT name FROM tabDocType WHERE module='SLHRM';
SELECT '--- Module Def ---' as info;
SELECT name FROM `tabModule Def` WHERE name='SLHRM';
SELECT '--- Workspace ---' as info;
SELECT name FROM tabWorkspace WHERE module='SLHRM' OR app='slhrm';
SELECT '--- Workspace Sidebar ---' as info;
SELECT name FROM `tabWorkspace Sidebar` WHERE app='slhrm';
SELECT '--- Custom Fields ---' as info;
SELECT name FROM tabCustomField WHERE module='SLHRM';
SELECT '--- Page ---' as info;
SELECT name FROM tabPage WHERE module='SLHRM';
""")
sftp.close()
run('docker cp /tmp/check2.sql frappe_docker-backend-1:/tmp/check2.sql')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb < /tmp/check2.sql"')

# Step 6: Build
print("\n=== STEP 6: Build ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench build --app slhrm 2>&1"', timeout=300)

# Step 7: Clear cache and restart
print("\n=== STEP 7: Clear cache + restart ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk clear-cache 2>&1"')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench restart 2>&1"')

ssh.close()
print("\nDONE")
