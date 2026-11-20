# slhrm/install.py
"""Install / migrate hooks.

Desk records are shipped as standard app files and synced by `bench migrate`:
- Workspace:          slhrm/workspace/slhrm/slhrm.json        (module folder, via slhrm/slhrm/workspace)
- Workspace Sidebar:  slhrm/workspace_sidebar/slhrm.json      (app-level folder)
- Desktop Icon:       slhrm/desktop_icon/slhrm.json           (app-level folder)
- Page:               slhrm/page/slhrm_dashboard/*.json       (module folder, via slhrm/slhrm/page)

Never touch core records (workspaces, sidebars or pages of other apps) from here, and never
use raw SQL. Only idempotent, API-based steps on SLHRM-owned records belong in these hooks.
"""
import frappe


ROLES = ("Attendance Supervisor", "HR Assistant")  # v0.2.0 supervisor; v0.4.7 HR Assistant (Dashboard, Time & Attendance, Employee)


def execute():
    """after_install"""
    _ensure_module_def()
    ensure_roles()
    ensure_custom_perm_base()


def after_migrate():
    _ensure_module_def()
    ensure_roles()


SUPERVISOR_READ_DOCTYPES = ("Branch", "Employee", "Shift Type", "Holiday List",  # v0.2.1 Attendance Supervisor reads
                            # v0.4.7 HR Assistant (Custom DocPerm fixture rows): full access + link-target reads
                            "Employee Checkin", "Attendance", "Shift Assignment", "Department", "Designation", "Employee Onboarding",
                            "Employee Separation", "Company", "Employment Type", "Employee Grade", "Employee Onboarding Template",
                            "Employee Separation Template", "Shift Location", "Job Applicant", "Job Offer", "Leave Type",
                            "HR Settings")  # new Employee form reads HR Settings.emp_created_by


def ensure_custom_perm_base():
    """Frappe uses ONLY Custom DocPerm rows for a doctype once any exists. Before the SLHRM fixture adds the
    Attendance Supervisor read rows, make sure the standard rows were copied (what Role Permission Manager does;
    no-op when the doctype already has Custom DocPerm rows, as on production)."""
    from frappe.permissions import setup_custom_perms

    for dt in SUPERVISOR_READ_DOCTYPES:
        if frappe.db.exists("DocType", dt):
            setup_custom_perms(dt)


def ensure_roles():
    """SLHRM's own roles (standard Role records via the API, idempotent)."""
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def _ensure_module_def():
    if frappe.db.exists("Module Def", "SLHRM"):
        return
    frappe.get_doc(
        {"doctype": "Module Def", "module_name": "SLHRM", "app_name": "slhrm"}
    ).insert(ignore_permissions=True)
