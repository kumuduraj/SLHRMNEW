"""v0.3.0 (Phase 3.4): 9-hour day rule settings.

Fills the new SLHRM Settings fields (standard day 9 h, minimum daily OT 1 h, No Pay component + the PLACEHOLDER
per-day formula) only where empty. The retired fields default_ot_rate / overtime_threshold are no longer in the
DocType (their old Singles values are inert and left alone — no raw SQL on core tables).
"""
import frappe
from frappe.utils import flt

from slhrm.overtime import DEFAULT_NO_PAY_DAY_FORMULA, DEFAULT_OT_MIN_DAILY_HOURS, DEFAULT_STANDARD_DAY_HOURS

DT = "SLHRM Settings"


def execute():
    frappe.reload_doc("slhrm", "doctype", "slhrm_settings")
    get = lambda f: frappe.db.get_single_value(DT, f)  # noqa: E731
    if not flt(get("standard_day_hours")):
        frappe.db.set_single_value(DT, "standard_day_hours", DEFAULT_STANDARD_DAY_HOURS)
    if get("ot_min_daily_hours") in (None, "") or not frappe.db.exists(
            "Singles", {"doctype": DT, "field": "ot_min_daily_hours"}):
        frappe.db.set_single_value(DT, "ot_min_daily_hours", DEFAULT_OT_MIN_DAILY_HOURS)
    if not (get("no_pay_day_formula") or "").strip():
        frappe.db.set_single_value(DT, "no_pay_day_formula", DEFAULT_NO_PAY_DAY_FORMULA)
    if not get("no_pay_component") and frappe.db.exists("Salary Component", {"name": "No Pay", "type": "Deduction"}):
        frappe.db.set_single_value(DT, "no_pay_component", "No Pay")
