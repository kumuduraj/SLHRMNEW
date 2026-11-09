"""v0.0.10: package overrides are effective-dated via a snapshot on each package SSA
(`slhrm_package_components`). Backfill submitted package SSAs that have none with the package's current
rows (before 0.0.10 there was only ever one live package SSA, holding exactly those amounts)."""
import json

import frappe


def execute():
    if not frappe.db.has_column("Salary Structure Assignment", "slhrm_package_components"):
        # post_model_sync patches run before fixtures sync: create SLHRM's custom fields first
        from frappe.utils.fixtures import sync_fixtures

        sync_fixtures("slhrm")
    from slhrm.doctype.employee_salary_package.employee_salary_package import package_snapshot

    for ssa in frappe.get_all(
        "Salary Structure Assignment",
        filters={"slhrm_managed": 1, "docstatus": 1},
        fields=["name", "employee", "slhrm_package_components"],
    ):
        if ssa.slhrm_package_components or not frappe.db.exists("Employee Salary Package", ssa.employee):
            continue
        package = frappe.get_doc("Employee Salary Package", ssa.employee)
        frappe.db.set_value("Salary Structure Assignment", ssa.name, "slhrm_package_components",
                            json.dumps(package_snapshot(package.components)), update_modified=False)
