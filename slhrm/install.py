# slhrm/install.py
import frappe
import json
import os
import sys


def execute():
    """Post-install setup: workspace sidebar and workspace page."""
    _ensure_modules_txt()
    _setup_module_path()
    _create_module_def()
    _create_page()
    _create_desktop_icon()
    _create_workspace()
    _set_workspace_links()
    _create_workspace_sidebar()
    _fix_sidebar_child_items()
    _fix_sidebar_show_arrow()
    _remove_home_items()
    frappe.db.commit()
    print("SLHRM install complete.")


def after_migrate():
    """Runs AFTER bench migrate — recreates sidebar, kills Home, fixes content."""
    _ensure_modules_txt()
    _setup_module_path()
    _create_module_def()
    _create_page()
    _create_desktop_icon()
    _fix_sidebar_show_arrow()
    _remove_home_items()
    _rebuild_workspace_sidebar()
    _set_workspace_content()
    _set_workspace_links()
    _set_workspace_redirect()
    _sync_pwa_assets()
    frappe.db.commit()
    print("after_migrate: Sidebar rebuilt, Home removed, content + redirect set")


def _sync_pwa_assets():
    """Copy PWA build output to sites/slhrm_pwa/ so nginx can serve it.

    Architecture:
    - sites/ is a shared Docker volume between frontend and backend containers
    - sites/assets is a symlink to bench/assets/ (different volume, NOT shared properly)
    - So we write to sites/slhrm_pwa/ which IS on the shared volume
    - Frontend nginx serves /slhrm/assets/ from sites/slhrm_pwa/assets/
    """
    import shutil
    import pathlib

    this_file = pathlib.Path(__file__).resolve()
    bench_root = this_file.parent.parent.parent.parent
    src = bench_root / "apps" / "slhrm" / "public" / "frontend"

    if not src.exists() or not (src / "index.html").exists():
        print(f"PWA sync: source not found at {src}")
        return

    # --- Payroll ---
    _section("Payroll", "banknote")
    _link("Payroll Worksheet", "Payroll Worksheet", "file-text")
    _link("Employee Salary Package", "Employee Salary Package", "banknote")
    _link("Salary Slip", "Salary Slip", "file-text")
    _link("Payroll Entry", "Payroll Entry", "square-check")
    _link("Salary Structure", "Salary Structure", "settings")
    _link("Salary Structure Assignment", "Salary Structure Assignment", "settings")
    _link("Employee Salary Component", "Employee Salary Component", "file-text")
    _link("Additional Salary", "Additional Salary", "file-text")
    _link("Bulk Additional Salary", "Bulk Additional Salary", "file-text")
    # --- Expense & Travel --- â”€â”€
    _section("Expense & Travel", "receipt")
    _link("Expense Claim", "Expense Claim", "file-text")
    _link("Travel Request", "Travel Request", "file-text")

    # â”€â”€ Performance â”€â”€
    _section("Performance", "chart-bar")
    _link("Appraisal", "Appraisal", "file-text")
    _link("Goal", "Goal", "file-text")

    # â”€â”€ Training â”€â”€
    _section("Training", "graduation-cap")
    _link("Training Program", "Training Program", "file-text")
    _link("Training Event", "Training Event", "file-text")

    # â”€â”€ Settings â”€â”€
    _section("Settings", "settings")
    _link("SLHRM Settings", "SLHRM Settings", "settings")
    _link("HR Settings", "HR Settings", "settings")
    _link("Company", "Company", "layout-grid")

    return items


# â”€â”€â”€ Workspace Page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _create_workspace():
    """Create the SLHRM workspace page with dashboard as first view."""
    if frappe.db.exists("Workspace", "SLHRM"):
        frappe.delete_doc("Workspace", "SLHRM", force=True)

    content = _get_workspace_content()

    ws = frappe.new_doc("Workspace")
    ws.name = ws.label = ws.title = "SLHRM"
    ws.module = "SLHRM"
    ws.app = "slhrm"
    ws.icon = "hexagon"
    ws.type = "Workspace"
    ws.public = 1
    ws.is_hidden = 0
    ws.content = json.dumps(content)

    # Card Break + Link format for workspace page body cards
    for entry in _get_workspace_links():
        ws.append("links", entry)

    ws.insert(ignore_permissions=True, ignore_links=True)

    # Content field is hidden=1; Frappe overwrites it to "[]" during insert.
    frappe.db.sql(
        "UPDATE `tabWorkspace` SET content = %s WHERE name = %s",
        (json.dumps(content), ws.name),
    )
    print("Created Workspace: SLHRM")


