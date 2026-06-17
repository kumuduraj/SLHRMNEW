import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=300):
    print(f'>>> {cmd[:250]}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip()[:5000])
    if err: print('ERR: ' + err.strip()[:2000])
    return out

# Check what install-app actually checks
print("=== What does install-app check? ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/inspect.py', 'w') as f:
    f.write("""import frappe
frappe.connect()

# Check installed apps
print('installed_apps:', frappe.get_installed_apps())

# Check site_config
import json
with open('/home/frappe/frappe-bench/sites/desk02.evonet.lk/site_config.json') as f:
    sc = json.load(f)
print('site_config keys:', list(sc.keys()))

# Check if slhrm is in installed list
print('slhrm in installed_apps:', 'slhrm' in frappe.get_installed_apps())

frappe.db.close()
""")
sftp.close()
run('docker cp /tmp/inspect.py frappe_docker-backend-1:/tmp/inspect.py')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute /tmp/inspect.py"')

# Force install by calling the function directly
print("\n=== Force install via Python ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/force_install.py', 'w') as f:
    f.write("""import frappe
import sys

frappe.connect(site='desk02.evonet.lk')

# Check current state
installed = frappe.get_installed_apps()
print('Currently installed:', installed)

# Call install_app directly
try:
    from frappe.installer import install_app
    install_app('slhrm', site='desk02.evonet.lk', verbose=True)
    print('install_app completed!')
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()

frappe.db.commit()
frappe.db.close()
""")
sftp.close()
run('docker cp /tmp/force_install.py frappe_docker-backend-1:/tmp/force_install.py')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute /tmp/force_install.py 2>&1"', timeout=300)

ssh.close()
print("\nDONE")
