# slhrm/doctype/biometric_device_blocked_user/biometric_device_blocked_user.py
from frappe.model.document import Document


class BiometricDeviceBlockedUser(Document):
    """Child of Biometric Device (Blocked User IDs): a device user id of THIS device that is never matched to an
    employee (not by Attendance Device ID, not by employee number). Its punches stay Unmatched with match_reason = reason."""
