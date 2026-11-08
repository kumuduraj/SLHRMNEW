import frappe

DETAIL = "Attendance Marker Detail"
REFS = "Attendance Marker Punch Reference"

# old column -> new field (old columns stay in the table after the field is removed)
DETAIL_MOVES = {
    "actual_overtime": "normal_ot_hours",
    "overtime_hours": "calc_normal_ot",
}


def execute():
    """Move legacy Attendance Marker OT values into the Normal/Double OT fields.

    Guarded and idempotent: copies only into empty (0/NULL) targets and only while
    the old column exists. SLHRM-owned tables only.
    """
    for old, new in DETAIL_MOVES.items():
        if frappe.db.has_column(DETAIL, old) and frappe.db.has_column(DETAIL, new):
            frappe.db.sql(
                f"""UPDATE `tab{DETAIL}` SET `{new}` = `{old}`
                WHERE IFNULL(`{new}`, 0) = 0 AND IFNULL(`{old}`, 0) != 0"""
            )

    if frappe.db.has_column(REFS, "punch_doctype"):
        frappe.db.sql(
            f"""UPDATE `tab{REFS}` SET punch_doctype = 'Biometric Punch Log'
            WHERE IFNULL(punch_doctype, '') = ''"""
        )
