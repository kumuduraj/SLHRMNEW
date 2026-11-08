# slhrm/payroll_preview.py
"""In-memory Salary Slip preview: the Payroll Worksheet's salary numbers come from HRMS's own
Salary Slip calculation. The preview is NEVER inserted, saved or committed.

Path (HRMS v16, read-only):
  frappe.new_doc("Salary Slip") with explicit employee / company / start_date / end_date /
  payroll_frequency "Monthly", then the slip's own steps:
    get_working_days_details()  holidays (Holiday List Assignment), LWP, payment days
    check_sal_struct()          the employee's Salary Structure (via submitted SSA)
    make_salary_slip(structure, slip) -> process_salary_structure -> calculate_net_pay
                                structure formulas, submitted Additional Salary, proration, tax
Not used: slip.validate() (check_existing() throws once a real slip exists) and
get_emp_and_working_day_details() (also runs loan interest accrual, which writes when the
lending app is installed).

Defence in depth: every preview runs inside a DB savepoint that is always rolled back, and
the message log is restored, so nothing a future HRMS version might write can persist.
"""
import frappe
from frappe.utils import flt, getdate

from slhrm.overrides.salary_slip import apply_package_overrides

WORKSHEET_DOCTYPE = "Payroll Worksheet"


def _rows(table):
    return [
        {
            "component": r.salary_component,
            "abbr": r.abbr,
            "amount": flt(r.amount, 2),
            "additional_salary": r.additional_salary or "",
            "depends_on_payment_days": r.depends_on_payment_days,
        }
        for r in table
        if not r.do_not_include_in_total
    ]


def _drop_worksheet_ot(slip):
    """Remove Additional Salary created by a Payroll Worksheet (its OT) — the worksheet adds OT
    itself. Re-totals the HRMS way (amount as counted in gross, then set_net_pay)."""
    links = [r.additional_salary for r in slip.earnings + slip.deductions if r.additional_salary]
    if not links:
        return
    worksheet_ads = set(
        frappe.get_all("Additional Salary", filters={"name": ["in", links], "ref_doctype": WORKSHEET_DOCTYPE},
                       pluck="name")
    )
    if not worksheet_ads:
        return
    for table in ("earnings", "deductions"):
        keep = []
        for r in slip.get(table):
            if r.additional_salary in worksheet_ads:
                if table == "earnings" and not r.do_not_include_in_total:
                    slip.gross_pay = flt(slip.gross_pay) - slip.get_amount_based_on_payment_days(r)[0]
                continue
            keep.append(r)
        slip.set(table, keep)
    slip.set_net_pay()


def build_preview(employee, company, start_date, end_date):
    """HRMS Salary Slip numbers for one employee and period, computed in memory only.

    Returns a dict: earnings / deductions [{component, abbr, amount, additional_salary,
    depends_on_payment_days}], gross_pay, total_deduction, net_pay, total_loan_repayment,
    total_working_days, payment_days, absent_days, leave_without_pay, salary_structure, base (SSA), error.
    """
    from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

    result = frappe._dict(
        employee=employee, earnings=[], deductions=[], gross_pay=0.0, total_deduction=0.0, net_pay=0.0,
        total_loan_repayment=0.0, total_working_days=0.0, payment_days=0.0, absent_days=0.0,
        leave_without_pay=0.0, salary_structure="", base=0.0, error=None,
    )
    savepoint = f"slhrm_preview_{frappe.generate_hash(length=8)}"
    messages_before = len(frappe.local.message_log or [])
    frappe.db.savepoint(savepoint)
    try:
        slip = frappe.new_doc("Salary Slip")
        slip.update({
            "employee": employee,
            "employee_name": frappe.get_cached_value("Employee", employee, "employee_name"),
            "company": company,
            "posting_date": getdate(end_date),
            "start_date": getdate(start_date),
            "end_date": getdate(end_date),
            "payroll_frequency": "Monthly",
        })
        slip.get_working_days_details()
        if not slip.check_sal_struct():
            result.error = (
                f"No active Monthly Salary Structure Assignment for {employee} on or before {start_date}."
            )
            return result

        make_salary_slip(slip.salary_structure, slip)  # process_salary_structure -> calculate_net_pay
        result.base = flt(frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": employee, "salary_structure": slip.salary_structure, "docstatus": 1,
             "from_date": ("<=", slip.actual_start_date)},
            "base", order_by="from_date desc",
        ))
        _drop_worksheet_ot(slip)
        apply_package_overrides(slip)

        result.update(
            earnings=_rows(slip.earnings),
            deductions=_rows(slip.deductions),
            gross_pay=flt(slip.gross_pay, 2),
            total_deduction=flt(slip.total_deduction, 2),
            net_pay=flt(slip.net_pay, 2),
            total_loan_repayment=flt(slip.get("total_loan_repayment"), 2),
            total_working_days=flt(slip.total_working_days),
            payment_days=flt(slip.payment_days),
            absent_days=flt(slip.get("absent_days")),
            leave_without_pay=flt(slip.leave_without_pay),
            salary_structure=slip.salary_structure or "",
        )
    except Exception as e:
        result.error = frappe.utils.strip_html(str(e)) or type(e).__name__
    finally:
        frappe.db.rollback(save_point=savepoint)
        if frappe.local.message_log is not None:
            del frappe.local.message_log[messages_before:]
    return result


def build_previews(employees, company, start_date, end_date, progress=None):
    """{employee: preview}; one employee's error never stops the others."""
    out = {}
    total = len(employees)
    for i, emp in enumerate(employees, 1):
        out[emp] = build_preview(emp, company, start_date, end_date)
        if progress:
            progress(i, total)
    return out
