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


def execute():
    """after_install"""
    _ensure_module_def()


def after_migrate():
    _ensure_module_def()


def _ensure_module_def():
    if frappe.db.exists("Module Def", "SLHRM"):
        return
    frappe.get_doc(
        {"doctype": "Module Def", "module_name": "SLHRM", "app_name": "slhrm"}
    ).insert(ignore_permissions=True)
