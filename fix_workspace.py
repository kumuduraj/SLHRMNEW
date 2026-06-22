"""
fix_workspace.py - Fix workspace content and Desktop Icon issues caused by bytecode cache.
Run via: bench --site <site> execute slhrm.fix_workspace.fix_all

This script can be run after bench migrate to correct any data that was
overwritten by stale bytecode cache running old install.py code.
"""
import frappe
import json


def fix_all():
    """Fix all known workspace issues."""
    _fix_desktop_icon()
    _fix_workspace_content()
    _fix_workspace_shortcuts()
    frappe.db.commit()
    print("All workspace fixes applied.")


def _fix_desktop_icon():
    """Fix Desktop Icon: link_type should be 'Page', link_to should be 'slhrm-dashboard'."""
    if frappe.db.exists("Desktop Icon", "SLHRM"):
        frappe.db.sql("""
            UPDATE `tabDesktop Icon`
            SET link_type='Page', link_to='slhrm-dashboard',
                icon_type='App', icon='hexagon',
                logo_url='/assets/slhrm/icons/desktop_icons/solid/slhrm.svg',
                app='slhrm', standard=1
            WHERE name='SLHRM'
        """)
        print("Fixed Desktop Icon: link_type='Page', link_to='slhrm-dashboard'")
    else:
        print("Desktop Icon 'SLHRM' not found, skipping")


def _fix_workspace_content():
    """Fix workspace content: remove shortcut blocks, keep only headers and cards."""
    content = [
        {"id": "h_tna", "type": "header", "data": {"text": "Time & Attendance", "col": 12}},
        {"id": "card_tna", "type": "card", "data": {"card_name": "Time & Attendance", "col": 4}},
        {"id": "h_emp", "type": "header", "data": {"text": "Employee", "col": 12}},
        {"id": "card_emp", "type": "card", "data": {"card_name": "Employee", "col": 4}},
        {"id": "h_rec", "type": "header", "data": {"text": "Recruitment", "col": 12}},
        {"id": "card_rec", "type": "card", "data": {"card_name": "Recruitment", "col": 4}},
        {"id": "h_leave", "type": "header", "data": {"text": "Leaves", "col": 12}},
        {"id": "card_leave", "type": "card", "data": {"card_name": "Leaves", "col": 4}},
        {"id": "h_pay", "type": "header", "data": {"text": "Payroll", "col": 12}},
        {"id": "card_pay", "type": "card", "data": {"card_name": "Payroll", "col": 4}},
        {"id": "h_exp", "type": "header", "data": {"text": "Expense & Travel", "col": 12}},
        {"id": "card_exp", "type": "card", "data": {"card_name": "Expense & Travel", "col": 4}},
        {"id": "h_perf", "type": "header", "data": {"text": "Performance", "col": 12}},
        {"id": "card_perf", "type": "card", "data": {"card_name": "Performance", "col": 4}},
        {"id": "h_train", "type": "header", "data": {"text": "Training", "col": 12}},
        {"id": "card_train", "type": "card", "data": {"card_name": "Training", "col": 4}},
        {"id": "h_set", "type": "header", "data": {"text": "Settings", "col": 12}},
        {"id": "card_set", "type": "card", "data": {"card_name": "Settings", "col": 4}},
    ]

    frappe.db.sql(
        "UPDATE `tabWorkspace` SET content=%s WHERE name='SLHRM'",
        (json.dumps(content),),
    )
    print(f"Fixed workspace content: {len(content)} entries (no shortcuts)")


def _fix_workspace_shortcuts():
    """Delete all shortcuts from the child table — they cause 'DocType Shortcut not found' errors."""
    frappe.db.sql("DELETE FROM `tabWorkspace Shortcut` WHERE parent='SLHRM'")
    print("Deleted workspace shortcuts from child table")
