# slhrm/slhrm/doctype/attendance_marker/attendance_marker.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from slhrm.attendance import (
    MAX_PLAUSIBLE_HOURS,
    PUNCH_BIOMETRIC,
    combine,
    day_figures,
    get_holiday_info,
    get_settings,
    get_shift_info,
    out_is_next_day,
    previous_day_marker,
    span_hours,
)
OT_PERMLEVEL = 1
SHORT_LEAVE_FIELDS = ("short_leave", "short_leave_min", "short_leave_note")
LEVEL1_FIELDS = ("ot_hours", *SHORT_LEAVE_FIELDS)  # permlevel 1 in Attendance Marker Detail


class AttendanceMarker(Document):
    def validate(self):
        self._check_no_duplicate_marker()
        self._validate_details_not_empty()
        self._validate_employee_company()
        self._apply_overtime()
        self._warn_previous_day()

    def _warn_previous_day(self):
        """Warn (never block) when the previous day's marker of this branch is not submitted: that day's
        night shifts are only known to this day's punch windows from a submitted marker."""
        if not self.branch or not self.date:
            return
        prev = previous_day_marker(self.branch, self.company, str(self.date))
        if prev.status != "Submitted":
            frappe.msgprint(
                _("Previous day {0} not submitted — night shifts from that day may claim punches from this day.").format(
                    frappe.format_value(prev.date, {"fieldtype": "Date"})),
                title=_("Previous day"), indicator="orange")

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

    # ── Overtime + early/late (server-side; never trust client values) ──

    def _apply_overtime(self):
        """Recompute worked hours, early/late minutes, short-leave excuses, calculated OT and
        eligibility for every row, then the Lates counts.

        - eligibility is re-read from Employee; ineligible employees always get OT 0
        - calc_ot (system value) is always recomputed (slhrm.attendance.day_figures)
        - users with permlevel-1 write (HR Manager, Attendance Supervisor, System Manager): their
          ot_hours / short-leave values stand (negatives rejected); ot_hours != calc_ot records
          ot_edited_by / ot_edited_on (kept from the stored row when the value did not change)
        - other users: short-leave fields keep the stored values; ot_hours keeps an edited stored value,
          otherwise follows calc_ot
        """
        if not self.attendance_details:
            self.late_in_count = self.early_out_count = self.no_shift_count = 0
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
        if not self.is_new():
            stored = {
                r.name: r
                for r in frappe.get_all(
                    "Attendance Marker Detail",
                    filters={"parent": self.name, "parenttype": self.doctype},
                    fields=["name", *LEVEL1_FIELDS, "ot_edited_by", "ot_edited_on"],
                )
            }

        date_str = str(self.date)
        long_rows = []
        late_in_count = early_out_count = no_shift_count = 0
        for row in self.attendance_details:
            row.shift_date = self.date
            prev = stored.get(row.name)
            if not can_edit_ot:
                for field in SHORT_LEAVE_FIELDS:
                    row.set(field, prev.get(field) if prev else (0 if field != "short_leave_note" else None))
            elif cint(row.short_leave_min) < 0:
                frappe.throw(_("Row {0} ({1}): Short Leave (min) cannot be negative.").format(
                    row.idx, row.employee_name or row.employee))
            # OUT before IN on the same day is impossible -> OUT is on the next day; no OUT -> no flag
            if not row.out_time:
                row.out_next_day = 0
            elif out_is_next_day(row.in_time, row.out_time):
                row.out_next_day = 1
            is_eligible = cint(eligible.get(row.employee))
            shift_info = get_shift_info(row.shift, date_str, settings)
            worked = span_hours(date_str, row.in_time, row.out_time, row.out_next_day)
            if worked > MAX_PLAUSIBLE_HOURS:
                long_rows.append(f"{row.idx}. {row.employee_name or row.employee}: {worked} h")
            fig = day_figures(
                shift_info, combine(date_str, row.in_time), combine(date_str, row.out_time, row.out_next_day),
                worked, is_eligible, get_holiday_info(row.employee, date_str)[1], settings,
                row.short_leave, row.short_leave_min,
            )
            row.update(fig)
            row.worked_hours = worked
            row.shift_hours = shift_info.hours
            row.ot_eligible = is_eligible
            if cint(row.late_in_min) and not cint(row.late_in_excused):
                late_in_count += 1
            if cint(row.early_out_min) and not cint(row.early_out_excused):
                early_out_count += 1
            no_shift_count += cint(row.no_shift)

            if not is_eligible:
                row.ot_hours = 0
            elif not prev and row.get("ot_hours") in (None, ""):
                row.ot_hours = fig["calc_ot"]  # new row without a value (API / import) -> calculated OT
            elif not can_edit_ot:
                row.ot_hours = flt(prev.ot_hours) if prev and prev.ot_edited_by else fig["calc_ot"]
            elif flt(row.ot_hours) < 0:
                frappe.throw(
                    _("Row {0} ({1}): {2} cannot be negative.").format(
                        row.idx, row.employee_name or row.employee, row.meta.get_label("ot_hours")
                    )
                )
            self._set_ot_edited(row, prev, can_edit_ot)

        self.late_in_count = late_in_count
        self.early_out_count = early_out_count
        self.no_shift_count = no_shift_count
        if long_rows:  # warn, don't block (manual overnight entries)
            frappe.msgprint(_("More than {0} worked hours — check IN / OUT and the OUT next day box:").format(MAX_PLAUSIBLE_HOURS)
                            + "<br>" + "<br>".join(long_rows), title=_("Long shifts"), indicator="orange")

    @staticmethod
    def _set_ot_edited(row, prev, can_edit_ot):
        """ot_edited_by / ot_edited_on: who set ot_hours away from calc_ot (never from the client)."""
        if flt(row.ot_hours, 2) == flt(row.calc_ot, 2):
            row.ot_edited_by = row.ot_edited_on = None
        elif can_edit_ot and (not prev or flt(prev.ot_hours, 2) != flt(row.ot_hours, 2) or not prev.ot_edited_by):
            row.ot_edited_by, row.ot_edited_on = frappe.session.user, now_datetime()
        else:
            row.ot_edited_by = prev.ot_edited_by if prev else None
            row.ot_edited_on = prev.ot_edited_on if prev else None

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
            # IN = shift date + in_time; OUT = (shift date + 1 if "OUT next day") + out_time
            if row.in_time:
                att.in_time = combine(self.date, row.in_time)
            if row.out_time:
                att.out_time = combine(self.date, row.out_time, row.out_next_day)
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