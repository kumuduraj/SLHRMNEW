import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "Employee"
RENAMES = {
    "biometric_section": "slhrm_biometric_section",
    "biometric_device_id": "slhrm_biometric_device_id",
    "biometric_device_name": "slhrm_biometric_device_name",
}


def execute():
    """Rename legacy Employee biometric_* custom fields to slhrm_biometric_*.

    Idempotent: does nothing once the old Custom Fields are gone. The new fields
    are created here from the app fixtures (fixtures sync only after patches,
    and rename_field needs the new field to exist).
    """
    old_present = [
        old for old in RENAMES if frappe.db.exists("Custom Field", f"{DOCTYPE}-{old}")
    ]
    if not old_present:
        return

    _create_new_fields_from_fixtures()

    for old in old_present:
        # copies data (data fields only; section breaks have no column) and
        # updates saved report/list settings that reference the old fieldname
        rename_field(DOCTYPE, old, RENAMES[old])
        frappe.delete_doc(
            "Custom Field", f"{DOCTYPE}-{old}", force=1, ignore_permissions=True
        )

    frappe.clear_cache(doctype=DOCTYPE)


def _create_new_fields_from_fixtures():
    path = frappe.get_app_path("slhrm", "fixtures", "custom_field.json")
    with open(path) as f:
        fixtures = json.load(f)

    wanted = set(RENAMES.values())
    fields = [
        {k: v for k, v in d.items() if k not in ("doctype", "name", "dt")}
        for d in fixtures
        if d.get("dt") == DOCTYPE and d.get("fieldname") in wanted
    ]
    create_custom_fields({DOCTYPE: fields}, update=True)
