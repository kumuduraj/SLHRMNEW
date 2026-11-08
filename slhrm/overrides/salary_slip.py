import frappe
from frappe.utils import flt

from slhrm.statutory import apply_epf


def apply_salary_package(doc, method):
    """doc_events Salary Slip before_save AND before_submit.

    Frappe runs validate + before_save on save, but validate + before_submit on submit (never
    before_save), and HRMS validate() re-runs calculate_net_pay(), which resets every row to its
    structure value. So the same rules must run on both events or a submitted slip would lose them.
    """
    apply_salary_rules(doc)


def apply_salary_rules(slip):
    """THE single entry point for SLHRM slip rules, in this order:
    1. Employee Salary Package overrides  2. EPF/ETF on the final earnings (slhrm.statutory).
    Used by the real Salary Slip hook and the Payroll Worksheet preview (slhrm.payroll_preview).
    Returns apply_epf()'s result ({epf_base, employer, applied}).
    """
    apply_package_overrides(slip)
    return apply_epf(slip)


def apply_package_overrides(slip):
    """Apply Employee Salary Package override amounts to a Salary Slip (saved or in-memory).

    Call apply_salary_rules(), not this directly: it does not re-total the slip (apply_epf does,
    with HRMS's own get_component_totals / set_net_pay).
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
    return True
