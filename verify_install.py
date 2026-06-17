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
    if out: print(out)
    if err: print(err)
    return out

# Get site DB name
docker_exec("cd /home/frappe/frappe-bench; python -c \"import json; c=json.load(open('sites/desk02.evonet.lk/site_config.json')); print(c.get('db_name','?'))\"")

# Use bench console to check
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute -c \"import frappe; print('DocTypes:', [d.name for d in frappe.get_all('DocType', filters={'module': 'SLHRM'}, fields=['name'])])\"")
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute -c \"import frappe; print('ModuleDef:', frappe.db.exists('Module Def', 'SLHRM'))\"")
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute -c \"import frappe; print('Workspace:', frappe.db.exists('Workspace', 'SLHRM'))\"")
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute -c \"import frappe; print('Sidebar:', frappe.db.exists('Workspace Sidebar', 'SLHRM'))\"")
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute -c \"import frappe; print('CustomFields:', [f.name for f in frappe.get_all('Custom Field', filters={'module': 'SLHRM'}, fields=['name'])])\"")
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute -c \"import frappe; print('Hooks:', frappe.get_hooks('add_to_apps_screen'))\"")

# Check symlinks
docker_exec("ls -la /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm/")

# Check assets
docker_exec("ls /home/frappe/frappe-bench/sites/desk02.evonet.lk/public/assets/slhrm/ 2>&1 || echo 'No slhrm assets'")

ssh.close()
print("\nDONE")
