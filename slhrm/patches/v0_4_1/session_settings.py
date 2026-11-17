"""v0.4.1: defaults for OT eligible by default (on), rest gap 6 h, max session 20 h — only where unset."""
import frappe

DT = "SLHRM Settings"


def execute():
    frappe.reload_doc("slhrm", "doctype", "slhrm_settings")
    for field, value in (("ot_eligible_by_default", 1), ("rest_gap_hours", 6), ("max_session_hours", 20)):
        if not frappe.db.exists("Singles", {"doctype": DT, "field": field}):
            frappe.db.set_single_value(DT, field, value)
