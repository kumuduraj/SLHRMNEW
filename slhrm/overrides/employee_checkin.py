# slhrm/overrides/employee_checkin.py
"""Server-side gate for Employee Checkin (doc_events; no core changes).

HRMS lets role "Employee" create (and edit) Employee Checkin for any employee and never
checks the mobile-app flag on the server. SLHRM enforces, for users without an HR role:
- the check-in must be for the session user's own active Employee
- that Employee must have slhrm_allow_app_checkin = 1 and HR Settings must allow
  check-in from the mobile app
HR User / HR Manager / System Manager and Administrator are unrestricted. Imports and
patches are never blocked.
"""
import frappe
from frappe import _
from frappe.utils import cint

UNRESTRICTED_ROLES = {"HR User", "HR Manager", "System Manager"}


def get_session_employee():
    return frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user, "status": "Active"},
        ["name", "slhrm_allow_app_checkin", "slhrm_ot_eligible"],
        as_dict=True,
    )


def mobile_checkin_enabled():
    return bool(cint(frappe.db.get_single_value("HR Settings", "allow_employee_checkin_from_mobile_app")))


def app_checkin_allowed(employee_row):
    return bool(employee_row and cint(employee_row.slhrm_allow_app_checkin) and mobile_checkin_enabled())


def _is_unrestricted(doc):
    if frappe.flags.in_import or frappe.flags.in_patch or frappe.flags.in_install or frappe.flags.in_migrate:
        return True
    if frappe.session.user == "Administrator":
        return True
    return bool(UNRESTRICTED_ROLES.intersection(frappe.get_roles()))


def _enforce(doc):
    if _is_unrestricted(doc):
        return
    own = get_session_employee()
    if not own or doc.employee != own.name:
        frappe.throw(_("You can only check in for yourself."), frappe.PermissionError)
    if not app_checkin_allowed(own):
        frappe.throw(_("Check-in via app is not enabled for you. Contact HR."), frappe.PermissionError)


def validate(doc, method=None):
    """before_insert: new check-ins."""
    _enforce(doc)


def validate_update(doc, method=None):
    """validate: edits to existing check-ins (role Employee has write on any check-in)."""
    if doc.is_new():
        return
    _enforce(doc)
    previous = doc.get_doc_before_save()
    if previous and previous.employee != doc.employee:
        _enforce(previous)
