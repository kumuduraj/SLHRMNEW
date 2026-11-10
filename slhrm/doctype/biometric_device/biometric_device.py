# slhrm/doctype/biometric_device/biometric_device.py
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe import _
from frappe.model.document import Document


class BiometricDevice(Document):
    """A biometric device the SLHRM agent reads (read-only). Name = device serial number.
    Health fields are written only by slhrm.biometric.heartbeat."""

    def validate(self):
        self.serial = (self.serial or "").strip()
        if not self.serial or "|" in self.serial:
            frappe.throw(_("Serial Number is required and may not contain '|'."))
        try:
            ZoneInfo(self.timezone or "")
        except (ZoneInfoNotFoundError, ValueError):
            frappe.throw(_("Unknown timezone {0}. Use an IANA name such as Asia/Colombo.").format(self.timezone))
        self.set_served_branches()

    def set_served_branches(self):
        """The device's own branch is always served; no duplicates."""
        seen, rows = set(), []
        for r in self.get("served_branches") or []:
            if r.branch and r.branch not in seen:
                seen.add(r.branch)
                rows.append(r)
        self.set("served_branches", rows)
        if self.branch and self.branch not in seen:
            self.append("served_branches", {"branch": self.branch})

