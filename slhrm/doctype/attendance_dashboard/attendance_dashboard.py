import frappe
from frappe.model.document import Document


class AttendanceDashboard(Document):
    def validate(self):
        self.calculate_working_hours()

    def calculate_working_hours(self):
        if self.check_in and self.check_out:
            from frappe.utils import time_diff_in_seconds

            diff = time_diff_in_seconds(self.check_out, self.check_in)
            self.working_hours = round(diff / 3600, 2)

    @frappe.whitelist()
    def get_attendance_stats(employee=None, from_date=None, to_date=None):
        """Get attendance statistics for an employee"""
        filters = {}
        if employee:
            filters["employee"] = employee
        if from_date and to_date:
            filters["date"] = ["between", [from_date, to_date]]
        elif from_date:
            filters["date"] = [">=", from_date]
        elif to_date:
            filters["date"] = ["<=", to_date]

        records = frappe.get_all(
            "Attendance Dashboard",
            filters=filters,
            fields=["status", "working_hours", "date"],
            order_by="date desc",
        )

        stats = {
            "total_days": len(records),
            "present": 0,
            "absent": 0,
            "half_day": 0,
            "on_leave": 0,
            "holiday": 0,
            "total_hours": 0,
            "avg_hours": 0,
        }

        for r in records:
            status_key = r.status.lower().replace(" ", "_")
            if status_key in stats:
                stats[status_key] += 1
            if r.working_hours:
                stats["total_hours"] += r.working_hours

        if stats["total_days"] > 0:
            stats["avg_hours"] = round(stats["total_hours"] / stats["total_days"], 2)

        return stats

    @frappe.whitelist()
    def get_recent_attendance(employee=None, limit=10):
        """Get recent attendance records"""
        filters = {}
        if employee:
            filters["employee"] = employee

        return frappe.get_all(
            "Attendance Dashboard",
            filters=filters,
            fields=["employee", "employee_name", "date", "status", "check_in", "check_out", "working_hours"],
            order_by="date desc",
            limit_page_length=limit,
        )