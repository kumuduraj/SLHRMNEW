import frappe
from frappe.utils import flt


def apply_salary_package(doc, method):
    """doc_events Salary Slip before_save: apply Employee Salary Package overrides."""
    apply_package_overrides(doc)


def apply_package_overrides(slip):
    """Apply Employee Salary Package override amounts to a Salary Slip (saved or in-memory).

    Shared by the real Salary Slip (before_save) and the Payroll Worksheet preview
    (slhrm.payroll_preview), so both produce identical numbers.
    Returns True if any override was applied.
    """
    if not slip.employee:
        return False

    package_name = frappe.db.exists("Employee Salary Package", slip.employee)
    if not package_name:
        return False

    package = frappe.get_doc("Employee Salary Package", package_name)
    if not package.components:
        return False

    override_map = {}
    for row in package.components:
        if row.override and flt(row.amount) >= 0:
            override_map[row.salary_component] = {
                "amount": flt(row.amount),
                "type": row.salary_component_type,
                "depends_on_payment_days": row.depends_on_payment_days,
            }

    if not override_map:
        return False

    total_working_days = flt(slip.total_working_days)
    payment_days = flt(slip.payment_days) or total_working_days

    for slip_row in list(slip.earnings) + list(slip.deductions):
        if slip_row.salary_component in override_map:
            pkg = override_map[slip_row.salary_component]
            amount = pkg["amount"]
            slip_row.default_amount = amount

            if pkg["depends_on_payment_days"] and total_working_days > 0:
                slip_row.amount = flt(amount * payment_days / total_working_days)
            else:
                slip_row.amount = amount

    slip.gross_pay = sum(flt(r.amount) for r in slip.earnings)
    slip.total_deduction = sum(flt(r.amount) for r in slip.deductions)
    slip.net_pay = flt(slip.gross_pay) - flt(slip.total_deduction)

    if hasattr(slip, "rounded_total"):
        slip.rounded_total = round(flt(slip.net_pay))
    return True