def _set_workspace_content():
    """Re-set workspace content via SQL — bench migrate overwrites it."""
    content = _get_workspace_content()
    frappe.db.sql(
        "UPDATE `tabWorkspace` SET content = %s WHERE name = 'SLHRM'",
        (json.dumps(content),),
    )
    print("Set workspace content via SQL")


def _set_workspace_links():
    """Insert workspace links via SQL — ws.insert() doesn't persist child table rows."""
    frappe.db.sql("DELETE FROM `tabWorkspace Link` WHERE parent = 'SLHRM'")
    idx = 0
    for entry in _get_workspace_links():
        idx += 1
        link_type = entry.get("type")
        if link_type == "Card Break":
            frappe.db.sql("""
                INSERT INTO `tabWorkspace Link`
                (name, parent, parenttype, parentfield, type, label, icon, idx, docstatus)
                VALUES (UUID(), 'SLHRM', 'Workspace', 'links', 'Card Break', %s, %s, %s, 0)
            """, (entry["label"], entry.get("icon", ""), idx))
        elif link_type == "Link":
            frappe.db.sql("""
                INSERT INTO `tabWorkspace Link`
                (name, parent, parenttype, parentfield, type, label, link_to, link_type, onboard, idx, docstatus)
                VALUES (UUID(), 'SLHRM', 'Workspace', 'links', 'Link', %s, %s, %s, %s, %s, 0)
            """, (entry["label"], entry["link_to"], entry.get("link_type", "DocType"), entry.get("onboard", 0), idx))
    print("Set workspace links via SQL")


def _get_workspace_content():
    """Return workspace content blocks: shortcuts + headers + card blocks."""
    return [
        # â”€â”€ Shortcuts â”€â”€
        {"id": "sc_dashboard", "type": "shortcut", "label": "Attendance Dashboard", "link_to": "slhrm-dashboard", "doc_view": "Page", "icon": "chart-bar", "color": "#3b82f6"},
        {"id": "sc_marker", "type": "shortcut", "label": "New Attendance Marker", "link_to": "Attendance Marker", "doc_view": "Form", "icon": "square-check", "color": "#3b82f6"},
        {"id": "sc_punch", "type": "shortcut", "label": "Biometric Punch Log", "link_to": "Biometric Punch Log", "doc_view": "List", "icon": "file-text", "color": "#22c55e"},
        {"id": "sc_emp", "type": "shortcut", "label": "Employees", "link_to": "Employee", "doc_view": "List", "icon": "user", "color": "#8b5cf6"},
        {"id": "sc_leave", "type": "shortcut", "label": "Leave Applications", "link_to": "Leave Application", "doc_view": "List", "icon": "book-open", "color": "#f59e0b"},
        {"id": "sc_salary", "type": "shortcut", "label": "Salary Slips", "link_to": "Salary Slip", "doc_view": "List", "icon": "file-text", "color": "#ef4444"},
        {"id": "sc_expense", "type": "shortcut", "label": "Expense Claims", "link_to": "Expense Claim", "doc_view": "List", "icon": "file-text", "color": "#ec4899"},
        {"id": "sc_settings", "type": "shortcut", "label": "Settings", "link_to": "SLHRM Settings", "doc_view": "Form", "icon": "settings", "color": "#6b7280"},

        # â”€â”€ Time & Attendance â”€â”€
        {"id": "h_tna", "type": "header", "data": {"text": "Time & Attendance", "col": 12}},
        {"id": "card_tna", "type": "card", "data": {"card_name": "Time & Attendance", "col": 4}},

        # â”€â”€ Employee â”€â”€
        {"id": "h_emp", "type": "header", "data": {"text": "Employee", "col": 12}},
        {"id": "card_emp", "type": "card", "data": {"card_name": "Employee", "col": 4}},

        # â”€â”€ Recruitment â”€â”€
        {"id": "h_rec", "type": "header", "data": {"text": "Recruitment", "col": 12}},
        {"id": "card_rec", "type": "card", "data": {"card_name": "Recruitment", "col": 4}},

        # â”€â”€ Leaves â”€â”€
        {"id": "h_leave", "type": "header", "data": {"text": "Leaves", "col": 12}},
        {"id": "card_leave", "type": "card", "data": {"card_name": "Leaves", "col": 4}},

        # â”€â”€ Payroll â”€â”€
        {"id": "h_pay", "type": "header", "data": {"text": "Payroll", "col": 12}},
        {"id": "card_pay", "type": "card", "data": {"card_name": "Payroll", "col": 4}},

        # â”€â”€ Expense & Travel â”€â”€
        {"id": "h_exp", "type": "header", "data": {"text": "Expense & Travel", "col": 12}},
        {"id": "card_exp", "type": "card", "data": {"card_name": "Expense & Travel", "col": 4}},

        # â”€â”€ Performance â”€â”€
        {"id": "h_perf", "type": "header", "data": {"text": "Performance", "col": 12}},
        {"id": "card_perf", "type": "card", "data": {"card_name": "Performance", "col": 4}},

        # â”€â”€ Training â”€â”€
        {"id": "h_train", "type": "header", "data": {"text": "Training", "col": 12}},
        {"id": "card_train", "type": "card", "data": {"card_name": "Training", "col": 4}},

        # â”€â”€ Settings â”€â”€
        {"id": "h_set", "type": "header", "data": {"text": "Settings", "col": 12}},
        {"id": "card_set", "type": "card", "data": {"card_name": "Settings", "col": 4}},
    ]


