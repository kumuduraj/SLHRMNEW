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
]
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
]

# Doc events
doc_events = {
    "Employee": {
        "after_insert": "slhrm.user_setup.create_employee_user",
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
extend_bootinfo = ["slhrm.user_setup.extend_bootinfo"]

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
    "methods": ["slhrm.payroll_table.worksheet_table"],
}
