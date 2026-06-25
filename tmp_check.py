import frappe
import os

os.chdir('/home/frappe/frappe-bench/sites')
frappe.init('desk01.evonet.lk')
frappe.connect()

# Simulate the exact query from load_payroll_data
emp_names = ['EMP-00107', 'EMP-00108']
esp_rows = frappe.db.sql("""
    SELECT esp.employee, espd.salary_component, espd.amount
    FROM `tabEmployee Salary Package` esp
    INNER JOIN `tabEmployee Salary Package Detail` espd ON espd.parent = esp.name
    WHERE esp.employee IN %(employees)s AND espd.amount > 0
""", {"employees": emp_names}, as_dict=True)

print("=== Package query results ===")
for r in esp_rows:
    print(f"  {r.employee} | {r.salary_component} | {r.amount}")

# Check what the final ssa_components_map would look like
ssa_components_map = {}
for row in esp_rows:
    ssa_components_map.setdefault(row.employee, {})[row.salary_component] = flt(row.amount)

print("\n=== ssa_components_map ===")
for emp, comps in ssa_components_map.items():
    print(f"  {emp}: {comps}")

# Check how employee data is built
employees_raw = frappe.get_all("Employee", filters={"status": "Active", "branch": "LITTLE JAPAN"}, fields=["name", "employee_name", "designation"])

# Simulate the SSA query
ssas = frappe.db.sql("""
    SELECT ssa.name, ssa.employee, ssa.base, ssa.salary_structure
    FROM `tabSalary Structure Assignment` ssa
    INNER JOIN (
        SELECT employee, MAX(from_date) as max_date
        FROM `tabSalary Structure Assignment`
        WHERE employee IN %(employees)s AND docstatus = 1
        GROUP BY employee
    ) latest ON ssa.employee = latest.employee AND ssa.from_date = latest.max_date
    WHERE ssa.docstatus = 1
""", {"employees": [e.name for e in employees_raw]}, as_dict=True)

print(f"\n=== SSAs found: {len(ssas)} ===")
for s in ssas:
    comp_amounts = ssa_components_map.get(s.employee, {})
    print(f"  {s.employee} | base={s.base} | components={comp_amounts}")

frappe.destroy()
