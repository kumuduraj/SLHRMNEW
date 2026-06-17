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

# 1. Create missing symlinks manually
docker_exec("cd /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm; ln -sf ../doctype doctype; ln -sf ../public public; ln -sf ../fixtures fixtures; ln -sf ../workspace workspace; ln -sf ../workspace_sidebar workspace_sidebar")

# 2. Verify symlinks
docker_exec("ls -la /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm/")

# 3. Write a verification script and run it
docker_exec("""cat > /tmp/verify_slhrm.py << 'PYEOF'
import frappe
frappe.connect()

print("=== DocTypes ===")
dts = frappe.get_all("DocType", filters={"module": "SLHRM"}, fields=["name"])
print([d.name for d in dts])

print("\n=== Module Def ===")
print(frappe.db.exists("Module Def", "SLHRM"))

print("\n=== Workspace ===")
print(frappe.db.exists("Workspace", "SLHRM"))

print("\n=== Workspace Sidebar ===")
print(frappe.db.exists("Workspace Sidebar", "SLHRM"))

print("\n=== Custom Fields ===")
cfs = frappe.get_all("Custom Field", filters={"module": "SLHRM"}, fields=["name"])
print([f.name for f in cfs])

print("\n=== Desktop Icon ===")
try:
    icons = frappe.get_all("Desktop Icon", filters={"app_name": "slhrm"}, fields=["name"])
    print([i.name for i in icons])
except:
    print("Desktop Icon table not found or different schema")

print("\n=== add_to_apps_screen hooks ===")
print(frappe.get_hooks("add_to_apps_screen"))

print("\n=== Installed Apps ===")
apps = frappe.get_all("Installed Application", fields=["app_name", "app_version", "is_setup_complete"])
for a in apps:
    print(f"  {a.app_name} v{a.app_version} setup={a.is_setup_complete}")

frappe.db.close()
PYEOF""")

docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute /tmp/verify_slhrm.py")

# 4. Clear cache and restart
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk clear-cache")
docker_exec("cd /home/frappe/frappe-bench; bench restart")

ssh.close()
print("\nDONE")
