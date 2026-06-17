import frappe
from frappe import _

@frappe.whitelist()
def get_dashboard_stats():
    from frappe.utils import today, add_days
    
    today_date = today()
    month_start = add_days(today_date, -30)
    
    today_stats = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabAttendance Dashboard`
        WHERE date = %s
        GROUP BY status
    """, today_date, as_dict=True)
    
    month_stats = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabAttendance Dashboard`
        WHERE date BETWEEN %s AND %s
        GROUP BY status
    """, (month_start, today_date), as_dict=True)
    
    total_employees = frappe.db.count("Employee", {"status": "Active"})
    
    recent = frappe.db.sql("""
        SELECT employee, employee_name, date, status, check_in, check_out, working_hours
        FROM `tabAttendance Dashboard`
        ORDER BY date DESC, creation DESC
        LIMIT 10
    """, as_dict=True)
    
    today_data = {s.status: s.count for s in today_stats}
    month_data = {s.status: s.count for s in month_stats}
    
    return {
        "today": {
            "present": today_data.get("Present", 0),
            "absent": today_data.get("Absent", 0),
            "half_day": today_data.get("Half Day", 0),
            "on_leave": today_data.get("On Leave", 0),
            "holiday": today_data.get("Holiday", 0),
        },
        "month": {
            "present": month_data.get("Present", 0),
            "absent": month_data.get("Absent", 0),
            "half_day": month_data.get("Half Day", 0),
            "on_leave": month_data.get("On Leave", 0),
            "holiday": month_data.get("Holiday", 0),
        },
        "total_employees": total_employees,
        "recent": recent,
    }
