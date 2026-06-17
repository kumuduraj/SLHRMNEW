# slhrm/slhrm/doctype/biometric_punch_log/biometric_punch_log.py
import frappe
from frappe import _
from frappe.model.document import Document


class BiometricPunchLog(Document):
    def validate(self):
        self._validate_employee()
        self._validate_punch_time()
        self._check_duplicate_punch()

    def _validate_employee(self):
        if not self.employee:
            frappe.throw(_("Employee is required."))
        if not frappe.db.exists("Employee", self.employee):
            frappe.throw(_("Employee {0} does not exist.").format(self.employee))

    def _validate_punch_time(self):
        if not self.punch_time:
            frappe.throw(_("Punch Time is required."))

    def _check_duplicate_punch(self):
        """Prevent exact duplicate punches — same employee, same timestamp."""
        if self.is_new():
            existing = frappe.db.exists("Biometric Punch Log", {
                "employee": self.employee,
                "punch_time": self.punch_time,
            })
            if existing:
                frappe.throw(
                    _("Duplicate punch: {0} already has a punch at {1}.").format(
                        self.employee_name or self.employee, self.punch_time
                    )
                )