import paramiko
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=120):
    print(f'>>> {cmd[:150]}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip()[:3000])
    if err: print(err.strip()[:3000])
    return out + err

# Write script to bench directory (inside container) via SFTP to host, then docker cp
sftp = ssh.open_sftp()
with sftp.open('/tmp/check.py', 'w') as f:
    f.write("""import frappe
frappe.connect()
print('--- DocTypes ---')
dts = frappe.get_all('DocType', filters={'module': 'SLHRM'}, fields=['name'])
for d in dts:
    print('  ' + d.name)
print('Total: ' + str(len(dts)))
print('--- Module Def ---')
print(str(frappe.db.exists('Module Def', 'SLHRM')))
print('--- Workspace ---')
print(str(frappe.db.exists('Workspace', 'SLHRM')))
print('--- Workspace Sidebar ---')
print(str(frappe.db.exists('Workspace Sidebar', 'SLHRM')))
print('--- Custom Fields ---')
cfs = frappe.get_all('Custom Field', filters={'module': 'SLHRM'}, fields=['name'])
for cf in cfs:
    print('  ' + cf.name)
print('Total: ' + str(len(cfs)))
print('--- Hooks ---')
print(str(frappe.get_hooks('add_to_apps_screen')))
print('--- Installed Apps ---')
apps = frappe.get_all('Installed Application', fields=['app_name', 'app_version', 'is_setup_complete'])
for a in apps:
    print('  ' + a.app_name + ' v' + str(a.app_version) + ' setup=' + str(a.is_setup_complete))
frappe.db.close()
""")
sftp.close()

# Copy to container
run('docker cp /tmp/check.py frappe_docker-backend-1:/home/frappe/frappe-bench/check.py')

# Run via bench console using -c flag with heredoc
run("""docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk console -c 'exec(open(\\\"/home/frappe/frappe-bench/check.py\\\").read())'" """)

# Cleanup
run('docker exec frappe_docker-backend-1 rm /home/frappe/frappe-bench/check.py')

ssh.close()
print("\nDONE")
