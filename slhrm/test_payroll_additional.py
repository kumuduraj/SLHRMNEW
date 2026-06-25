import frappe

def execute():
    result = frappe.get_attr("slhrm.api.load_payroll_data")(
        branch="FORT FUSION",
        company="Gills",
        payroll_month=6,
        payroll_year=2026
    )

    print("=== Salary Components ===")
    for comp in result.get("salary_components", []):
        print(f"  {comp['name']} ({comp['type']})")

    print("\n=== Component Amounts for EMP-00002 ===")
    comp_amounts = result.get("component_amounts", {})
    emp_amounts = comp_amounts.get("EMP-00002", {})
    for comp, amt in emp_amounts.items():
        if amt > 0:
            print(f"  {comp}: {amt}")

    print("\n=== Employees with Additional Salary ===")
    for emp in result.get("employees", []):
        if emp.get("additional_earning_total", 0) > 0 or emp.get("additional_deduction_total", 0) > 0:
            print(f"  {emp['employee']}: earning={emp.get('additional_earning_total', 0)}, deduction={emp.get('additional_deduction_total', 0)}")
