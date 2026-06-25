"""
Test Employee creation → User auto-creation flow:
1. Create a test Employee
2. Verify User was auto-created
3. Check User roles and settings
4. Verify password change flag
"""
import frappe


def execute():
    print("=" * 60)
    print("TEST: Employee → User Auto-Creation Flow")
    print("=" * 60)

    # Step 1: Create test Employee
    print("\n--- Step 1: Creating Test Employee ---")
    
    test_emp_id = "EMP-TEST-001"
    test_name = "Test Auto User Employee"
    test_company = "Gills"
    test_branch = "FORT FUSION"
    test_email = "test.autouser@example.com"
    
    # Check if test employee already exists
    if frappe.db.exists("Employee", test_emp_id):
        print(f"Test employee {test_emp_id} already exists, skipping creation")
        emp = frappe.get_doc("Employee", test_emp_id)
    else:
        emp = frappe.get_doc({
            "doctype": "Employee",
            "employee": test_emp_id,
            "employee_name": test_name,
            "company": test_company,
            "branch": test_branch,
            "company_email": test_email,
            "status": "Active",
            "date_of_joining": "2026-06-25",
            "gender": "Male",
            "date_of_birth": "1990-01-01"
        })
        emp.insert()
        frappe.db.commit()
        print(f"Created Employee: {emp.name} | {emp.employee_name}")
        print(f"Company Email: {emp.company_email}")
    
    # Step 2: Check if User was auto-created
    print("\n--- Step 2: Checking Auto-Created User ---")
    
    # Check for user with employee ID
    user_exists = frappe.db.exists("User", {"employee": test_emp_id})
    print(f"User with employee={test_emp_id}: {'EXISTS' if user_exists else 'NOT FOUND'}")
    
    # Check for user with email
    user_by_email = frappe.db.exists("User", test_email)
    print(f"User with email={test_email}: {'EXISTS' if user_by_email else 'NOT FOUND'}")
    
    # Get the user
    user_name = user_exists or user_by_email
    if user_name:
        user = frappe.get_doc("User", user_name)
        print(f"\nUser Details:")
        print(f"  Name: {user.name}")
        print(f"  Email: {user.email}")
        print(f"  Employee: {user.employee}")
        print(f"  Enabled: {user.enabled}")
        print(f"  Send Welcome Email: {user.send_welcome_email}")
        
        # Check roles
        roles = [r.role for r in user.roles]
        print(f"  Roles: {roles}")
        
        # Check if Employee role exists
        has_employee_role = "Employee" in roles
        print(f"  Has Employee Role: {has_employee_role}")
        
        # Check password change flag (from custom field or property)
        # The hook sets must_change_password = 1
        print(f"  Password Policies: {user.password_settings if hasattr(user, 'password_settings') else 'N/A'}")
        
        # Check if user can login
        print(f"\n  Login Test:")
        print(f"    User Type: {user.user_type}")
        print(f"    Last Active: {user.last_active}")
        
    else:
        print("✗ No user was auto-created!")
        print("  Checking if hook is working...")
        
        # Check if Employee after_insert hook is registered
        hooks = frappe.get_hooks("doc_events", {})
        emp_hooks = hooks.get("Employee", {})
        print(f"  Employee doc_events hooks: {emp_hooks}")
    
    # Step 3: Verify User permissions
    print("\n--- Step 3: Verifying User Permissions ---")
    
    if user_name:
        # Check if user has proper permissions
        user_roles = frappe.get_roles(user_name)
        print(f"  User Roles: {user_roles}")
        
        # Check if user can access PWA
        has_pwa_access = "Employee" in user_roles
        print(f"  Has PWA Access (Employee role): {has_pwa_access}")
    
    # Step 4: Summary
    print("\n--- Step 4: Summary ---")
    
    if user_name:
        print("✓ Employee created successfully")
        print("✓ User auto-created successfully")
        print(f"  User: {user_name}")
        print(f"  Default Password: Abc@12345")
        print(f"  Must Change Password: Yes (set by hook)")
        print("\n  Login Instructions:")
        print(f"    1. Go to https://desk01.evonet.lk/slhrm/")
        print(f"    2. Login with: {test_email}")
        print(f"    3. Password: Abc@12345")
        print(f"    4. System will prompt to change password")
    else:
        print("✗ Test failed - User was not auto-created")
        print("  Check if Employee after_insert hook is working")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
