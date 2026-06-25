app_name = "slhrm"
app_title = "SLHRM"
app_publisher = "Evonet"
app_description = "Biometric fingerprint attendance for ERPNext v16"
app_version = "0.0.1"
app_color = "#3b22f6"
app_icon = "hexagon"
app_email = "rajitha@evonet.lk"
app_license = "mit"

# Assets — MUST be lists
app_include_js = [
    "/assets/slhrm/js/slhrm.js",
    "/assets/slhrm/js/bulk_additional_salary.js",
]
app_include_css = ["/assets/slhrm/css/slhrm.css"]

# Install
after_install = "slhrm.install.execute"
after_migrate = [
    "slhrm.install.after_migrate",
    "slhrm.custom_fields.setup_custom_fields",
]

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
        "after_insert": "slhrm.api.create_employee_user"
    },
    "Salary Slip": {
        "before_save": "slhrm.overrides.salary_slip.apply_salary_package"
    }
}

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
