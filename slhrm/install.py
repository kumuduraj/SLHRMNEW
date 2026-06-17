# slhrm/install.py
import frappe
import json
import os
import sys


def before_install():
    """Runs BEFORE DocType sync — setup module path so Frappe finds our DocTypes."""
    _ensure_modules_txt()
    _setup_module_path()


def execute():
    """Post-install setup: workspace sidebar, workspace page, desktop icon."""
    _create_module_def()
    _create_dashboard_page()
    _create_workspace()
    _create_workspace_sidebar()
    _create_desktop_icon()
    _add_to_all_desktop_layouts()
    _fix_sidebar_child_items()
    _remove_home_items()
    frappe.db.commit()
    print("SLHRM install complete.")


def after_migrate():
    """Runs AFTER bench migrate — recreates sidebar, kills Home, fixes content."""
    _ensure_modules_txt()
    _setup_module_path()
    _create_module_def()
    _create_dashboard_page()
    _remove_home_items()
    _rebuild_workspace_sidebar()
    _set_workspace_content()
    _set_workspace_redirect()
    frappe.db.commit()
    print("after_migrate: Sidebar rebuilt, Home removed, content + redirect set")


# ─── Module Path Fix ──────────────────────────────────────────────────────────


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


def _create_dashboard_page():
    """Create the SLHRM Dashboard page if it doesn't exist."""
    if not frappe.db.exists("Page", "slhrm-dashboard"):
        try:
            frappe.get_doc({
                "doctype": "Page",
                "name": "slhrm-dashboard",
                "page_name": "slhrm-dashboard",
                "title": "SLHRM Dashboard",
                "icon": "chart-bar",
                "module": "SLHRM",
                "standard": "No",
            }).insert(ignore_permissions=True)
            print("Created Page: slhrm-dashboard")
        except Exception:
            print("Page: slhrm-dashboard already exists or creation skipped")
    else:
        print("Page: slhrm-dashboard already exists")


# ─── Workspace Sidebar ────────────────────────────────────────────────────────


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
    sidebar.flags.ignore_links = True
    sidebar.insert(ignore_permissions=True)

    frappe.db.sql("""
        UPDATE `tabWorkspace Sidebar Item`
        SET child = 1
        WHERE parent = %s AND type = 'Link'
    """, sidebar.name)

    print("Created Workspace Sidebar: SLHRM")


def _rebuild_workspace_sidebar():
    """Delete and recreate sidebar — bench migrate overwrites it with Frappe's auto-generated items."""
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

    def _section(label, icon):
        nonlocal idx
        idx += 1
        items.append({
            "type": "Section Break", "label": label, "icon": icon,
            "indent": 0, "collapsible": 1, "keep_closed": 0, "child": 0, "idx": idx,
        })

    def _link(label, link_to, icon="", link_type="DocType"):
        nonlocal idx
        idx += 1
        items.append({
            "type": "Link", "label": label, "link_type": link_type,
            "link_to": link_to, "icon": icon, "child": 1, "indent": 0, "idx": idx,
        })

    # ── Dashboard ──
    _section("Dashboard", "chart-bar")
    _link("Attendance Dashboard", "slhrm-dashboard", "chart-bar", link_type="Page")

    # ── Time & Attendance ──
    _section("Time & Attendance", "clock")
    _link("Biometric Punch Log", "Biometric Punch Log", "file-text")
    _link("Attendance Marker", "Attendance Marker", "square-check")
    _link("Employee Checkin", "Employee Checkin", "file-text")
    _link("Attendance", "Attendance", "square-check")
    _link("Shift Type", "Shift Type", "clock")
    _link("Shift Assignment", "Shift Assignment", "square-check")

    # ── Employee ──
    _section("Employee", "user")
    _link("Employee", "Employee", "user")
    _link("Department", "Department", "layout-grid")
    _link("Designation", "Designation", "layout-grid")
    _link("Employee Onboarding", "Employee Onboarding", "user")
    _link("Employee Separation", "Employee Separation", "user")

    # ── Recruitment ──
    _section("Recruitment", "briefcase")
    _link("Job Opening", "Job Opening", "file-text")
    _link("Job Applicant", "Job Applicant", "user")
    _link("Job Offer", "Job Offer", "square-check")

    # ── Leaves ──
    _section("Leaves", "book-open")
    _link("Leave Application", "Leave Application", "file-text")
    _link("Leave Type", "Leave Type", "settings")
    _link("Leave Allocation", "Leave Allocation", "square-check")

    # ── Payroll ──
    _section("Payroll", "banknote")
    _link("Salary Slip", "Salary Slip", "file-text")
    _link("Payroll Entry", "Payroll Entry", "square-check")
    _link("Salary Structure", "Salary Structure", "settings")

    # ── Expense & Travel ──
    _section("Expense & Travel", "receipt")
    _link("Expense Claim", "Expense Claim", "file-text")
    _link("Travel Request", "Travel Request", "file-text")

    # ── Performance ──
    _section("Performance", "chart-bar")
    _link("Appraisal", "Appraisal", "file-text")
    _link("Goal", "Goal", "file-text")

    # ── Training ──
    _section("Training", "graduation-cap")
    _link("Training Program", "Training Program", "file-text")
    _link("Training Event", "Training Event", "file-text")

    # ── Settings ──
    _section("Settings", "settings")
    _link("SLHRM Settings", "SLHRM Settings", "settings")
    _link("HR Settings", "HR Settings", "settings")
    _link("Company", "Company", "layout-grid")

    return items


