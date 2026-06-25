"""
Test Bulk Additional Salary complete flow:
1. Create a Bulk Additional Salary document
2. Get employees
3. Set amounts
4. Submit
5. Verify Additional Salary records created
6. Cancel and verify
"""
import frappe


def execute():
    print("=" * 60)
    print("TEST: Bulk Additional Salary Complete Flow")
    print("=" * 60)

    # Step 1: Create Bulk Additional Salary
    print("\n--- Step 1: Creating Bulk Additional Salary ---")
    
    # Check if salary component exists
    comp = frappe.db.get_value("Salary Component", {"type": "Earning"}, "name")
    if not comp:
        print("No Earning type Salary Component found. Creating one...")
        comp_doc = frappe.get_doc({
            "doctype": "Salary Component",
            "salary_component": "Test Bonus",
            "type": "Earning",
            "salary_component_abbr": "TB",
        })
        comp_doc.insert()
        frappe.db.commit()
        comp = comp_doc.name
        print(f"Created Salary Component: {comp}")
    else:
        print(f"Using existing Salary Component: {comp}")
    
    # Get a branch with employees
    branch = frappe.db.get_value("Employee", {"status": "Active", "branch": ["is", "set"]}, "branch")
    if not branch:
        print("No branch with active employees found!")
        return
    
    company = frappe.db.get_value("Employee", {"branch": branch, "status": "Active"}, "company")
    print(f"Using Branch: {branch}, Company: {company}")
    
    # Create the document with employees
    doc = frappe.get_doc({
        "doctype": "Bulk Additional Salary",
        "branch": branch,
        "company": company,
        "salary_component": comp,
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
    print(f"Added {len(doc.employees)} employees to the document")
    
    # Step 3: Verify totals
    print("\n--- Step 3: Verifying Totals ---")
    print(f"Total Employees: {doc.total_employees}")
    print(f"Total Amount: {doc.total_amount}")
    
    # Step 4: Submit
    print("\n--- Step 4: Submitting ---")
    doc.submit()
    frappe.db.commit()
    print(f"Submitted: {doc.name}")
    print(f"Additional Salaries Created: {doc.additional_salaries_created}")
    
    # Step 5: Verify Additional Salary records
    print("\n--- Step 5: Verifying Additional Salary Records ---")
    
    for row in doc.employees:
        if row.additional_salary:
            add_sal = frappe.get_doc("Additional Salary", row.additional_salary)
            print(f"  {row.employee}: {add_sal.name} | Amount: {add_sal.amount} | Status: {row.status}")
        else:
            print(f"  {row.employee}: No Additional Salary created | Status: {row.status}")
    
    # Step 6: Cancel
    print("\n--- Step 6: Cancelling ---")
    doc.cancel()
    frappe.db.commit()
    print(f"Cancelled: {doc.name}")
    
    # Verify cancellation
    for row in doc.employees:
        print(f"  {row.employee}: Status: {row.status} | Additional Salary: {row.additional_salary}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
