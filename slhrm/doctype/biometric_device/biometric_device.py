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
        self.validate_unique_device_ids()

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

    def validate_unique_device_ids(self):
        """Device user ids must identify ONE Active employee across the served branches."""
        branches = [r.branch for r in self.served_branches if r.branch]
        if len(branches) < 2:
            return
        dupes = frappe.db.sql("""select slhrm_biometric_device_id, group_concat(concat(name, ' ', employee_name, ' (', branch, ')')
                                 separator '; ') who, count(*) n from tabEmployee
                                 where status = 'Active' and ifnull(slhrm_biometric_device_id, '') != '' and branch in %(b)s
                                 group by slhrm_biometric_device_id having n > 1""", {"b": tuple(branches)}, as_dict=True)
        if dupes:
            frappe.throw(_("These device user ids are used by more than one active employee of the served branches {0}:"
                           "<br>{1}<br>Fix the employees' device ids first.").format(
                               ", ".join(branches), "<br>".join(f"{x.slhrm_biometric_device_id}: {x.who}" for x in dupes[:20])),
                         title=_("Device user ids not unique"))
