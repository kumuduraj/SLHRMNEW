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

# Write the inspect script into apps directory as a proper Frappe module
sftp = ssh.open_sftp()
with sftp.open('/tmp/check_inspect.py', 'w') as f:
    f.write("""import frappe

def execute():
    frappe.connect(site='desk02.evonet.lk')
    
    # Check installed apps
    installed = frappe.get_installed_apps()
    print('Installed apps:', installed)
    
    # Check tabInstalled Application directly
    rows = frappe.db.sql("SELECT app_name, is_setup_complete FROM `tabInstalled Application`", as_dict=True)
    print('tabInstalled Application rows:', [(r.app_name, r.is_setup_complete) for r in rows])
    
    # Check what get_app_modules returns
    try:
        from frappe.modules.utils import get_app_modules
        mods = get_app_modules('slhrm')
        print('get_app_modules(slhrm):', mods)
    except Exception as e:
        print('get_app_modules error:', e)
    
    # Check modules.txt
    import os
    app_path = frappe.get_app_path('slhrm')
    modules_path = os.path.join(app_path, 'modules.txt')
    print('app_path:', app_path)
    print('modules.txt exists:', os.path.exists(modules_path))
    if os.path.exists(modules_path):
        print('modules.txt content:', open(modules_path).read().strip())
    
    # Check if Module Def exists
    print('Module Def SLHRM:', frappe.db.exists('Module Def', 'SLHRM'))
    
    # Check doctype discovery
    import json
    doctype_path = os.path.join(app_path, 'slhrm', 'doctype')
    if os.path.exists(doctype_path):
        print('DocType dirs:', os.listdir(doctype_path))
    else:
        print('No doctype dir at', doctype_path)
        # Try without the slhrm subdir
        doctype_path2 = os.path.join(app_path, 'doctype')
        if os.path.exists(doctype_path2):
            print('DocType dirs (alt):', os.listdir(doctype_path2))
    
    frappe.db.close()
""")
sftp.close()

# Copy to apps dir
run('docker cp /tmp/check_inspect.py frappe_docker-backend-1:/home/frappe/frappe-bench/apps/check_inspect.py')

# Run as bench execute with module path
run('docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk execute check_inspect.execute"')

# Cleanup
run('docker exec frappe_docker-backend-1 rm /home/frappe/frappe-bench/apps/check_inspect.py')

ssh.close()
print("\nDONE")
