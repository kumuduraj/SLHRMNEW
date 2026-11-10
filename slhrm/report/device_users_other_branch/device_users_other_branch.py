# Device Users Other Branch: punches matched by Attendance Device ID (company-wide) to an employee whose branch the
# device does not serve (match_reason "other_branch"). Check: transfer, visiting staff, or a re-used number.
import frappe
from frappe import _

from slhrm.biometric import other_branch_rows


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return columns(), other_branch_rows(filters.get("device"))


def columns():
    return [
        {"fieldname": "device_name", "label": _("Device"), "fieldtype": "Data", "width": 110},
        {"fieldname": "served_branches", "label": _("Served Branches"), "fieldtype": "Data", "width": 170},
        {"fieldname": "device_user_id", "label": _("Device User ID"), "fieldtype": "Data", "width": 110},
        {"fieldname": "user_name", "label": _("Name on Device"), "fieldtype": "Data", "width": 140},
        {"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 130},
        {"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "employee_branch", "label": _("Employee Branch"), "fieldtype": "Link", "options": "Branch", "width": 130},
        {"fieldname": "punches", "label": _("Punches"), "fieldtype": "Int", "width": 80},
        {"fieldname": "first_punch", "label": _("First Punch"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "last_punch", "label": _("Last Punch"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "device_serial", "label": _("Device Serial"), "fieldtype": "Data", "width": 130},
    ]
