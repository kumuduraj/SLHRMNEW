import frappe


def execute():
    """Earlier SLHRM versions deleted the core "Home" workspace on every migrate.

    SLHRM no longer touches it. Home is a standard ERPNext workspace, so the
    regular app sync restores it; this patch never recreates core records,
    it only logs the state for the record.
    """
    if frappe.db.exists("Workspace", "Home"):
        print("SLHRM: core 'Home' workspace present; nothing to do")
        return

    msg = (
        "Core 'Home' workspace is missing. SLHRM no longer deletes it and will not "
        "recreate it; the owning app restores it on `bench migrate`."
    )
    print(f"SLHRM: {msg}")
    frappe.log_error(title="SLHRM: Home workspace missing", message=msg)
