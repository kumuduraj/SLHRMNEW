# slhrm/payroll_ot.py
"""Data access for Payroll Worksheet overtime / short hours / No Pay days. The math lives in slhrm.overtime."""
import frappe
from frappe.utils import cint, flt

from slhrm.overtime import STATUS_NO_PAY


def get_ot_eligibility(employees):
    """{employee: 0/1} from Employee.slhrm_ot_eligible (never from the client)."""
    if not employees:
        return {}
    return {
        r.name: cint(r.slhrm_ot_eligible)
        for r in frappe.get_all(
            "Employee", filters={"name": ["in", list(employees)]}, fields=["name", "slhrm_ot_eligible"]
        )
    }


def get_marker_totals(employees, start_date, end_date):
    """{employee: {ot_hours, short_hours, no_pay_days}} summed from SUBMITTED Attendance Markers of the period:
    approved daily OT (ot_hours), short hours, and the count of rows with status No Pay."""
    if not employees:
        return {}
    rows = frappe.db.sql(
        """
        SELECT amd.employee,
               SUM(IFNULL(amd.ot_hours, 0)) AS ot_hours,
               SUM(IFNULL(amd.short_hours, 0)) AS short_hours,
               SUM(CASE WHEN amd.attendance_status = %(no_pay)s THEN 1 ELSE 0 END) AS no_pay_days
        FROM `tabAttendance Marker Detail` amd
        INNER JOIN `tabAttendance Marker` am ON am.name = amd.parent
        WHERE amd.employee IN %(employees)s
            AND am.date BETWEEN %(start)s AND %(end)s
            AND am.docstatus = 1
        GROUP BY amd.employee
        """,
        {"employees": list(employees), "start": start_date, "end": end_date, "no_pay": STATUS_NO_PAY},
        as_dict=True,
    )
    return {r.employee: frappe._dict(ot_hours=flt(r.ot_hours, 2), short_hours=flt(r.short_hours, 2),
                                     no_pay_days=flt(r.no_pay_days)) for r in rows}


def get_marker_ot_hours(employees, start_date, end_date):
    """{employee: approved OT hours} (kept for callers that need OT only)."""
    return {k: v.ot_hours for k, v in get_marker_totals(employees, start_date, end_date).items()}
