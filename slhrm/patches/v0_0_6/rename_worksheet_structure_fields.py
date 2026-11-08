import frappe

CHILD = "Payroll Worksheet Employee"
MOVES = {
    "structure_earning_total": "structure_gross",
    "structure_deduction_total": "structure_deduction",
}


def execute():
    """v0.0.6: worksheet salary numbers now come from the HRMS preview; rename the v0.0.5 fields.

    Guarded and idempotent: copies only into empty targets and only while the old column exists.
    SLHRM-owned table only.
    """
    for old, new in MOVES.items():
        if frappe.db.has_column(CHILD, old) and frappe.db.has_column(CHILD, new):
            frappe.db.sql(
                f"""UPDATE `tab{CHILD}` SET `{new}` = `{old}`
                WHERE IFNULL(`{new}`, 0) = 0 AND IFNULL(`{old}`, 0) != 0"""
            )
