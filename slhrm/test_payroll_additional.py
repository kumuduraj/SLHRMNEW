import frappe

def execute():
    # Cleanup test Additional Salary records
    frappe.db.sql("UPDATE `tabAdditional Salary` SET docstatus=2 WHERE name IN ('HR-ADS-26-06-00018','HR-ADS-26-06-00019')")
    frappe.db.commit()
    print("Cleaned up test records")
