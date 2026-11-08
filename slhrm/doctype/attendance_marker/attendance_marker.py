# slhrm/slhrm/doctype/attendance_marker/attendance_marker.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime

from slhrm.attendance import (
    PUNCH_BIOMETRIC,
    get_holiday_info,
    get_settings,
    get_shift_info,
    worked_hours_from_times,
)
from slhrm.overtime import calculate_ot_hours

OT_PERMLEVEL = 1


class AttendanceMarker(Document):
    def validate(self):
        self._check_no_duplicate_marker()
        self._validate_details_not_empty()
        self._validate_employee_company()
        self._apply_overtime()

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
        """Prevent two submitted markers for the same branch + company + date.
        
        Allows multiple markers if they cover different employee subsets (e.g., 
        late arrivals). The uniqueness constraint is on branch + company + date.
        """
        existing = frappe.db.exists(
            "Attendance Marker",
            {
                "date": self.date,
                "branch": self.branch,
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
                ).format(self.branch, self.date, self.company)
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

    # ── Overtime (server-side; never trust client values) ────────

    def _apply_overtime(self):
        """Recompute worked hours, calculated OT and eligibility for every row.

        - eligibility is re-read from Employee
        - calc_normal_ot / calc_double_ot are recomputed from the row's IN/OUT times,
          its shift and the employee's holiday list (slhrm.overtime)
        - users without permlevel-1 write: new rows take the calculated OT; existing
          rows keep the stored (approved) value
        - users with permlevel-1 write: their values stand; negatives are rejected
        - ineligible employees always get 0 / 0
        """
        if not self.attendance_details:
            return

        settings = get_settings()
        emp_names = list({row.employee for row in self.attendance_details if row.employee})
        eligible = dict(
            frappe.get_all(
                "Employee", filters={"name": ["in", emp_names]},
                fields=["name", "slhrm_ot_eligible"], as_list=True,
            )
        )
        can_edit_ot = self._can_write_ot()
        stored = {}
        if not can_edit_ot and not self.is_new():
            stored = {
                r.name: r
                for r in frappe.get_all(
                    "Attendance Marker Detail",
                    filters={"parent": self.name, "parenttype": self.doctype},
                    fields=["name", "normal_ot_hours", "double_ot_hours"],
                )
            }

        date_str = str(self.date)
        for row in self.attendance_details:
            is_eligible = cint(eligible.get(row.employee))
            shift_info = get_shift_info(row.shift, date_str, settings)
            worked = worked_hours_from_times(row.in_time, row.out_time)
            calc = calculate_ot_hours(
                {
                    "employee": row.employee, "date": date_str, "ot_eligible": is_eligible,
                    "shift": row.shift, "shift_hours": shift_info.hours,
                    "in_time": row.in_time, "out_time": row.out_time, "worked_hours": worked,
                    "is_holiday": None, "holiday_type": get_holiday_info(row.employee, date_str)[1],
                },
                settings,
            )
            row.worked_hours = worked
            row.shift_hours = shift_info.hours
            row.ot_eligible = is_eligible
            row.calc_normal_ot = calc["normal"]
            row.calc_double_ot = calc["double"]

            if not is_eligible:
                row.normal_ot_hours = 0
                row.double_ot_hours = 0
                continue

            if not can_edit_ot:
                prev = stored.get(row.name)
                if prev:
                    row.normal_ot_hours = flt(prev.normal_ot_hours)
                    row.double_ot_hours = flt(prev.double_ot_hours)
                else:
                    row.normal_ot_hours = calc["normal"]
                    row.double_ot_hours = calc["double"]
                continue

            for field in ("normal_ot_hours", "double_ot_hours"):
                if flt(row.get(field)) < 0:
                    frappe.throw(
                        _("Row {0} ({1}): {2} cannot be negative.").format(
                            row.idx, row.employee_name or row.employee, row.meta.get_label(field)
                        )
                    )

    def _can_write_ot(self):
        if frappe.session.user == "Administrator" or self.flags.ignore_permissions:
            return True
        return OT_PERMLEVEL in self.get_permlevel_access("write")

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
                if ref.employee == row.employee and (ref.punch_doctype or PUNCH_BIOMETRIC) == PUNCH_BIOMETRIC:
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
                if (
                    ref.employee == row.employee
                    and ref.punch_log
                    and (ref.punch_doctype or PUNCH_BIOMETRIC) == PUNCH_BIOMETRIC
                ):
                    punch_logs_to_reset.add(ref.punch_log)

        # Bulk reset punch statuses in a single SQL operation
        if punch_logs_to_reset:
            placeholders = ", ".join(["%s"] * len(punch_logs_to_reset))
            frappe.db.sql(
                f"UPDATE `tabBiometric Punch Log` SET processing_status='Pending' WHERE name IN ({placeholders})",
                tuple(punch_logs_to_reset),
            )