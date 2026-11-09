# Unmatched Device Users: device user ids whose punches have no Employee yet, newest activity first.
import frappe
from frappe import _
from frappe.utils import add_months, get_first_day, today

from slhrm.biometric import DEVICE, DEVICE_USER, PUNCH, mapping_candidates, suggest_employee


def execute(filters=None):
    filters = frappe._dict(filters or {})
    since = get_first_day(add_months(today(), -1))
    cond, values = "", {"since": since}
    if filters.get("device"):
        cond = "and p.device_serial = %(device)s"
        values["device"] = filters.device
    rows = frappe.db.sql(f"""
        select p.device_serial, p.device_user_id, count(*) as punches,
               min(p.punch_time) as first_punch, max(p.punch_time) as last_punch,
               sum(case when p.punch_time >= %(since)s then 1 else 0 end) as recent
        from `tab{PUNCH}` p
        where p.processing_status = 'Unmatched' and ifnull(p.device_user_id, '') != '' {cond}
        group by p.device_serial, p.device_user_id
        order by last_punch desc, punches desc""", values, as_dict=True)

    devices = {d.name: d for d in frappe.get_all(DEVICE, fields=["name", "device_name", "branch"])}
    names = {(u.device, u.device_user_id): u for u in frappe.get_all(
        DEVICE_USER, fields=["device", "device_user_id", "user_name", "on_device"])}
    employees = mapping_candidates()
    for r in rows:
        d = devices.get(r.device_serial) or frappe._dict()
        u = names.get((r.device_serial, r.device_user_id)) or frappe._dict()
        r.device_name = d.device_name or r.device_serial
        r.branch = d.branch
        r.user_name = u.user_name
        r.on_device = 1 if u.get("on_device") else 0
        emp, conf = suggest_employee(u.user_name, d.branch, employees) if u.user_name else (None, "none")
        r.suggested_employee = emp.name if emp else None
        r.suggested_name = emp.employee_name if emp else None
        r.confidence = conf
        r.action = ""
    return columns(since), rows


def columns(since):
    return [
        {"fieldname": "device_name", "label": _("Device"), "fieldtype": "Data", "width": 110},
        {"fieldname": "branch", "label": _("Branch"), "fieldtype": "Link", "options": "Branch", "width": 110},
        {"fieldname": "device_user_id", "label": _("Device User ID"), "fieldtype": "Data", "width": 110},
        {"fieldname": "user_name", "label": _("Name on Device"), "fieldtype": "Data", "width": 140},
        {"fieldname": "punches", "label": _("Punches"), "fieldtype": "Int", "width": 80},
        {"fieldname": "first_punch", "label": _("First Punch"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "last_punch", "label": _("Last Punch"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "recent", "label": _("Since {0}").format(frappe.format(since, "Date")), "fieldtype": "Int", "width": 100},
        {"fieldname": "suggested_employee", "label": _("Suggested Employee"), "fieldtype": "Link", "options": "Employee", "width": 130},
        {"fieldname": "suggested_name", "label": _("Suggested Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "confidence", "label": _("Confidence"), "fieldtype": "Data", "width": 150},
        {"fieldname": "action", "label": _("Action"), "fieldtype": "Data", "width": 140},
        {"fieldname": "device_serial", "label": _("Device Serial"), "fieldtype": "Data", "width": 130},
        {"fieldname": "on_device", "label": _("Still on Device"), "fieldtype": "Check", "width": 90},
    ]
