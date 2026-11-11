# slhrm/doctype/slhrm_settings/slhrm_settings.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class SLHRMSettings(Document):
    def validate(self):
        for field in ("standard_day_hours", "ot_min_daily_hours"):
            if flt(self.get(field)) < 0:
                frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(field)))
        if not flt(self.standard_day_hours):
            self.standard_day_hours = 9
        self._validate_no_pay()
        if cint(self.ot_punch_window_after) < 0:
            frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label("ot_punch_window_after")))

        for field in ("ot_component",):
            component = self.get(field)
            if component and frappe.db.get_value("Salary Component", component, "type") != "Earning":
                frappe.throw(
                    _("{0}: {1} must be an Earning salary component.").format(
                        self.meta.get_label(field), component
                    )
                )

    def _validate_no_pay(self):
        from slhrm.overtime import DEFAULT_NO_PAY_DAY_FORMULA, calculate_no_pay_rate

        self.no_pay_day_formula = (self.no_pay_day_formula or "").strip() or DEFAULT_NO_PAY_DAY_FORMULA
        try:
            calculate_no_pay_rate({"BS": 1, "BA": 1, "VA": 1, "base": 1}, self)
        except Exception as e:
            frappe.throw(_("No Pay per day formula: {0}").format(frappe.utils.escape_html(str(e) or type(e).__name__)))
        if self.no_pay_component and frappe.db.get_value("Salary Component", self.no_pay_component, "type") != "Deduction":
            frappe.throw(_("{0}: {1} must be a Deduction salary component.").format(
                self.meta.get_label("no_pay_component"), self.no_pay_component))
