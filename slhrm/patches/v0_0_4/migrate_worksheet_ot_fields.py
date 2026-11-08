import frappe

CHILD = "Payroll Worksheet Employee"

# old column -> new field (old columns stay in the table after the field is removed)
MOVES = {
    "ot_hours": "normal_ot_hours",
    "ot_rate": "normal_ot_rate",
}


def execute():
    """Move legacy single-OT worksheet values into the Normal OT fields.

    Guarded and idempotent: copies only into empty (0/NULL) targets and only while
    the old column exists. SLHRM-owned table only.
    """
    for old, new in MOVES.items():
        if frappe.db.has_column(CHILD, old) and frappe.db.has_column(CHILD, new):
            frappe.db.sql(
                f"""UPDATE `tab{CHILD}` SET `{new}` = `{old}`
                WHERE IFNULL(`{new}`, 0) = 0 AND IFNULL(`{old}`, 0) != 0"""
            )
