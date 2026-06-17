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

# Check if sites/slhrm exists and what it contains
print("=== Check sites/slhrm ===")
run('docker exec frappe_docker-backend-1 ls -la /home/frappe/frappe-bench/sites/slhrm/ 2>&1')

# Check the editable install
print("\n=== Check editable install ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; env/bin/pip show slhrm 2>&1"')

# Check what MAPPING frappe uses
print("\n=== Check frappe MAPPING ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/check_mapping.py', 'w') as f:
    f.write("""
import frappe
import os

# Check the MAPPING
print('frappe.MAPPING:', getattr(frappe, 'MAPPING', 'NOT FOUND'))

# Check installed packages
try:
    from importlib.metadata import packages_distributions
    pd = packages_distributions()
    if 'slhrm' in pd:
        print('importlib slhrm:', pd['slhrm'])
except:
    pass

# Check setup.py
setup_path = '/home/frappe/frappe-bench/apps/slhrm/setup.py'
if os.path.exists(setup_path):
    print('setup.py exists')

# Check pyproject.toml
pyproject_path = '/home/frappe/frappe-bench/apps/slhrm/pyproject.toml'
if os.path.exists(pyproject_path):
    print('pyproject.toml:')
    print(open(pyproject_path).read()[:2000])
""")
sftp.close()
run('docker cp /tmp/check_mapping.py frappe_docker-backend-1:/tmp/check_mapping.py')
run("""docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; cat /tmp/check_mapping.py | bench --site desk02.evonet.lk console 2>&1" """, timeout=120)

ssh.close()
print("\nDONE")
