"""v0.4.0: initial connection status — last_success_at from the last OK read, then the status (no notification)."""
import frappe


def execute():
    frappe.reload_doc("slhrm", "doctype", "biometric_device")
    for d in frappe.get_all("Biometric Device", fields=["name", "last_pull", "last_pull_ok", "last_success_at"]):
        if not d.last_success_at and d.last_pull_ok and d.last_pull:
            frappe.db.set_value("Biometric Device", d.name, "last_success_at", d.last_pull, update_modified=False)
    from slhrm.biometric import refresh_connection_status

    refresh_connection_status(notify=False)
