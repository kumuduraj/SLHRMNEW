# slhrm/doctype/biometric_device_branch/biometric_device_branch.py
from frappe.model.document import Document


class BiometricDeviceBranch(Document):
    """Child of Biometric Device: a branch whose employees punch on that device (Served Branches)."""
