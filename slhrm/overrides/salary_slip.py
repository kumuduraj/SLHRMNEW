import json

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

    Effective-dated: the amounts come from the snapshot (`slhrm_package_components`) stored on the
    Salary Structure Assignment the slip uses (HRMS: latest submitted SSA with from_date <= the slip's
    start date), so earlier periods keep their own amounts after a package change.
    Call apply_salary_rules(), not this directly: it does not re-total the slip (apply_epf does,
    with HRMS's own get_component_totals / set_net_pay).
    Returns True if any override was applied.
    """
    if not slip.employee:
        return False

    rows = _package_rows_for_slip(slip)
    if not rows:
        return False

    override_map = {}
    for row in rows:
        row = frappe._dict(row)
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


def _slip_ssa(slip):
    """The SSA HRMS uses for this slip (same rule as SalarySlip.set_salary_structure_assignment)."""
    ssa = getattr(slip, "_salary_structure_assignment", None)
    if ssa and ssa.get("name"):
        return frappe.db.get_value("Salary Structure Assignment", ssa.get("name"),
                                   ["name", "slhrm_managed", "slhrm_package_components"], as_dict=True)
    start = slip.get("actual_start_date") or slip.get("start_date")
    if not (slip.get("salary_structure") and start):
        return None
    return frappe.db.get_value(
        "Salary Structure Assignment",
        {"employee": slip.employee, "salary_structure": slip.salary_structure,
         "from_date": ("<=", start), "docstatus": 1},
        ["name", "slhrm_managed", "slhrm_package_components"], as_dict=True, order_by="from_date desc",
    )


def _package_rows_for_slip(slip):
    """Package rows in force for the slip's period: the SSA's snapshot. A non-package SSA -> none.
    Legacy package SSA without a snapshot -> the package's current rows (patch v0_0_10 backfills)."""
    ssa = _slip_ssa(slip)
    if not ssa or not ssa.slhrm_managed:
        return []
    if ssa.slhrm_package_components:
        try:
            return json.loads(ssa.slhrm_package_components)
        except ValueError:
            frappe.log_error(title=f"SLHRM: bad package snapshot on {ssa.name}")
            return []
    package = frappe.db.exists("Employee Salary Package", slip.employee)
    return [r.as_dict() for r in frappe.get_doc("Employee Salary Package", package).components] if package else []
