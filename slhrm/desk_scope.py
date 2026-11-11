# slhrm/desk_scope.py
"""Desk scope (2026-11-11): non-admin users see ONLY the SLHRM app on the Desk; Administrator and System Manager
see everything as before.

Same mechanism as agrosys.evonet.lk (evonav local changes there), implemented in SLHRM so no core or other-app
record is modified and nothing is undone by migrate:
- extend_bootinfo: Frappe v16 builds bootinfo.desktop_icons / module_wise_workspaces / workspace_sidebar_item for the
  user; for a non-admin we keep only SLHRM's (desktop icons of app "slhrm" + their child icons, the "SLHRM" module
  workspaces, the SLHRM workspace sidebars). Pages are not blocked — access stays with roles / DocPerms; other apps
  are simply not offered in the Desk UI.
- Desktop Icon permission hooks: core gives every Desk User read/write on Desktop Icon, so the desk's "Removed
  icons" tray / list API could list and re-add other apps' icons; non-admins only see SLHRM icons.
Role checks are per user; bootinfo is cached per user (clear-cache after changing this file).
"""
import frappe

APP = "slhrm"
MODULE = "SLHRM"


def is_privileged(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _slhrm_sidebars():
    return {r.name.lower(): r.name for r in frappe.get_all(
        "Workspace Sidebar", filters={"app": APP}, fields=["name"])} | {MODULE.lower(): MODULE}


def extend_bootinfo(bootinfo):
    if frappe.session.user == "Guest" or is_privileged():
        return
    icons = bootinfo.get("desktop_icons") or []
    keep = [i for i in icons if (i.get("app") == APP) and not i.get("parent_icon")]
    labels = {i.get("label") for i in keep}
    keep += [i for i in icons if i.get("parent_icon") and i.get("parent_icon") in labels]
    bootinfo["desktop_icons"] = sorted(keep, key=lambda i: i.get("idx") or 0)

    mww = bootinfo.get("module_wise_workspaces")
    if isinstance(mww, dict):
        bootinfo["module_wise_workspaces"] = {k: v for k, v in mww.items() if k == MODULE}

    sidebars = bootinfo.get("workspace_sidebar_item")
    if isinstance(sidebars, dict):
        allowed = _slhrm_sidebars()
        bootinfo["workspace_sidebar_item"] = {k: v for k, v in sidebars.items() if k in allowed}


def desktop_icon_query_conditions(user=None):
    """permission_query_conditions for Desktop Icon: non-admins list only SLHRM icons."""
    if is_privileged(user):
        return ""
    return f"`tabDesktop Icon`.`app` = {frappe.db.escape(APP)}"


def desktop_icon_has_permission(doc, user=None, permission_type=None):
    if is_privileged(user):
        return True
    return doc.get("app") == APP
