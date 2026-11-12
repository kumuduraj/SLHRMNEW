from slhrm import __version__

app_version = __version__

app_name = "slhrm"
app_title = "SLHRM"
app_publisher = "Evonet"
app_description = "Biometric fingerprint attendance for ERPNext v16"
app_color = "#3b22f6"
app_icon = "hexagon"
app_email = "rajitha@evonet.lk"
app_license = "mit"

# Assets — MUST be lists
app_include_js = [
    "/assets/slhrm/js/slhrm.js",
    "/assets/slhrm/js/device_sync.js",
]

# Biometric Device connection status: age-based transitions when heartbeats stop (v0.4.0)
scheduler_events = {
    "cron": {
        "*/5 * * * *": ["slhrm.biometric.refresh_connection_status"],
    },
}
app_include_css = ["/assets/slhrm/css/slhrm.css"]

# Install
after_install = "slhrm.install.execute"
after_migrate = ["slhrm.install.after_migrate"]

# Fixtures
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "SLHRM"]],
    },
    {
        "dt": "Workspace",
        "filters": [["app", "=", "slhrm"]],
    },
    {
        "dt": "Property Setter",
        "filters": [["module", "=", "SLHRM"]],
    },
    {
        # v0.2.1: Attendance Supervisor read-only on Branch / Employee / Shift Type / Holiday List
        "dt": "Custom DocPerm",
        "filters": [["role", "=", "Attendance Supervisor"]],
    },
]

# Doc events
doc_events = {
    "Additional Salary": {
        "before_validate": "slhrm.overrides.additional_salary.before_validate",
    },
    "Employee": {
        "after_insert": "slhrm.user_setup.create_employee_user",
        "validate": "slhrm.biometric.on_employee_validate",
        "on_update": "slhrm.biometric.on_employee_update",
    },
    "User": {
        "on_update": "slhrm.user_setup.on_user_update",
    },
    "Salary Slip": {
        # same entry point on both: submit runs validate + before_submit, never before_save
        "before_save": "slhrm.overrides.salary_slip.apply_salary_package",
        "before_submit": "slhrm.overrides.salary_slip.apply_salary_package",
    },
    "Employee Checkin": {
        "before_insert": "slhrm.overrides.employee_checkin.validate",
        "validate": "slhrm.overrides.employee_checkin.validate_update",
    },
}

# Forced password change (slhrm/user_setup.py): auth_hooks run on every request AFTER cookie /
# token / API-key auth -> Desk + PWA pages redirect to /update-password, API calls get 403.
auth_hooks = ["slhrm.user_setup.enforce_password_change"]
on_session_creation = ["slhrm.user_setup.on_session_creation"]
extend_bootinfo = ["slhrm.user_setup.extend_bootinfo", "slhrm.desk_scope.extend_bootinfo"]

# Desk scope (2026-11-11): non-admins see only the SLHRM app; they may not list / re-add other apps' desktop icons
permission_query_conditions = {
    "Desktop Icon": "slhrm.desk_scope.desktop_icon_query_conditions",
}
has_permission = {
    "Desktop Icon": "slhrm.desk_scope.desktop_icon_has_permission",
}

# Employee form: "Issue Temporary Password" (HR Manager / System Manager)
doctype_js = {"Employee": "public/js/employee.js"}

# Desk registration — modern Frappe v16 approach
add_to_apps_screen = [
    {
        "name": "slhrm",
        "logo": "/assets/slhrm/icons/desktop_icons/solid/slhrm.svg",
        "title": "SLHRM",
        "route": "/app/slhrm-dashboard",
    }
]

# PWA — serve index.html through Frappe (needs Jinja rendering for boot/csrf)
website_route_rules = [
    {
        "from_route": "/slhrm",
        "to_route": "slhrm",
    },
    {
        "from_route": "/slhrm/<path:app_page>",
        "to_route": "slhrm",
    },
]

# Jinja methods (print formats)
jinja = {
    "methods": ["slhrm.payroll_table.worksheet_table", "slhrm.payslip.payslip_data"],
}
