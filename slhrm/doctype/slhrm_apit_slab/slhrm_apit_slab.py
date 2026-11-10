# slhrm/doctype/slhrm_apit_slab/slhrm_apit_slab.py
from frappe.model.document import Document


class SLHRMAPITSlab(Document):
    """Child of SLHRM Settings: one monthly APIT band (slhrm.statutory.calc_apit)."""
