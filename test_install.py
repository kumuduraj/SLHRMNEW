import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=120):
    print(f'>>> {cmd}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out)
    if err: print(err)
    return out + err

def docker_exec(cmd, timeout=120):
    escaped = cmd.replace('"', '\\"')
    return run(f'docker exec frappe_docker-backend-1 bash -c "{escaped}"', timeout)

# 1. Check doctype dir
docker_exec("ls /home/frappe/frappe-bench/apps/slhrm/slhrm/doctype/ 2>&1")

# 2. Remove slhrm completely
docker_exec("cd /home/frappe/frappe-bench; bench remove-app slhrm 2>&1 || true")
docker_exec("rm -rf /home/frappe/frappe-bench/apps/slhrm")

# 3. Get fresh from GitHub
docker_exec("cd /home/frappe/frappe-bench; bench get-app https://github.com/kumuduraj/SLHRMNEW.git 2>&1", timeout=180)

# 4. Install
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk install-app slhrm 2>&1", timeout=180)

# 5. Migrate
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk migrate 2>&1", timeout=180)

# 6. Clear cache
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk clear-cache 2>&1")

# 7. Build
docker_exec("cd /home/frappe/frappe-bench; bench build --app slhrm 2>&1", timeout=180)

# 8. Verify DocTypes
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \"SELECT name FROM tabDocType WHERE module='SLHRM';\" 2>&1")

# 9. Verify Module Def
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \"SELECT name FROM tabModuleDef WHERE name='SLHRM';\" 2>&1")

# 10. Verify Workspace
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \"SELECT name FROM tabWorkspace WHERE app='slhrm' OR module='SLHRM';\" 2>&1")

# 11. Verify Workspace Sidebar
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \"SELECT name FROM tabWorkspaceSidebar WHERE app='slhrm';\" 2>&1")

# 12. Verify symlinks
docker_exec("ls -la /home/frappe/frappe-bench/apps/slhrm/slhrm/slhrm/ 2>&1")

# 13. is_setup_complete
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \"SELECT app_name, is_setup_complete FROM tabInstalledApplication WHERE app_name='slhrm';\" 2>&1")

# 14. Custom Fields
docker_exec("cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk mariadb -e \"SELECT name FROM tabCustomField WHERE module='SLHRM';\" 2>&1")

ssh.close()
print("DONE")
