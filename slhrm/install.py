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
    _set_workspace_redirect()
    frappe.db.commit()
    print("after_migrate: Sidebar rebuilt, Home removed, content + redirect set")


# â”€â”€â”€ Module Path Fix â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _ensure_modules_txt():
    """Ensure modules.txt exists at the package level for Frappe module discovery."""
    app_path = frappe.get_app_path("slhrm")
    modules_txt = os.path.join(app_path, "modules.txt")
    if not os.path.exists(modules_txt):
        with open(modules_txt, "w") as f:
            f.write("SLHRM\n")
        print("Created modules.txt at package level")
    else:
        content = open(modules_txt).read().strip()
        if "SLHRM" not in content:
            with open(modules_txt, "a") as f:
                f.write("\nSLHRM\n")
            print("Added SLHRM to modules.txt")


def _setup_module_path():
    """Create the module path directory and symlinks so get_module_path('SLHRM') works.

    Since app_name='slhrm' and module='SLHRM' (scrubs to 'slhrm'),
    Frappe tries to import 'slhrm.slhrm' which needs apps/slhrm/slhrm/slhrm/__init__.py.
    We also symlink doctype, public, etc. so form loading finds the right files.
    """
    app_path = frappe.get_app_path("slhrm")
    module_dir = os.path.join(app_path, "slhrm")

    # Create slhrm/slhrm/slhrm/ directory
    os.makedirs(module_dir, exist_ok=True)

    # Create __init__.py
    init_file = os.path.join(module_dir, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w") as f:
            f.write("")

    # Create symlinks for directories that Frappe looks for
    symlinks = {
        "doctype": "../doctype",
        "public": "../public",
        "fixtures": "../fixtures",
        "workspace": "../workspace",
        "workspace_sidebar": "../workspace_sidebar",
        "page": "../../page",
    }
    for name, target in symlinks.items():
        link_path = os.path.join(module_dir, name)
        if not os.path.exists(link_path) and not os.path.islink(link_path):
            os.symlink(target, link_path)
            print(f"Created symlink: {name} -> {target}")


def _create_module_def():
    """Create Module Def for SLHRM if it doesn't exist."""
    if not frappe.db.exists("Module Def", "SLHRM"):
        try:
            frappe.get_doc({
                "doctype": "Module Def",
                "module_name": "SLHRM",
                "app_name": "slhrm",
            }).insert(ignore_permissions=True)
            print("Created Module Def: SLHRM")
        except Exception:
            print("Module Def: SLHRM already exists or creation skipped")
    else:
        print("Module Def: SLHRM already exists")


def _create_page():
    """Create the Dashboard Page in tabPage if it doesn't exist."""
    if not frappe.db.exists("Page", "slhrm-dashboard"):
        frappe.db.sql("""
            INSERT IGNORE INTO tabPage
            (name, page_name, title, icon, module, standard, docstatus, idx, system_page, modified, creation, modified_by, owner)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), %s, %s)
        """, ("slhrm-dashboard", "slhrm-dashboard", "Attendance Dashboard", "chart-bar", "SLHRM", "1", 0, 0, 0, "Administrator", "Administrator"))
        print("Created Page: slhrm-dashboard")
    else:
        print("Page: slhrm-dashboard already exists")


def _create_desktop_icon():
    """Create Desktop Icon for SLHRM app in the apps switcher sidebar."""
    if not frappe.db.exists("Desktop Icon", "SLHRM"):
        frappe.db.sql("""
            INSERT IGNORE INTO `tabDesktop Icon`
            (name, label, icon_type, icon, link_type, link_to, app, logo_url, standard, docstatus, idx, hidden, sidebar, modified, creation, modified_by, owner)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), %s, %s)
        """, ("SLHRM", "SLHRM", "App", "hexagon", "External", "SLHRM", "slhrm",
              "/assets/slhrm/icons/desktop_icons/solid/slhrm.svg",
              1, 0, 1, 0, 1, "Administrator", "Administrator"))
        print("Created Desktop Icon: SLHRM")
    else:
        frappe.db.sql("""
            UPDATE `tabDesktop Icon`
            SET icon_type='App', icon='hexagon',
                logo_url='/assets/slhrm/icons/desktop_icons/solid/slhrm.svg',
                app='slhrm', standard=1, link='/app/slhrm'
            WHERE name='SLHRM'
        """)
        print("Updated Desktop Icon: SLHRM")


# â”€â”€â”€ Workspace Sidebar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _create_workspace_sidebar():
    """Create the Workspace Sidebar that powers the left sidebar links."""
    if frappe.db.exists("Workspace Sidebar", "SLHRM"):
        frappe.delete_doc("Workspace Sidebar", "SLHRM", force=True)

    sidebar = frappe.get_doc({
        "doctype": "Workspace Sidebar",
        "title": "SLHRM",
        "header_icon": "hexagon",
        "app": "slhrm",
        "module": "SLHRM",
        "standard": 1,
        "items": _build_sidebar_items(),
    })
    sidebar.insert(ignore_permissions=True, ignore_links=True)

    frappe.db.sql("""
        UPDATE `tabWorkspace Sidebar Item`
        SET child = 1
        WHERE parent = %s AND type = 'Link'
    """, sidebar.name)

    print("Created Workspace Sidebar: SLHRM")


def _rebuild_workspace_sidebar():
    """Delete and recreate sidebar â€” bench migrate overwrites it with Frappe's auto-generated items."""
    frappe.db.sql("DELETE FROM `tabWorkspace Sidebar Item` WHERE parent = 'SLHRM'")
    frappe.db.sql("DELETE FROM `tabWorkspace Sidebar` WHERE name = 'SLHRM'")
    _create_workspace_sidebar()
    print("Rebuilt sidebar: deleted and recreated with correct sections")


def _set_workspace_redirect():
    """Make the Attendance Dashboard shortcut first item and set it as the workspace header link."""
    frappe.db.sql("""
        UPDATE `tabWorkspace` SET is_hidden = 0, module = 'SLHRM'
        WHERE name = 'SLHRM'
    """)
    print("Set workspace: SLHRM visible and module assigned")


def _fix_sidebar_child_items():
    """Set child=1 on Link items so find_nested_items() groups them under Section Breaks."""
    frappe.db.sql("""
        UPDATE `tabWorkspace Sidebar Item`
        SET child = 1
        WHERE parent = 'SLHRM' AND type = 'Link'
    """)
    print("Fixed sidebar child items: child=1 on all Link items")


def _fix_sidebar_show_arrow():
    """Set show_arrow=0 on Section Break items — show_arrow overwrites the collapsible drop icon."""
    frappe.db.sql("""
        UPDATE `tabWorkspace Sidebar Item`
        SET show_arrow = 0
        WHERE parent = 'SLHRM' AND type = 'Section Break'
    """)
    print("Fixed sidebar: show_arrow=0 on all Section Break items")


def _remove_home_items():
    """Remove Home link from sidebar and any stale auto-generated entries."""
    frappe.db.sql("""
        DELETE FROM `tabWorkspace Sidebar Item`
        WHERE parent = 'SLHRM' AND label = 'Home'
    """)
    if frappe.db.exists("Workspace", "Home"):
        frappe.delete_doc("Workspace", "Home", force=True)
    frappe.db.sql("""
        DELETE FROM `tabWorkspace Sidebar Item`
        WHERE parent IN (
            SELECT name FROM `tabWorkspace Sidebar`
            WHERE (app IS NULL OR app = '') AND module = 'SLHRM'
        )
    """)
    frappe.db.sql("""
        DELETE FROM `tabWorkspace Sidebar`
        WHERE (app IS NULL OR app = '') AND module = 'SLHRM'
    """)
    print("Removed Home items and stale auto-generated sidebar entries")


def _build_sidebar_items():
    """Build sidebar items with Section Break headers and indented Link rows."""
    items = []
    idx = 0

    def _section(label, icon, keep_closed=0):
        nonlocal idx
        idx += 1
        items.append({
            "type": "Section Break", "label": label, "icon": icon,
            "indent": 0, "collapsible": 1, "keep_closed": keep_closed, "child": 0, "idx": idx,
            "show_arrow": 0,
        })

    def _link(label, link_to, icon="", link_type="DocType"):
        nonlocal idx
        idx += 1
        items.append({
            "type": "Link", "label": label, "link_type": link_type,
            "link_to": link_to, "icon": icon, "child": 1, "indent": 0, "idx": idx,
        })

    # â”€â”€ Dashboard â”€â”€
    _section("Dashboard", "chart-bar")
    _link("Attendance Dashboard", "slhrm-dashboard", "chart-bar", link_type="Page")

    # â”€â”€ Time & Attendance â”€â”€
    _section("Time & Attendance", "clock")
    _link("Biometric Punch Log", "Biometric Punch Log", "file-text")
    _link("Attendance Marker", "Attendance Marker", "square-check")
    _link("Employee Checkin", "Employee Checkin", "file-text")
    _link("Attendance", "Attendance", "square-check")
    _link("Shift Type", "Shift Type", "clock")
    _link("Shift Assignment", "Shift Assignment", "square-check")

    # â”€â”€ Employee â”€â”€
    _section("Employee", "user")
    _link("Employee", "Employee", "user")
    _link("Department", "Department", "layout-grid")
    _link("Designation", "Designation", "layout-grid")
    _link("Employee Onboarding", "Employee Onboarding", "user")
    _link("Employee Separation", "Employee Separation", "user")

    # â”€â”€ Recruitment â”€â”€
    _section("Recruitment", "briefcase")
    _link("Job Opening", "Job Opening", "file-text")
    _link("Job Applicant", "Job Applicant", "user")
    _link("Job Offer", "Job Offer", "square-check")

    # â”€â”€ Leaves â”€â”€
    _section("Leaves", "book-open")
    _link("Leave Application", "Leave Application", "file-text")
    _link("Leave Type", "Leave Type", "settings")
    _link("Leave Allocation", "Leave Allocation", "square-check")

    # â”€â”€ Payroll â”€â”€
    _section("Payroll", "banknote")
    _link("Salary Slip", "Salary Slip", "file-text")
    _link("Payroll Entry", "Payroll Entry", "square-check")
    _link("Salary Structure", "Salary Structure", "settings")

    # â”€â”€ Expense & Travel â”€â”€
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
    """Re-set workspace content via SQL â€” bench migrate overwrites it."""
    content = _get_workspace_content()
    frappe.db.sql(
        "UPDATE `tabWorkspace` SET content = %s WHERE name = 'SLHRM'",
        (json.dumps(content),),
    )
    print("Set workspace content via SQL")


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
        {"type": "Link", "label": "Salary Slip", "link_to": "Salary Slip", "link_type": "DocType", "onboard": 1},
        {"type": "Link", "label": "Payroll Entry", "link_to": "Payroll Entry", "link_type": "DocType", "onboard": 0},
        {"type": "Link", "label": "Salary Structure", "link_to": "Salary Structure", "link_type": "DocType", "onboard": 0},

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
