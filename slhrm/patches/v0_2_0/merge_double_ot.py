"""v0.2.0: ONE OT type. Merge the old Normal + Double OT values into the single OT fields, then drop
the old columns. Guarded and idempotent (runs only while an old column exists; copies only into
empty targets). SLHRM-owned tables only.

Attendance Marker Detail:   ot_hours = normal_ot_hours + double_ot_hours
                            calc_ot  = calc_normal_ot + calc_double_ot
Payroll Worksheet Employee: ot_hours = normal_ot_hours + double_ot_hours
                            ot_rate  = normal_ot_rate when there were no double hours, else
                                       ot_amount / ot_hours (ot_amount already = normal + double amount)
Payroll Worksheet:          total_ot_amount already = normal + double (kept).
"""
import frappe

DETAIL = "Attendance Marker Detail"
WS_ROW = "Payroll Worksheet Employee"
WS = "Payroll Worksheet"
DROP = {
    DETAIL: ("normal_ot_hours", "double_ot_hours", "calc_normal_ot", "calc_double_ot"),
    WS_ROW: ("normal_ot_hours", "normal_ot_rate", "normal_ot_amount", "double_ot_hours", "double_ot_rate", "double_ot_amount"),
    WS: ("total_normal_ot_amount", "total_double_ot_amount"),
}


def _has(dt, *cols):
    return all(frappe.db.has_column(dt, c) for c in cols)


def execute():
    report = {}
    if _has(DETAIL, "normal_ot_hours", "double_ot_hours", "ot_hours"):
        frappe.db.sql(f"""UPDATE `tab{DETAIL}` SET ot_hours = IFNULL(normal_ot_hours, 0) + IFNULL(double_ot_hours, 0)
                          WHERE IFNULL(ot_hours, 0) = 0""")
    if _has(DETAIL, "calc_normal_ot", "calc_double_ot", "calc_ot"):
        frappe.db.sql(f"""UPDATE `tab{DETAIL}` SET calc_ot = IFNULL(calc_normal_ot, 0) + IFNULL(calc_double_ot, 0)
                          WHERE IFNULL(calc_ot, 0) = 0""")
    if _has(DETAIL, "double_ot_hours"):
        report["marker rows with double OT merged"] = frappe.db.sql(
            f"SELECT COUNT(*) FROM `tab{DETAIL}` WHERE IFNULL(double_ot_hours, 0) != 0")[0][0]
    if _has(WS_ROW, "normal_ot_hours", "double_ot_hours", "normal_ot_rate", "ot_hours", "ot_rate"):
        frappe.db.sql(f"""UPDATE `tab{WS_ROW}`
                          SET ot_hours = IFNULL(normal_ot_hours, 0) + IFNULL(double_ot_hours, 0),
                              ot_rate = CASE WHEN IFNULL(double_ot_hours, 0) = 0 THEN IFNULL(normal_ot_rate, 0)
                                             ELSE ROUND(IFNULL(ot_amount, 0) / (IFNULL(normal_ot_hours, 0) + IFNULL(double_ot_hours, 0)), 2) END
                          WHERE IFNULL(ot_hours, 0) = 0 AND IFNULL(ot_rate, 0) = 0""")
        report["worksheet rows with double OT merged"] = frappe.db.sql(
            f"SELECT COUNT(*) FROM `tab{WS_ROW}` WHERE IFNULL(double_ot_hours, 0) != 0")[0][0]
    for dt, cols in DROP.items():
        for c in cols:
            if frappe.db.has_column(dt, c):
                frappe.db.sql_ddl(f"ALTER TABLE `tab{dt}` DROP COLUMN `{c}`")
                report.setdefault("dropped", []).append(f"{dt}.{c}")
    if report:
        print("merge_double_ot:", report)
