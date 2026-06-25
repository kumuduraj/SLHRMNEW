import frappe

def execute():
    for name in ["HR-ADS-26-06-00016", "HR-ADS-26-06-00017"]:
        try:
            doc = frappe.get_doc("Additional Salary", name)
            if doc.docstatus == 0:
                doc.submit()
                frappe.db.commit()
                print(f"Submitted: {name}")
            else:
                print(f"Already submitted/cancelled: {name} (docstatus={doc.docstatus})")
        except Exception as e:
            print(f"Error: {name}: {e}")
