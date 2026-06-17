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
    if out: print(out.strip()[:8000])
    if err: print('ERR: ' + err.strip()[:2000])
    return out

sftp = ssh.open_sftp()

# Step 1: Force install with all options
print("=== STEP 1: Force install with force=True ===")
with sftp.open('/tmp/force3.py', 'w') as f:
    f.write("""
import frappe
frappe.connect(site='desk02.evonet.lk')

# Delete from DB first
frappe.db.sql("SET SQL_SAFE_UPDATES=0")
frappe.db.sql("DELETE FROM `tabInstalled Application` WHERE app_name='slhrm'")
frappe.db.commit()

# Clear cache
frappe.clear_cache()

# Verify cleared
installed = frappe.get_installed_apps()
print('After clear_cache, installed:', installed)

# Now try force install
from frappe.installer import install_app
import inspect
sig = inspect.signature(install_app)
print('install_app signature:', sig)

# Try with force
try:
    install_app('slhrm', verbose=True, force=True)
    frappe.db.commit()
    print('FORCE INSTALL SUCCEEDED!')
except TypeError:
    # Try without force
    try:
        install_app('slhrm', verbose=True)
        frappe.db.commit()
        print('INSTALL SUCCEEDED (no force)!')
    except Exception as e2:
        print('INSTALL ERROR:', e2)
        import traceback
        traceback.print_exc()
except Exception as e:
    print('INSTALL ERROR:', e)
    import traceback
    traceback.print_exc()

# Verify
print()
print('=== VERIFY ===')
dts = frappe.get_all('DocType', filters={'module': 'SLHRM'}, fields=['name'])
print('DocTypes:', [d.name for d in dts])
print('Module Def:', frappe.db.exists('Module Def', 'SLHRM'))
print('Workspace:', frappe.db.exists('Workspace', 'SLHRM'))
print('Sidebar:', frappe.db.exists('Workspace Sidebar', 'SLHRM'))
cfs = frappe.get_all('Custom Field', filters={'module': 'SLHRM'}, fields=['name'])
print('Custom Fields:', [c.name for c in cfs])

frappe.db.close()
""")
sftp.close()
run('docker cp /tmp/force3.py frappe_docker-backend-1:/tmp/force3.py')
run("""docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; cat /tmp/force3.py | bench --site desk02.evonet.lk console 2>&1" """, timeout=300)

ssh.close()
print("\nDONE")
