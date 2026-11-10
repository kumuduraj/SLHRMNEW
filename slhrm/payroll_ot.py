# slhrm/payroll_ot.py
"""Data access for Payroll Worksheet overtime. The math itself lives in slhrm.overtime."""
import frappe
from frappe.utils import cint, flt


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


def get_marker_ot_hours(employees, start_date, end_date):
    """{employee: OT hours} summed from submitted Attendance Markers (ot_hours)."""
    if not employees:
        return {}
    rows = frappe.db.sql(
        """
        SELECT amd.employee,
               SUM(IFNULL(amd.ot_hours, 0)) AS ot_hours
        FROM `tabAttendance Marker Detail` amd
        INNER JOIN `tabAttendance Marker` am ON am.name = amd.parent
        WHERE amd.employee IN %(employees)s
            AND am.date BETWEEN %(start)s AND %(end)s
            AND am.docstatus = 1
        GROUP BY amd.employee
        """,
        {"employees": list(employees), "start": start_date, "end": end_date},
        as_dict=True,
    )
    return {r.employee: flt(r.ot_hours, 2) for r in rows}
