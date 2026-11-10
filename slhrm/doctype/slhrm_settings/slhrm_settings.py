# slhrm/doctype/slhrm_settings/slhrm_settings.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class SLHRMSettings(Document):
    def validate(self):
        for field in ("default_ot_rate", "overtime_threshold"):
            if flt(self.get(field)) < 0:
                frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(field)))
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
