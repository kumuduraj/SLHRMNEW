import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
    # Remove old SLHRM custom fields from SSA (replaced by Employee Salary Package)
    old_fields = [
        "Salary Structure Assignment-slhrm_salary_components_section",
        "Salary Structure Assignment-slhrm_components",
        "Salary Structure Assignment-slhrm_components_html",
    ]
    for field_name in old_fields:
        if frappe.db.exists("Custom Field", field_name):
            frappe.delete_doc("Custom Field", field_name, ignore_permissions=True)

    custom_fields = {
        "Salary Structure Assignment": [
            {
                "fieldname": "slhrm_managed",
                "label": "Managed by SLHRM",
                "fieldtype": "Check",
                "insert_after": "base",
                "read_only": 1,
                "hidden": 1,
                "default": "0",
                "description": "If checked, this SSA is managed by Employee Salary Package. Do not edit manually.",
            },
            {
                "fieldname": "slhrm_package_link",
                "label": "Employee Salary Package",
                "fieldtype": "Link",
                "options": "Employee Salary Package",
                "insert_after": "slhrm_managed",
                "read_only": 1,
                "hidden": 0,
                "depends_on": "eval:doc.slhrm_managed",
                "description": "Link to the Employee Salary Package that manages this SSA.",
            },
        ]
    }

    create_custom_fields(custom_fields, update=True)
