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

# Step 1: Remove the broken sites/slhrm directory
print("=== STEP 1: Remove sites/slhrm ===")
run('docker exec frappe_docker-backend-1 bash -c "rm -rf /home/frappe/frappe-bench/sites/slhrm"')

# Step 2: Verify apps/slhrm/slhrm/slhrm/ has correct structure
print("\n=== STEP 2: Verify apps/slhrm structure ===")
run('docker exec frappe_docker-backend-1 ls -la /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm/ 2>&1')

# Step 3: Create symlinks in apps/slhrm/slhrm/slhrm/ if missing
print("\n=== STEP 3: Create missing symlinks ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm; ln -sf ../doctype doctype 2>/dev/null; ln -sf ../public public 2>/dev/null; ln -sf ../fixtures fixtures 2>/dev/null; ln -sf ../workspace workspace 2>/dev/null; ln -sf ../workspace_sidebar workspace_sidebar 2>/dev/null; ls -la"')

# Step 4: Verify import resolution
print("\n=== STEP 4: Verify import ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/fix_import.py', 'w') as f:
    f.write("""
import frappe
import importlib
import os

# Check what import slhrm resolves to
spec = importlib.util.find_spec('slhrm')
print('slhrm spec origin:', spec.origin if spec else 'NOT FOUND')
print('slhrm spec submodule_search_locations:', spec.submodule_search_locations if spec else 'N/A')

# Check frappe.get_app_path
app_path = frappe.get_app_path('slhrm')
print('frappe.get_app_path:', app_path)

# Verify the path is correct
expected = '/home/frappe/frappe-bench/apps/slhrm/slhrm'
print('Expected:', expected)
print('Match:', app_path == expected)

# Check modules.txt at correct location
modules_path = os.path.join(app_path, 'modules.txt')
print('modules.txt exists:', os.path.exists(modules_path))
if os.path.exists(modules_path):
    print('modules.txt:', open(modules_path).read().strip())

# Check doctype dir
dt_path = os.path.join(app_path, 'slhrm', 'doctype')
print('doctype dir:', os.path.exists(dt_path), os.listdir(dt_path) if os.path.exists(dt_path) else 'N/A')
""")
sftp.close()
run('docker cp /tmp/fix_import.py frappe_docker-backend-1:/tmp/fix_import.py')
run("""docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; cat /tmp/fix_import.py | bench --site desk02.evonet.lk console 2>&1" """, timeout=120)

# Step 5: Force install
print("\n=== STEP 5: Force install ===")
sftp = ssh.open_sftp()
with sftp.open('/tmp/force_install2.py', 'w') as f:
    f.write("""
import frappe

frappe.connect(site='desk02.evonet.lk')

# Check installed apps
installed = frappe.get_installed_apps()
print('Currently installed:', installed)

# Remove slhrm from installed apps if present
if 'slhrm' in installed:
    frappe.db.sql("DELETE FROM `tabInstalled Application` WHERE app_name='slhrm'")
    frappe.db.commit()
    print('Removed slhrm from installed apps')

# Try to install
try:
    from frappe.installer import install_app
    install_app('slhrm', verbose=True)
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
""")
sftp.close()
run('docker cp /tmp/force_install2.py frappe_docker-backend-1:/tmp/force_install2.py')
run("""docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; cat /tmp/force_install2.py | bench --site desk02.evonet.lk console 2>&1" """, timeout=300)

# Step 6: Build + restart
print("\n=== STEP 6: Build + restart ===")
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench build --app slhrm 2>&1"', timeout=300)
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk clear-cache 2>&1"')
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench restart 2>&1"')

ssh.close()
print("\nDONE")
