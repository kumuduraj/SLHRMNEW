import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def docker_exec(cmd, timeout=120):
    escaped = cmd.replace('"', '\\"')
    print(f'>>> {cmd}')
    stdin, stdout, stderr = ssh.exec_command(f'docker exec frappe_docker-backend-1 bash -c "{escaped}"', timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip())
    if err: print(err.strip())
    return out

SCRIPT = """import frappe
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
for f in cfs:
    print('  ' + f.name)
print('Total: ' + str(len(cfs)))
print('--- Hooks ---')
print(str(frappe.get_hooks('add_to_apps_screen')))
print('--- Installed Apps ---')
apps = frappe.get_all('Installed Application', fields=['app_name', 'app_version', 'is_setup_complete'])
for a in apps:
    print('  ' + a.app_name + ' v' + str(a.app_version) + ' setup=' + str(a.is_setup_complete))
frappe.db.close()
"""

# Write script via SSH stdin
transport = ssh.get_transport()
chan = transport.open_session()
chan.exec_command('docker exec -i frappe_docker-backend-1 bash -c "cat > /home/frappe/frappe-bench/verify_slhrm.py"')
stdin = chan.makefile('w')
stdin.write(SCRIPT)
stdin.close()
exit_code = chan.recv_exit_status()
print(f"Write script exit code: {exit_code}")

# Execute it
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute verify_slhrm")

# Cleanup
docker_exec("rm /home/frappe/frappe-bench/verify_slhrm.py")

ssh.close()
print("\nDONE")
