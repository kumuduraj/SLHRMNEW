"""
Test Bulk Additional Salary complete flow:
1. Create a Bulk Additional Salary document (Earning)
2. Get employees
3. Set amounts
4. Submit
5. Verify Additional Salary records created
6. Cancel and verify
7. Test with Deduction component
"""
import frappe


def execute():
    print("=" * 60)
    print("TEST: Bulk Additional Salary Complete Flow")
    print("=" * 60)

    # Step 1: Create Bulk Additional Salary (Earning type)
    print("\n--- Step 1: Creating Bulk Additional Salary (Earning) ---")
    
    earning_comp = frappe.db.get_value("Salary Component", {"type": "Earning"}, "name")
    if not earning_comp:
        print("No Earning type Salary Component found. Creating one...")
        comp_doc = frappe.get_doc({
            "doctype": "Salary Component",
            "salary_component": "Test Bonus",
            "type": "Earning",
            "salary_component_abbr": "TB",
        })
        comp_doc.insert()
        frappe.db.commit()
        earning_comp = comp_doc.name
        print(f"Created Salary Component: {earning_comp}")
    else:
        print(f"Using existing Earning Component: {earning_comp}")
    
    # Get a branch with employees that have SSAs
    branches_with_ssa = frappe.db.sql("""
        SELECT DISTINCT e.branch
        FROM `tabEmployee` e
        INNER JOIN `tabSalary Structure Assignment` ssa 
            ON ssa.employee = e.name AND ssa.docstatus = 1
        WHERE e.status = 'Active'
    """, as_dict=True)
    
    if not branches_with_ssa:
        print("No employees with SSAs found!")
        return
    
    branch = branches_with_ssa[0].branch
    company = frappe.db.get_value("Employee", {"branch": branch, "status": "Active"}, "company")
    print(f"Using Branch: {branch}, Company: {company}")
    
    # Create the document with employees
    doc = frappe.get_doc({
        "doctype": "Bulk Additional Salary",
        "branch": branch,
        "company": company,
        "salary_component": earning_comp,
        "payroll_month": "June",
        "payroll_year": 2026,
        "default_amount": 5000,
    })
    
    # Get employees first
    employees = frappe.get_attr("slhrm.slhrm.doctype.bulk_additional_salary.bulk_additional_salary.get_employees")(
        branch=branch,
        company=company,
        default_amount=5000
    )
    print(f"Found {len(employees)} employees")
    
    # Add employees to the document
    for emp in employees[:3]:  # Only add first 3 for testing
        doc.append("employees", {
            "employee": emp["employee"],
            "employee_name": emp["employee_name"],
            "designation": emp["designation"],
            "department": emp["department"],
            "amount": emp["amount"],
            "status": emp["status"],
        })
    
    doc.insert()
    frappe.db.commit()
    print(f"Created Bulk Additional Salary: {doc.name}")
    print(f"Component Type: {doc.component_type}")
    print(f"Added {len(doc.employees)} employees")
    
    # Verify totals
    print("\n--- Verifying Totals ---")
    print(f"Total Employees: {doc.total_employees}")
    print(f"Total Amount: {doc.total_amount}")
    
    # Submit
    print("\n--- Submitting (Earning) ---")
    doc.submit()
    frappe.db.commit()
    print(f"Submitted: {doc.name}")
    print(f"Additional Salaries Created: {doc.additional_salaries_created}")
    
    # Verify Additional Salary records
    print("\n--- Verifying Additional Salary Records ---")
    for row in doc.employees:
        if row.additional_salary:
            add_sal = frappe.get_doc("Additional Salary", row.additional_salary)
            print(f"  {row.employee}: {add_sal.name} | Amount: {add_sal.amount} | Type: {add_sal.type} | Status: {row.status}")
        else:
            print(f"  {row.employee}: No Additional Salary created | Status: {row.status}")
    
    # Cancel
    print("\n--- Cancelling ---")
    doc.cancel()
    frappe.db.commit()
    print(f"Cancelled: {doc.name}")
    
    # =====================================================
    # TEST 2: Deduction component
    # =====================================================
    print("\n" + "=" * 60)
    print("TEST 2: Bulk Additional Salary (Deduction)")
    print("=" * 60)
    
    deduction_comp = frappe.db.get_value("Salary Component", {"type": "Deduction"}, "name")
    if not deduction_comp:
        print("No Deduction type Salary Component found. Creating one...")
        comp_doc = frappe.get_doc({
            "doctype": "Salary Component",
            "salary_component": "Test Deduction",
            "type": "Deduction",
            "salary_component_abbr": "TD",
        })
        comp_doc.insert()
        frappe.db.commit()
        deduction_comp = comp_doc.name
        print(f"Created Salary Component: {deduction_comp}")
    else:
        print(f"Using existing Deduction Component: {deduction_comp}")
    
    # Create deduction document
    doc2 = frappe.get_doc({
        "doctype": "Bulk Additional Salary",
        "branch": branch,
        "company": company,
        "salary_component": deduction_comp,
        "payroll_month": "June",
        "payroll_year": 2026,
        "default_amount": 2000,
    })
    
    # Add employees
    for emp in employees[:3]:
        doc2.append("employees", {
            "employee": emp["employee"],
            "employee_name": emp["employee_name"],
            "designation": emp["designation"],
            "department": emp["department"],
            "amount": 2000,
            "status": "Pending",
        })
    
    doc2.insert()
    frappe.db.commit()
    print(f"Created Bulk Additional Salary: {doc2.name}")
    print(f"Component Type: {doc2.component_type}")
    
    # Submit
    print("\n--- Submitting (Deduction) ---")
    doc2.submit()
    frappe.db.commit()
    print(f"Submitted: {doc2.name}")
    print(f"Additional Salaries Created: {doc2.additional_salaries_created}")
    
    # Verify Additional Salary records
    print("\n--- Verifying Additional Salary Records ---")
    for row in doc2.employees:
        if row.additional_salary:
            add_sal = frappe.get_doc("Additional Salary", row.additional_salary)
            print(f"  {row.employee}: {add_sal.name} | Amount: {add_sal.amount} | Type: {add_sal.type} | Status: {row.status}")
        else:
            print(f"  {row.employee}: No Additional Salary created | Status: {row.status}")
    
    # Cancel
    print("\n--- Cancelling ---")
    doc2.cancel()
    frappe.db.commit()
    print(f"Cancelled: {doc2.name}")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
