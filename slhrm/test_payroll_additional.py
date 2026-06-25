import frappe

def execute():
    # Create test Additional Salary records first
    print("=== Creating Test Additional Salary Records ===")
    
    # Check existing
    existing = frappe.db.get_value("Additional Salary", {
        "employee": "EMP-00002",
        "salary_component": "Incentive",
        "docstatus": 1
    }, "name")
    
    if not existing:
        add_sal = frappe.get_doc({
            "doctype": "Additional Salary",
            "employee": "EMP-00002",
            "salary_component": "Incentive",
            "amount": 5000,
            "payroll_date": "2026-06-30",
            "company": "Gills",
            "type": "Earning",
        })
        add_sal.insert(ignore_permissions=True)
        add_sal.submit()
        frappe.db.commit()
        print(f"Created: {add_sal.name}")
    else:
        print(f"Already exists: {existing}")
    
    existing2 = frappe.db.get_value("Additional Salary", {
        "employee": "EMP-00008",
        "salary_component": "Incentive",
        "docstatus": 1
    }, "name")
    
    if not existing2:
        add_sal2 = frappe.get_doc({
            "doctype": "Additional Salary",
            "employee": "EMP-00008",
            "salary_component": "Incentive",
            "amount": 3000,
            "payroll_date": "2026-06-30",
            "company": "Gills",
            "type": "Earning",
        })
        add_sal2.insert(ignore_permissions=True)
        add_sal2.submit()
        frappe.db.commit()
        print(f"Created: {add_sal2.name}")
    else:
        print(f"Already exists: {existing2}")
    
    # Now test load_payroll_data
    print("\n=== Testing load_payroll_data ===")
    result = frappe.get_attr("slhrm.api.load_payroll_data")(
        branch="FORT FUSION",
        company="Gills",
        payroll_month=6,
        payroll_year=2026
    )
    
    print("\n=== Salary Components ===")
    for comp in result.get("salary_components", []):
        print(f"  {comp['name']} ({comp['type']})")
    
    print("\n=== Component Amounts for EMP-00002 ===")
    comp_amounts = result.get("component_amounts", {})
    emp_amounts = comp_amounts.get("EMP-00002", {})
    for comp, amt in emp_amounts.items():
        if amt > 0:
            print(f"  {comp}: {amt}")
    
    print("\n=== Component Amounts for EMP-00008 ===")
    emp_amounts2 = comp_amounts.get("EMP-00008", {})
    for comp, amt in emp_amounts2.items():
        if amt > 0:
            print(f"  {comp}: {amt}")
    
    print("\n=== Employees with Additional Salary ===")
    for emp in result.get("employees", []):
        if emp.get("additional_earning_total", 0) > 0 or emp.get("additional_deduction_total", 0) > 0:
            print(f"  {emp['employee']}: earning={emp.get('additional_earning_total', 0)}, deduction={emp.get('additional_deduction_total', 0)}")
