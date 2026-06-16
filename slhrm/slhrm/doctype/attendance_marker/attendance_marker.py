# slhrm/slhrm/doctype/attendance_marker/attendance_marker.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class AttendanceMarker(Document):
    def validate(self):
        self._check_no_duplicate_marker()
        self._validate_details_not_empty()
        self._validate_employee_company()

    def before_submit(self):
        self.approved_by = frappe.session.user
        # Clear stale attendance_record references from prior cancelled submissions
        for row in self.attendance_details:
            if row.attendance_record:
                # Verify the Attendance doc still exists and is submitted
                if not frappe.db.exists("Attendance", {"name": row.attendance_record, "docstatus": 1}):
                    row.attendance_record = None

    def on_submit(self):
        self._create_attendance_records()

    def on_cancel(self):
        self._cancel_attendance_records()

    # ── Validation ──────────────────────────────────────────────

    def _check_no_duplicate_marker(self):
        """Prevent two submitted markers for the same department + company + date.
        
        Allows multiple markers if they cover different employee subsets (e.g., 
        late arrivals). The uniqueness constraint is on department + company + date.
        """
        existing = frappe.db.exists(
            "Attendance Marker",
            {
                "date": self.date,
                "department": self.department,
                "company": self.company,
                "docstatus": 1,
                "name": ["!=", self.name],
            },
        )
        if existing:
            frappe.throw(
                _(
                    "A submitted Attendance Marker already exists for "
                    "{0} on {1} (Company: {2}). Cancel that one first or use a different company."
                ).format(self.department, self.date, self.company)
            )

    def _validate_details_not_empty(self):
        if not self.attendance_details:
            frappe.throw(_("Attendance Details table cannot be empty."))

    def _validate_employee_company(self):
        """Ensure all employees belong to the selected company."""
        if not self.company or not self.attendance_details:
            return
        emp_names = [row.employee for row in self.attendance_details]
        company_map = dict(
            frappe.db.get_all(
                "Employee",
                filters={"name": ["in", emp_names]},
                fields=["name", "company"],
                as_list=True,
            )
        )
        for row in self.attendance_details:
            emp_company = company_map.get(row.employee)
            if emp_company and emp_company != self.company:
                frappe.throw(
                    _("Employee {0} ({1}) belongs to company {2}, not {3}.").format(
                        row.employee_name, row.employee, emp_company, self.company
                    )
                )

    # ── Submit: Create Attendance ────────────────────────────────

    def _create_attendance_records(self):
        for row in self.attendance_details:
            if row.attendance_record:
                # Double-check the attendance record actually exists and is valid
                if not frappe.db.exists("Attendance", {"name": row.attendance_record, "docstatus": 1}):
                    row.attendance_record = None
                else:
                    frappe.throw(
                        _("Attendance already exists for {0}. Cancel first.").format(
                            row.employee_name
                        )
                    )

            # Skip Holiday status - not valid in core Attendance
            if row.attendance_status == "Holiday":
                continue

            att = frappe.new_doc("Attendance")
            att.employee = row.employee
            att.attendance_date = self.date
            att.status = row.attendance_status
            att.shift = row.shift
            # Combine date with time for Datetime fields - handle Time field (timedelta)
            if row.in_time:
                att.in_time = self._combine_date_time(self.date, row.in_time)
            if row.out_time:
                att.out_time = self._combine_date_time(self.date, row.out_time)
            att.working_hours = row.worked_hours
            att.leave_type = row.leave_type
            att.company = self.company
            att.flags.ignore_permissions = True
            att.submit()

            row.db_set("attendance_record", att.name)

            # Mark consumed punches as Matched
            for ref in self.punch_references:
                if ref.employee == row.employee:
                    frappe.db.set_value(
                        "Biometric Punch Log",
                        ref.punch_log,
                        "processing_status",
                        "Matched",
                    )

    def _combine_date_time(self, date_obj, time_val):
        """Safely combine a date and Time/timedelta value into a Datetime string."""
        if not time_val:
            return None
        # Time field in Frappe returns timedelta; convert to HH:MM:SS string
        if hasattr(time_val, 'total_seconds'):
            # It's a timedelta object
            total_seconds = int(time_val.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            time_str = str(time_val)
        return f"{date_obj} {time_str}"

    # ── Cancel: Reverse Attendance ───────────────────────────────

    def _cancel_attendance_records(self):
        # Collect unique punch_log names to reset (avoids redundant DB writes)
        punch_logs_to_reset = set()
        
        for row in self.attendance_details:
            if row.attendance_record:
                att = frappe.get_doc("Attendance", row.attendance_record)
                att.flags.ignore_permissions = True
                att.cancel()
                row.db_set("attendance_record", None)

            # Collect punch logs for this employee
            for ref in self.punch_references:
                if ref.employee == row.employee and ref.punch_log:
                    punch_logs_to_reset.add(ref.punch_log)

        # Bulk reset punch statuses in a single SQL operation
        if punch_logs_to_reset:
            placeholders = ", ".join(["%s"] * len(punch_logs_to_reset))
            frappe.db.sql(
                f"UPDATE `tabBiometric Punch Log` SET processing_status='Pending' WHERE name IN ({placeholders})",
                tuple(punch_logs_to_reset),
            )