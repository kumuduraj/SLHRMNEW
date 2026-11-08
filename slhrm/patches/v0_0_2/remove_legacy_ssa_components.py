import frappe

LEGACY_SSA_CUSTOM_FIELDS = (
    "Salary Structure Assignment-slhrm_salary_components_section",
    "Salary Structure Assignment-slhrm_components",
    "Salary Structure Assignment-slhrm_components_html",
)

LEGACY_DOCTYPES = ("Salary Structure Assignment Component",)


def execute():
    """Remove the legacy SSA salary-components design (replaced by Employee Salary Package)."""
    for name in LEGACY_SSA_CUSTOM_FIELDS:
        if frappe.db.exists("Custom Field", name):
            frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)

    for doctype in LEGACY_DOCTYPES:
        table_exists = frappe.db.table_exists(doctype)
        if table_exists and frappe.db.count(doctype):
            frappe.log_error(
                title=f"SLHRM patch: kept legacy DocType {doctype}",
                message=f"{doctype} still has rows; not deleted. Migrate the data, then delete it manually.",
            )
            continue

        frappe.delete_doc("DocType", doctype, force=1, ignore_missing=True)
        if table_exists:
            frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