def _get_workspace_links():
    """Return Card Break + Link entries for workspace page body cards."""
    return [
        # Time & Attendance
        {"type": "Card Break", "label": "Time & Attendance", "icon": "clock"},
        {"type": "Link", "label": "Biometric Punch Log", "link_to": "Biometric Punch Log", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Attendance Marker", "link_to": "Attendance Marker", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Employee Checkin", "link_to": "Employee Checkin", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Attendance", "link_to": "Attendance", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Shift Type", "link_to": "Shift Type", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Shift Assignment", "link_to": "Shift Assignment", "link_type": "DocType", "onboard": 0},

        # Employee
        {"type": "Card Break", "label": "Employee", "icon": "user"},
        {"type": "Link", "label": "Employee", "link_to": "Employee", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Department", "link_to": "Department", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Designation", "link_to": "Designation", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Employee Onboarding", "link_to": "Employee Onboarding", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Employee Separation", "link_to": "Employee Separation", "link_type": "DocType", "onboard": 0},

        # Recruitment
        {"type": "Card Break", "label": "Recruitment", "icon": "briefcase"},
        {"type": "Link", "label": "Job Opening", "link_to": "Job Opening", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Job Applicant", "link_to": "Job Applicant", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Job Offer", "link_to": "Job Offer", "link_type": "DocType", "onboard": 0},

        # Leaves
        {"type": "Card Break", "label": "Leaves", "icon": "book-open"},
        {"type": "Link", "label": "Leave Application", "link_to": "Leave Application", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Leave Type", "link_to": "Leave Type", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Leave Allocation", "link_to": "Leave Allocation", "link_type": "DocType", "onboard": 0},

        # Payroll
        {"type": "Card Break", "label": "Payroll", "icon": "banknote"},
        {"type": "Link", "label": "Payroll Worksheet", "link_to": "Payroll Worksheet", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Salary Slip", "link_to": "Salary Slip", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Payroll Entry", "link_to": "Payroll Entry", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Salary Structure", "link_to": "Salary Structure", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Salary Structure Assignment", "link_to": "Salary Structure Assignment", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Additional Salary", "link_to": "Additional Salary", "link_type": "DocType", "onboard": 0},

        # Expense & Travel
        {"type": "Card Break", "label": "Expense & Travel", "icon": "receipt"},
        {"type": "Link", "label": "Expense Claim", "link_to": "Expense Claim", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Travel Request", "link_to": "Travel Request", "link_type": "DocType", "onboard": 0},

        # Performance
        {"type": "Card Break", "label": "Performance", "icon": "chart-bar"},
        {"type": "Link", "label": "Appraisal", "link_to": "Appraisal", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Goal", "link_to": "Goal", "link_type": "DocType", "onboard": 0},

        # Training
        {"type": "Card Break", "label": "Training", "icon": "graduation-cap"},
        {"type": "Link", "label": "Training Program", "link_to": "Training Program", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Training Event", "link_to": "Training Event", "link_type": "DocType", "onboard": 0},

        # Settings
        {"type": "Card Break", "label": "Settings", "icon": "settings"},
        {"type": "Link", "label": "SLHRM Settings", "link_to": "SLHRM Settings", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "HR Settings", "link_to": "HR Settings", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Company", "link_to": "Company", "link_type": "DocType", "onboard": 0},
    ]
