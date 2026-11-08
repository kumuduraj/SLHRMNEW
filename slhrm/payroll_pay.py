# slhrm/payroll_pay.py
"""Payroll Worksheet pay = HRMS Salary Slip preview + OT. Never duplicate HRMS pay math here.

    structure_gross     = preview.gross_pay         (HRMS: structure formulas, proration by payment
                                                    days, Additional Salary, package overrides)
    structure_deduction = preview.total_deduction
    loan_deduction      = preview.total_loan_repayment (0 without the lending app)
    total_earning       = structure_gross + normal OT + double OT
    total_deduction     = structure_deduction + loan_deduction
    net_pay             = total_earning - total_deduction

additional_earning_total / additional_deduction_total = preview rows linked to an Additional
Salary — display only (already inside the preview, never added again).
Tax/statutory components on the final Salary Slip are computed on gross INCLUDING OT, so for
those the worksheet is an approximation (OT reaches the slip as Additional Salary).
"""
import frappe
from frappe.utils import cint, flt

from slhrm.overtime import calculate_ot_amounts, calculate_ot_rates
from slhrm.payroll_ot import get_marker_ot_hours
from slhrm.payroll_preview import build_previews

PRECISION = 2
OT_INPUT_FIELDS = ("normal_ot_hours", "normal_ot_rate", "double_ot_hours", "double_ot_rate")


def compose_pay(structure_gross=0, structure_deduction=0, normal_ot_amount=0, double_ot_amount=0,
                loan_deduction=0):
    earning = flt(structure_gross) + flt(normal_ot_amount) + flt(double_ot_amount)
    deduction = flt(structure_deduction) + flt(loan_deduction)
    return {
        "total_earning": flt(earning, PRECISION),
        "total_deduction": flt(deduction, PRECISION),
        "net_pay": flt(earning - deduction, PRECISION),
    }


def salary_fields_from_preview(preview):
    """Row fields that come from the HRMS preview (never computed by SLHRM)."""
    addl_earn = sum(r["amount"] for r in preview.earnings if r["additional_salary"])
    addl_ded = sum(r["amount"] for r in preview.deductions if r["additional_salary"])
    return {
        "salary_structure": preview.salary_structure,
        "structure_gross": flt(preview.gross_pay, PRECISION),
        "structure_deduction": flt(preview.total_deduction, PRECISION),
        "loan_deduction": flt(preview.total_loan_repayment, PRECISION),
        "additional_earning_total": flt(addl_earn, PRECISION),
        "additional_deduction_total": flt(addl_ded, PRECISION),
        "total_working_days": flt(preview.total_working_days),
        "payment_days": flt(preview.payment_days),
        "lwp_days": flt(preview.leave_without_pay),
        "present_days": flt(preview.payment_days),
        "absent_days": flt(preview.absent_days),
        "leave_days": flt(preview.leave_without_pay),
        "row_error": preview.error or "",
    }


def build_rows(employees, company, start_date, end_date, ot_inputs=None, progress=None):
    """Worksheet rows for `employees` (list of dicts: name, employee_name, designation,
    slhrm_ot_eligible). `ot_inputs` {employee: {normal_ot_hours, ...}} keeps existing OT edits
    (refresh); otherwise OT hours come from submitted markers and rates from overtime.py.

    Returns (rows, lines) where lines = {"earnings": [...], "deductions": [...]} for the
    worksheet's component tables (display).
    """
    names = [e["name"] for e in employees]
    previews = build_previews(names, company, start_date, end_date, progress=progress)
    marker_hours = get_marker_ot_hours(names, start_date, end_date) if ot_inputs is None else {}
    settings = frappe.get_cached_doc("SLHRM Settings")

    rows, earnings, deductions = [], [], []
    for e in employees:
        p = previews[e["name"]]
        salary = salary_fields_from_preview(p)
        eligible = cint(e.get("slhrm_ot_eligible"))
        base = flt(p.base)  # SSA base (display + OT rate input); pay itself comes from the preview

        if not eligible:
            ot = dict.fromkeys(OT_INPUT_FIELDS, 0.0)
        elif ot_inputs is not None:
            ot = {f: flt((ot_inputs.get(e["name"]) or {}).get(f)) for f in OT_INPUT_FIELDS}
        else:
            hours = marker_hours.get(e["name"], {})
            rates = calculate_ot_rates(e["name"], base, settings)
            ot = {"normal_ot_hours": flt(hours.get("normal")), "double_ot_hours": flt(hours.get("double")),
                  "normal_ot_rate": rates["normal_rate"], "double_ot_rate": rates["double_rate"]}
        amounts = calculate_ot_amounts(ot["normal_ot_hours"], ot["double_ot_hours"],
                                       {"normal_rate": ot["normal_ot_rate"], "double_rate": ot["double_ot_rate"]})

        row = {
            "employee": e["name"], "employee_name": e.get("employee_name"), "designation": e.get("designation") or "",
            "base": flt(base, PRECISION), "ot_eligible": eligible, **ot,
            "normal_ot_amount": amounts["normal"], "double_ot_amount": amounts["double"],
            "ot_amount": flt(amounts["normal"] + amounts["double"], PRECISION),
            **salary,
        }
        row.update(compose_pay(row["structure_gross"], row["structure_deduction"], row["normal_ot_amount"],
                               row["double_ot_amount"], row["loan_deduction"]))
        rows.append(row)

        for r in p.earnings:
            earnings.append({"employee": e["name"], "employee_name": e.get("employee_name"),
                             "salary_component": r["component"], "amount": r["amount"],
                             "additional_salary": r["additional_salary"],
                             "source_type": "Additional Salary" if r["additional_salary"] else "Salary Structure"})
        for r in p.deductions:
            deductions.append({"employee": e["name"], "employee_name": e.get("employee_name"),
                               "salary_component": r["component"], "amount": r["amount"],
                               "source_type": "Additional Salary" if r["additional_salary"] else "Salary Structure",
                               "reference_name": r["additional_salary"]})
    return rows, {"earnings": earnings, "deductions": deductions}


def summarize(rows):
    def total(field):
        return flt(sum(flt(r.get(field)) for r in rows), PRECISION)

    return {
        "total_employees": len(rows),
        "employees_with_ssa": sum(1 for r in rows if r.get("salary_structure")),
        "rows_with_error": sum(1 for r in rows if r.get("row_error")),
        "total_ot_amount": total("ot_amount"),
        "total_normal_ot_amount": total("normal_ot_amount"),
        "total_double_ot_amount": total("double_ot_amount"),
        "total_gross_pay": total("total_earning"),
        "total_deductions": total("total_deduction"),
        "total_net_pay": total("net_pay"),
    }
