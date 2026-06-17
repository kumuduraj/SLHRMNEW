app_name = "slhrm"
app_title = "SLHRM"
app_publisher = "Evonet"
app_description = "Biometric fingerprint attendance for ERPNext v16"
app_version = "0.0.1"
app_color = "#3b82f6"
app_icon = "hexagon"
app_email = "rajitha@evonet.lk"
app_license = "mit"

# Assets — MUST be lists
app_include_js = ["/assets/slhrm/js/slhrm.js"]
app_include_css = ["/assets/slhrm/css/slhrm.css"]

# Install
after_install = "slhrm.install.execute"
after_migrate = "slhrm.install.after_migrate"

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
]

# Desk registration — modern Frappe v16 approach
add_to_apps_screen = [
    {
        "name": "slhrm",
        "logo": "/assets/slhrm/icons/desktop_icons/solid/slhrm.svg",
        "title": "SLHRM",
        "route": "/app/attendance-dashboard",
    }
]
