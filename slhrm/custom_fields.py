import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
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
