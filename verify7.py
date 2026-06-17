import paramiko
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('62.72.12.15', username='rajerp', password='esanatech@12', timeout=30)

def run(cmd, timeout=120):
    print(f'>>> {cmd[:250]}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.strip()[:3000])
    if err: print('ERR: ' + err.strip()[:1000])
    return out

db = '_1f5b1f23ca2e8149'
pw = 'cotEpWmNqlH0cyNg'

# MariaDB is in frappe_docker-db-1 container
# Use backtick-quoted database name to avoid bash issues
print("=== Direct queries via DB container ===")
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT COUNT(*) as slhrm_dts FROM `{db}`.tabDocType WHERE module=\\\"SLHRM\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.tabDocType WHERE module=\\\"SLHRM\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.\\\"tabModule Def\\\" WHERE name=\\\"SLHRM\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.tabWorkspace WHERE module=\\\"SLHRM\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.\\\"tabWorkspace Sidebar\\\" WHERE app=\\\"slhrm\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.\\\"tabInstalled Application\\\" WHERE app_name=\\\"slhrm\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.tabCustomField WHERE module=\\\"SLHRM\\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SHOW TABLES FROM `{db}` LIKE \\"%Module%\\""')
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SHOW TABLES FROM `{db}` LIKE \\"%CustomField%\\""')

# If DocTypes exist, try re-running sync
print("\n=== Force re-sync DocTypes ===")
run(f'docker exec frappe_docker-backend-1 bash -c "cd /home/frappe/frappe-bench; bench --site desk02.evonet.lk migrate --skip-search-index 2>&1"')

# Check again
run(f'docker exec frappe_docker-db-1 mariadb -u root -p{pw} -e "SELECT name FROM `{db}`.tabDocType WHERE module=\\\"SLHRM\\\""')

ssh.close()
print("\nDONE")
