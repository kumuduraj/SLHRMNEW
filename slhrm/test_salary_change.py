"""
Test salary change flow:
1. Edit Employee Salary Package (change amounts)
2. Verify old SSA is cancelled
3. Verify new SSA is created with updated amounts
"""
import frappe


def execute():
    print("=" * 60)
    print("TEST: Salary Change Flow")
    print("=" * 60)

    # Step 1: Get current state
    print("\n--- Step 1: Current State ---")
    
    # Get current package for EMP-00107
    pkg = frappe.db.get_value(
        "Employee Salary Package",
        "EMP-00107",
        ["name", "employee", "salary_structure", "total_earning", "current_ssa", "docstatus"],
        as_dict=True
    )
    print(f"Package: {pkg.name} | Employee: {pkg.employee} | SS: {pkg.salary_structure}")
    print(f"Current SSA: {pkg.current_ssa} | Total Earning: {pkg.total_earning} | Docstatus: {pkg.docstatus}")
    
    # Get current SSA
    if pkg.current_ssa:
        ssa = frappe.db.get_value(
            "Salary Structure Assignment",
            pkg.current_ssa,
            ["name", "employee", "salary_structure", "base", "docstatus", "slhrm_managed"],
            as_dict=True
        )
        print(f"SSA: {ssa.name} | Base: {ssa.base} | Docstatus: {ssa.docstatus} | Managed: {ssa.slhrm_managed}")
    
    # Get current components
    components = frappe.db.get_all(
        "Employee Salary Package Detail",
        filters={"parent": "EMP-00107"},
        fields=["salary_component", "amount", "override"],
        order_by="idx"
    )
    print("\nCurrent Components:")
    for c in components:
        print(f"  {c.salary_component}: {c.amount} | Override: {c.override}")
    
    # Step 2: Modify the package
    print("\n--- Step 2: Modifying Package ---")
    print("Changing BS from 30,000 to 35,000")
    
    # Load the package document
    doc = frappe.get_doc("Employee Salary Package", "EMP-00107")
    
    # Update BS amount
    for comp in doc.components:
        if comp.salary_component == "Basic Salary":
            comp.amount = 35000
            print(f"Updated {comp.salary_component}: {comp.amount}")
    
    # Update total
    doc.total_earning = 35000
    
    # Save the document (this should trigger manage_ssa)
    doc.save()
    frappe.db.commit()
    
    print(f"Package saved. New total_earning: {doc.total_earning}")
    print(f"Current SSA: {doc.current_ssa}")
    
    # Step 3: Verify SSA changes
    print("\n--- Step 3: Verifying SSA Changes ---")
    
    # Check if old SSA was cancelled
    old_ssa_name = pkg.current_ssa
    if old_ssa_name:
        old_ssa = frappe.db.get_value(
            "Salary Structure Assignment",
            old_ssa_name,
            ["name", "docstatus"],
            as_dict=True
        )
        print(f"Old SSA ({old_ssa.name}) docstatus: {old_ssa.docstatus} (0=Draft, 1=Submitted, 2=Cancelled)")
        if old_ssa.docstatus == 2:
            print("✓ Old SSA correctly cancelled")
        else:
            print("✗ Old SSA NOT cancelled!")
    
    # Check for new SSA
    new_ssas = frappe.db.get_all(
        "Salary Structure Assignment",
        filters={
            "employee": "EMP-00107",
            "docstatus": 1,
            "slhrm_managed": 1
        },
        fields=["name", "base", "from_date", "docstatus"],
        order_by="from_date DESC"
    )
    
    print(f"\nActive SSAs for EMP-00107: {len(new_ssas)}")
    for ssa in new_ssas:
        print(f"  {ssa.name} | Base: {ssa.base} | From: {ssa.from_date} | Docstatus: {ssa.docstatus}")
    
    # Step 4: Verify amounts
    print("\n--- Step 4: Verifying Amounts ---")
    
    # Check updated package
    updated_pkg = frappe.db.get_value(
        "Employee Salary Package",
        "EMP-00107",
        ["total_earning", "current_ssa", "current_ssa_base"],
        as_dict=True
    )
    print(f"Updated Package: total_earning={updated_pkg.total_earning}, current_ssa_base={updated_pkg.current_ssa_base}")
    
    # Check new SSA base
    if new_ssas:
        new_ssa_base = new_ssas[0].base
        print(f"New SSA Base: {new_ssa_base}")
        
        if new_ssa_base == 35000:
            print("✓ SSA base matches package total_earning")
        else:
            print(f"✗ SSA base ({new_ssa_base}) does NOT match package total_earning (35000)")
    
    # Step 5: Check package components
    print("\n--- Step 5: Package Components After Change ---")
    updated_components = frappe.db.get_all(
        "Employee Salary Package Detail",
        filters={"parent": "EMP-00107"},
        fields=["salary_component", "amount", "override"],
        order_by="idx"
    )
    for c in updated_components:
        print(f"  {c.salary_component}: {c.amount} | Override: {c.override}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
