import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=120):
    print(f'>>> {cmd[:200]}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip()[:3000])
    if err: print('ERR: ' + err.strip()[:3000])
    return out

db = '_1f5b1f23ca2e8149'
pw = 'cotEpWmNqlH0cyNg'

# Use MariaDB directly with password
print("=== Direct MariaDB queries ===")
queries = [
    f"SELECT COUNT(*) as cnt FROM `{db}`.tabDocType WHERE module='SLHRM'",
    f"SELECT name FROM `{db}`.tabDocType WHERE module='SLHRM' LIMIT 10",
    f"SHOW TABLES FROM `{db}` LIKE '%Module%'",
    f"SHOW TABLES FROM `{db}` LIKE '%Workspace%'",
    f"SHOW TABLES FROM `{db}` LIKE '%CustomField%'",
    f"SHOW TABLES FROM `{db}` LIKE '%Installed%'",
    f"SHOW TABLES FROM `{db}` LIKE '%Desktop%'",
    f"SELECT COUNT(*) as total_doctypes FROM `{db}`.tabDocType",
]

for q in queries:
    run(f'docker exec frappe_docker-backend-1 mariadb -u root -p{pw} -e "{q}"')

# Check all tables count
run(f'docker exec frappe_docker-backend-1 mariadb -u root -p{pw} -e "SELECT COUNT(*) as total_tables FROM information_schema.tables WHERE table_schema=\\\"{db}\\\""')

# Check if slhrm is in installed_apps in site_config
run(f'docker exec frappe_docker-backend-1 cat /home/frappe/frappe-bench/sites/desk02.evonet.lk/site_config.json')

# Check if custom_attendance is blocking things
run(f'docker exec frappe_docker-backend-1 ls /home/frappe/frappe-bench/apps/')

ssh.close()
print("\nDONE")
