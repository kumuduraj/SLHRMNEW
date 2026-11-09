# slhrm/doctype/biometric_device_user/biometric_device_user.py
from frappe.model.document import Document


class BiometricDeviceUser(Document):
    """A user enrolled on a Biometric Device (id + name only; no PIN / card / template).
    Written only by slhrm.biometric.sync_users (agent)."""

    pass
