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
    if err: print(err.strip()[:3000])
    return out + err

db = '_1f5b1f23ca2e8149'

# Get DB password from site_config
run(f'docker exec frappe_docker-backend-1 python -c "import json; c=json.load(open(\\\"/home/frappe/frappe-bench/sites/desk02.evonet.lk/site_config.json\\\")); print(c.get(\\\"db_password\\\",\\\"?\\\"))"')

# Use bench mariadb directly (it handles auth)
print("\n=== DocTypes ===")
run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT name FROM tabDocType WHERE module=\\\"SLHRM\\\""')

print("\n=== Module Def ===")
try:
    run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT name FROM \\"tabModule Def\\" WHERE name=\\\"SLHRM\\\""')
except:
    pass

print("\n=== Workspace ===")
try:
    run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT name, app, module FROM tabWorkspace WHERE module=\\\"SLHRM\\\""')
except:
    pass

print("\n=== Workspace Sidebar ===")
try:
    run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT name, app FROM \\"tabWorkspace Sidebar\\" WHERE app=\\\"slhrm\\\""')
except:
    pass

print("\n=== Custom Fields ===")
try:
    run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT name FROM tabCustomField WHERE module=\\\"SLHRM\\\""')
except:
    pass

print("\n=== Installed Application ===")
try:
    run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT app_name, is_setup_complete FROM \\"tabInstalled Application\\" WHERE app_name=\\\"slhrm\\\""')
except:
    pass

print("\n=== Page slhrm ===")
try:
    run(f'docker exec frappe_docker-backend-1 bench --site desk02.evonet.lk mariadb -e "SELECT name FROM tabPage WHERE module=\\\"SLHRM\\\""')
except:
    pass

# Check symlinks
print("\n=== Symlinks ===")
run('docker exec frappe_docker-backend-1 ls -la /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm/')

# Check assets
print("\n=== Assets ===")
run('docker exec frappe_docker-backend-1 find /home/frappe/frappe-bench/sites/desk02.evonet.lk/public/assets/ -name "slhrm*" 2>/dev/null | head -20')

ssh.close()
print("\nDONE")
