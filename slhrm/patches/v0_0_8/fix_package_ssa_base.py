import frappe
from frappe.utils import flt


def execute():
    """v0.0.8: Employee Salary Package SSA base = the base component's amount only.

    Before, the base was the sum of all overridden earnings, which inflated formulas on `base`
    (e.g. EPF 8%). For each package whose managed SSA has a different base, re-run
    manage_ssa() (cancel + new SSA with the right base). Guarded and idempotent: packages that
    are already correct are untouched; a package whose base component can't be resolved is
    logged and skipped.
    """
    for name in frappe.get_all("Employee Salary Package", pluck="name"):
        esp = frappe.get_doc("Employee Salary Package", name)
        try:
            esp.set_base_component()
            expected = esp.get_base_amount()
        except frappe.ValidationError as e:
            frappe.log_error(title=f"SLHRM patch: package {name} base not resolved",
                             message=frappe.utils.strip_html(str(e)))
            continue

        for row in esp.components:
            frappe.db.set_value("Employee Salary Package Detail", row.name, "is_base_component",
                                row.is_base_component, update_modified=False)

        ssa = esp._get_managed_ssa()
        if not ssa or flt(ssa.base) == flt(expected):
            continue
        print(f"SLHRM: package {name}: SSA {ssa.name} base {ssa.base} -> {expected}")
        esp.manage_ssa()
