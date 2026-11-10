"""v0.2.1: the device user id lives in ERPNext Employee.attendance_device_id (unique company-wide).
Copy slhrm_biometric_device_id -> attendance_device_id where attendance_device_id is empty. Guarded: ABORTS (no
change) if any id would collide (same id on several employees, or an employee with two different ids). Idempotent.
slhrm_biometric_device_id is left in place (hidden, legacy)."""
import frappe
from frappe.utils import cstr


def plan():
    if not frappe.db.has_column("Employee", "slhrm_biometric_device_id"):
        return [], []
    rows = frappe.get_all("Employee", fields=["name", "employee_name", "branch", "slhrm_biometric_device_id", "attendance_device_id"])
    holders, copy, conflicts = {}, [], []
    for e in rows:
        a = cstr(e.attendance_device_id).strip()
        if a:
            holders.setdefault(a, []).append(e.name)
    for e in rows:
        s, a = cstr(e.slhrm_biometric_device_id).strip(), cstr(e.attendance_device_id).strip()
        if not s or s == a:
            continue
        if a:
            conflicts.append(f"{e.name} {e.employee_name}: SLHRM id {s} but Attendance Device ID {a}")
            continue
        holders.setdefault(s, []).append(e.name)
        copy.append((e.name, s))
    conflicts += [f"id {k} on {', '.join(v)}" for k, v in holders.items() if len(v) > 1]
    return copy, conflicts


def execute():
    copy, conflicts = plan()
    if conflicts:
        frappe.throw("copy_device_ids: conflicts, nothing copied:<br>" + "<br>".join(conflicts))
    for name, uid in copy:
        frappe.db.set_value("Employee", name, "attendance_device_id", uid, update_modified=False)
    print(f"copy_device_ids: copied {len(copy)}")
