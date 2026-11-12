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
        self.clean_blocked_ids()

    def clean_blocked_ids(self):
        seen = set()
        for r in self.get("blocked_user_ids") or []:
            r.device_user_id = (r.device_user_id or "").strip()
            if not r.device_user_id or "|" in r.device_user_id:
                frappe.throw(_("Blocked User IDs row {0}: Device User ID is required and may not contain '|'.").format(r.idx))
            if r.device_user_id in seen:
                frappe.throw(_("Blocked User IDs: {0} is listed twice.").format(r.device_user_id))
            seen.add(r.device_user_id)

    def on_update(self):
        from slhrm.biometric import apply_blocks

        before = self.get_doc_before_save()
        old = {r.device_user_id for r in (before.get("blocked_user_ids") or [])} if before else set()
        res = apply_blocks(self.name, unblocked=old - {r.device_user_id for r in self.get("blocked_user_ids") or []})
        if res.get("kept_matched"):
            frappe.msgprint(_("{0} punch(es) of blocked ids are already used by a submitted Attendance Marker and stay as they are.")
                            .format(res["kept_matched"]), indicator="orange")

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