# ─── Workspace Page ───────────────────────────────────────────────────────────


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

    ws.flags.ignore_links = True
    ws.insert(ignore_permissions=True)

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


def _get_workspace_content():
    """Return workspace content blocks: shortcuts + headers + card blocks."""
    return [
        # ── Shortcuts ──
        {"id": "sc_dashboard", "type": "shortcut", "label": "Attendance Dashboard", "format": "{}", "link_to": "/desk/dashboard-view/Attendance", "doc_view": "Form", "icon": "chart-bar", "color": "#3b82f6"},
        {"id": "sc_marker", "type": "shortcut", "label": "New Attendance Marker", "format": "{}", "link_to": "Attendance Marker", "doc_view": "Form", "icon": "square-check", "color": "#3b82f6"},
        {"id": "sc_punch", "type": "shortcut", "label": "Biometric Punch Log", "format": "{}", "link_to": "Biometric Punch Log", "doc_view": "List", "icon": "file-text", "color": "#22c55e"},
        {"id": "sc_emp", "type": "shortcut", "label": "Employees", "format": "{}", "link_to": "Employee", "doc_view": "List", "icon": "user", "color": "#8b5cf6"},
        {"id": "sc_leave", "type": "shortcut", "label": "Leave Applications", "format": "{}", "link_to": "Leave Application", "doc_view": "List", "icon": "book-open", "color": "#f59e0b"},
        {"id": "sc_salary", "type": "shortcut", "label": "Salary Slips", "format": "{}", "link_to": "Salary Slip", "doc_view": "List", "icon": "file-text", "color": "#ef4444"},
        {"id": "sc_expense", "type": "shortcut", "label": "Expense Claims", "format": "{}", "link_to": "Expense Claim", "doc_view": "List", "icon": "file-text", "color": "#ec4899"},
        {"id": "sc_settings", "type": "shortcut", "label": "Settings", "format": "{}", "link_to": "SLHRM Settings", "doc_view": "Form", "icon": "settings", "color": "#6b7280"},

        # ── Time & Attendance ──
        {"id": "h_tna", "type": "header", "data": {"text": "Time & Attendance", "col": 12}},
        {"id": "card_tna", "type": "card", "data": {"card_name": "Time & Attendance", "col": 4}},

        # ── Employee ──
        {"id": "h_emp", "type": "header", "data": {"text": "Employee", "col": 12}},
        {"id": "card_emp", "type": "card", "data": {"card_name": "Employee", "col": 4}},

        # ── Recruitment ──
        {"id": "h_rec", "type": "header", "data": {"text": "Recruitment", "col": 12}},
        {"id": "card_rec", "type": "card", "data": {"card_name": "Recruitment", "col": 4}},

        # ── Leaves ──
        {"id": "h_leave", "type": "header", "data": {"text": "Leaves", "col": 12}},
        {"id": "card_leave", "type": "card", "data": {"card_name": "Leaves", "col": 4}},

        # ── Payroll ──
        {"id": "h_pay", "type": "header", "data": {"text": "Payroll", "col": 12}},
        {"id": "card_pay", "type": "card", "data": {"card_name": "Payroll", "col": 4}},

        # ── Expense & Travel ──
        {"id": "h_exp", "type": "header", "data": {"text": "Expense & Travel", "col": 12}},
        {"id": "card_exp", "type": "card", "data": {"card_name": "Expense & Travel", "col": 4}},

        # ── Performance ──
        {"id": "h_perf", "type": "header", "data": {"text": "Performance", "col": 12}},
        {"id": "card_perf", "type": "card", "data": {"card_name": "Performance", "col": 4}},

        # ── Training ──
        {"id": "h_train", "type": "header", "data": {"text": "Training", "col": 12}},
        {"id": "card_train", "type": "card", "data": {"card_name": "Training", "col": 4}},

        # ── Settings ──
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


# ─── Desktop Icon ────────────────────────────────────────────────────────────


def _create_desktop_icon():
    """Create the SLHRM desktop icon record."""
    if frappe.db.exists("Desktop Icon", "SLHRM"):
        frappe.delete_doc("Desktop Icon", "SLHRM", force=True)

    di = frappe.new_doc("Desktop Icon")
    di.name = di.label = "SLHRM"
    di.app = "slhrm"
    di.icon = "hexagon"
    di.icon_type = "Link"
    di.link_type = "Workspace Sidebar"
    di.link_to = "SLHRM"
    di.hidden = 0
    di.standard = 1
    di.flags.ignore_links = True
    di.insert(ignore_permissions=True)
    print("Created Desktop Icon: SLHRM")


def _add_to_all_desktop_layouts():
    """Add SLHRM tile to all existing users' saved Desktop Layouts."""
    for dl_name in frappe.get_all("Desktop Layout", pluck="name"):
        try:
            dl = frappe.get_doc("Desktop Layout", dl_name)
            layout = json.loads(dl.layout or "[]")
            layout = [x for x in layout if x.get("label") != "SLHRM"]
            layout.append({
                "label": "SLHRM",
                "link_type": "Workspace Sidebar",
                "link_to": "SLHRM",
                "app": "slhrm",
                "icon_type": "Link",
                "icon": "hexagon",
                "parent_icon": "",
                "hidden": 0,
                "idx": len(layout) + 1,
            })
            dl.layout = json.dumps(layout)
            dl.save(ignore_permissions=True)
        except Exception:
            pass
    print("Added SLHRM to all Desktop Layouts")
