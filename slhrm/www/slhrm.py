import frappe
from frappe.boot import load_translations

no_cache = 1


def get_context(context):
    csrf_token = frappe.sessions.get_csrf_token()
    frappe.db.commit()  # persist the CSRF token for this session
    context.csrf_token = csrf_token
    context.site_name = frappe.local.site
    context.boot = frappe.as_json(get_boot(), indent=None)
    context.no_cache = 1
    return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
    if not frappe.conf.developer_mode:
        frappe.throw(frappe._("This method is only meant for developer mode"))
    return get_boot()


def get_boot():
    # Keys read by SLHRM-PWA/src from window.frappe.boot:
    # push_relay_server_url, lang, __messages (translations_hash: not provided
    # by Frappe v16; the PWA falls back to a cache-busting value)
    bootinfo = frappe._dict(
        {
            "sitename": frappe.local.site,
            "site_name": frappe.local.site,
            "socketio_port": frappe.conf.get("socketio_port") or 9000,
            "push_relay_server_url": frappe.conf.get("push_relay_server_url") or "",
            "default_route": "/slhrm",
        }
    )
    bootinfo.lang = frappe.local.lang
    load_translations(bootinfo)  # sets __messages
    return bootinfo
