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

SCRIPT = """
import frappe
import os, json

frappe.connect(site='desk02.evonet.lk')

# Check installed apps
installed = frappe.get_installed_apps()
print('Installed apps:', installed)

# Check tabInstalled Application
rows = frappe.db.sql("SELECT app_name, is_setup_complete FROM `tabInstalled Application`", as_dict=True)
print('tabInstalled Application:', [(r.app_name, r.is_setup_complete) for r in rows])

# Check get_app_modules
try:
    from frappe.modules.utils import get_app_modules
    mods = get_app_modules('slhrm')
    print('get_app_modules(slhrm):', mods)
except Exception as e:
    print('get_app_modules error:', e)

# Check app path and modules.txt
app_path = frappe.get_app_path('slhrm')
print('app_path:', app_path)
modules_path = os.path.join(app_path, 'modules.txt')
print('modules.txt at app_path:', os.path.exists(modules_path))
if os.path.exists(modules_path):
    print('modules.txt:', open(modules_path).read().strip())

# Check package level
pkg_path = os.path.join(app_path, 'slhrm')
print('pkg_path:', pkg_path)
modules_path2 = os.path.join(pkg_path, 'modules.txt')
print('modules.txt at pkg_path:', os.path.exists(modules_path2))
if os.path.exists(modules_path2):
    print('pkg modules.txt:', open(modules_path2).read().strip())

# Check doctype dirs
dt_path = os.path.join(pkg_path, 'doctype')
print('doctype dir:', os.path.exists(dt_path), os.listdir(dt_path) if os.path.exists(dt_path) else 'N/A')

# Check Module Def
print('Module Def:', frappe.db.exists('Module Def', 'SLHRM'))

# Now force install
print()
print('=== FORCING INSTALL ===')
try:
    from frappe.installer import install_app
    install_app('slhrm', site='desk02.evonet.lk', verbose=True)
    frappe.db.commit()
    print('INSTALL SUCCEEDED!')
except Exception as e:
    print('INSTALL ERROR:', e)
    import traceback
    traceback.print_exc()

# Verify
print()
print('=== VERIFY ===')
print('DocTypes:', [d.name for d in frappe.get_all('DocType', filters={'module': 'SLHRM'}, fields=['name'])])
print('Module Def:', frappe.db.exists('Module Def', 'SLHRM'))
print('Workspace:', frappe.db.exists('Workspace', 'SLHRM'))
print('Sidebar:', frappe.db.exists('Workspace Sidebar', 'SLHRM'))

frappe.db.close()
"""

# Write script to host
sftp = ssh.open_sftp()
with sftp.open('/tmp/run_console.py', 'w') as f:
    f.write(SCRIPT)
sftp.close()

# Use cat pipe into bench console
run("docker cp /tmp/run_console.py frappe_docker-backend-1:/tmp/run_console.py")
run("""docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; cat /tmp/run_console.py | bench --site desk02.evonet.lk console 2>&1" """, timeout=300)

ssh.close()
print("\nDONE")
