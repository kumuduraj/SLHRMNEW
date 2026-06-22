# slhrm/api.py
import frappe
from frappe import _
from frappe.utils import cstr
from datetime import datetime, timedelta
import os
import json


# ═══════════════════════════════════════════════════════════════
# PWA SERVING
# ═══════════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=True)
def serve_pwa():
    """Serve the SLHRM PWA index.html."""
    pwa_path = "/home/frappe/frappe-bench/apps/slhrm/public/frontend/index.html"
    if not os.path.exists(pwa_path):
        frappe.throw("PWA not found")

    with open(pwa_path, "r") as f:
        content = f.read()

    rendered = content.replace("{{ boot }}", "{}")
    rendered = rendered.replace("{{ csrf_token }}", "")
    rendered = rendered.replace("{{ site_name }}", getattr(frappe.local, "site", ""))

    frappe.local.response.filename = "index.html"
    frappe.local.response.filecontent = rendered.encode("utf-8")
    frappe.local.response.type = "download"
    frappe.local.response.content_type = "text/html; charset=utf-8"
    frappe.local.response.display_content_as = "inline"


# ═══════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════

def _validate_device_api_key():
    """Validate device API key from header or parameter. Raises 403 on failure."""
    settings = frappe.get_cached_doc("SLHRM Settings")
    if not settings.device_api_enabled:
        return
    stored_key = settings.get_password("device_api_key")
    if not stored_key:
        frappe.throw(
            _("Device API Key not configured. Set it in SLHRM Settings."),
            frappe.AuthenticationError,
        )
    provided_key = (
        frappe.request.headers.get("X-Device-Key")
        or frappe.form_dict.get("api_key")
    )
    if not provided_key or provided_key != stored_key:
        frappe.throw(
            _("Invalid or missing device API key."),
            frappe.AuthenticationError,
        )


def _get_shift_window(shift_name, date_str):
    """Return (start_dt, end_dt, working_hours) for a shift on a given date.

    If no shift_name, returns (None, None, 0) — meaning no filtering.
    Uses SLHRM Settings shift_match_window_before/after to expand the window for punch filtering.
    working_hours is calculated from the actual shift times (not expanded window).
    """
    if not shift_name:
        return None, None, 0
    shift = frappe.db.get_value(
        "Shift Type", shift_name, ["start_time", "end_time"], as_dict=True
    )
    if not shift:
        return None, None, 0
    start = datetime.strptime(f"{date_str} {shift.start_time}", "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(f"{date_str} {shift.end_time}", "%Y-%m-%d %H:%M:%S")
    if end <= start:
        end += timedelta(days=1)  # overnight shift

    # Calculate working_hours from actual shift times (not expanded window)
    working_hours = round((end - start).total_seconds() / 3600, 2)

    # Apply shift match window settings from SLHRM Settings for punch filtering
    settings = frappe.get_cached_doc("SLHRM Settings")
    before_mins = settings.shift_match_window_before or 120
    after_mins = settings.shift_match_window_after or 180
    start -= timedelta(minutes=before_mins)
    end += timedelta(minutes=after_mins)

    return start, end, working_hours


def _filter_punches_in_shift(punches, shift_start, shift_end):
    """Return only punches that fall within the shift window.

    If no shift window defined, returns all punches (no filtering).
    """
    if not shift_start or not shift_end:
        return punches
    filtered = []
    for p in punches:
        pt = p.punch_time
        if isinstance(pt, str):
            pt = datetime.strptime(pt, "%Y-%m-%d %H:%M:%S")
        if shift_start <= pt <= shift_end:
            filtered.append(p)
    return filtered


def _calc_worked_hours(in_time, out_time):
    """Calculate worked hours between two datetimes."""
    if not in_time or not out_time:
        return 0
    if isinstance(in_time, str):
        in_time = datetime.strptime(in_time, "%Y-%m-%d %H:%M:%S")
    if isinstance(out_time, str):
        out_time = datetime.strptime(out_time, "%Y-%m-%d %H:%M:%S")
    diff = out_time - in_time
    return round(diff.total_seconds() / 3600, 2)


# ═══════════════════════════════════════════════════════════════
# DEVICE API ENDPOINTS (allow_guest — secured by API key)
# ═══════════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=True)
def device_punch(device_id, employee_id, punch_time, punch_type="IN"):
    """
    Single punch from a biometric device.

    POST /api/method/slhrm.api.device_punch
    Headers: X-Device-Key: <your-api-key>
    Body: device_id, employee_id, punch_time (YYYY-MM-DD HH:MM:SS), punch_type

    employee_id can be either:
    - ERPNext Employee ID (field: employee)
    - Biometric Device ID (field: biometric_device_id custom field)
    """
    _validate_device_api_key()

    if not device_id or not employee_id or not punch_time:
        frappe.throw(_("device_id, employee_id, and punch_time are required."))

    # Try lookup by ERPNext Employee ID first, then fallback to biometric_device_id
    employee = frappe.db.get_value(
        "Employee",
        {"employee": employee_id, "status": "Active"},
        ["name", "employee_name"],
        as_dict=True,
    )
    if not employee:
        employee = frappe.db.get_value(
            "Employee",
            {"biometric_device_id": employee_id, "status": "Active"},
            ["name", "employee_name"],
            as_dict=True,
        )
    if not employee:
        frappe.throw(_("Employee {0} not found or inactive.").format(employee_id))

    # Populate biometric_device_name on Employee if not set
    if device_id:
        frappe.db.set_value("Employee", employee.name, "biometric_device_name", device_id, update_modified=False)

    doc = frappe.get_doc(
        {
            "doctype": "Biometric Punch Log",
            "employee": employee.name,
            "employee_name": employee.employee_name,
            "source_device": device_id,
            "punch_time": punch_time,
            "punch_type": punch_type,
            "processing_status": "Pending",
            "raw_data": f"Device: {device_id} | Emp: {employee_id} | Time: {punch_time} | Type: {punch_type}",
        }
    )
    doc.insert(ignore_permissions=True)
    # No frappe.db.commit() — Frappe auto-commits on success

    return {"status": "ok", "punch_log": doc.name}


@frappe.whitelist(allow_guest=True)
def device_punch_bulk(device_id, punches, strict=False):
    """
    Bulk punch endpoint for devices.

    POST /api/method/slhrm.api.device_punch_bulk
    Headers: X-Device-Key: <your-api-key>
    Body: device_id, punches (JSON array of {employee_id, punch_time, punch_type}), strict (bool, optional)

    If strict=True: rolls back ALL inserts if ANY punch fails (atomic batch).
    If strict=False (default): inserts successful punches, returns errors for failed ones.
    """
    _validate_device_api_key()

    if not device_id or not punches:
        frappe.throw(_("device_id and punches are required."))

    import json

    if isinstance(punches, str):
        punches = json.loads(punches)

    created = []
    errors = []

    # Use savepoint for strict mode
    if strict:
        frappe.db.savepoint("bulk_punch_start")

    for p in punches:
        try:
            # Try lookup by ERPNext Employee ID first, then fallback to biometric_device_id
            employee = frappe.db.get_value(
                "Employee",
                {"employee": p.get("employee_id"), "status": "Active"},
                ["name", "employee_name"],
                as_dict=True,
            )
            if not employee:
                employee = frappe.db.get_value(
                    "Employee",
                    {"biometric_device_id": p.get("employee_id"), "status": "Active"},
                    ["name", "employee_name"],
                    as_dict=True,
                )
            if not employee:
                err = {"employee_id": p.get("employee_id"), "error": "Employee not found or inactive"}
                errors.append(err)
                if strict:
                    frappe.db.rollback(save_point="bulk_punch_start")
                    frappe.throw(_("Strict mode: batch rolled back — {0}").format(err["error"]))
                continue

            # Populate biometric_device_name on Employee if not set
            if device_id:
                frappe.db.set_value("Employee", employee.name, "biometric_device_name", device_id, update_modified=False)

            doc = frappe.get_doc(
                {
                    "doctype": "Biometric Punch Log",
                    "employee": employee.name,
                    "employee_name": employee.employee_name,
                    "source_device": device_id,
                    "punch_time": p.get("punch_time"),
                    "punch_type": p.get("punch_type", "IN"),
                    "processing_status": "Pending",
                    "raw_data": f"Device: {device_id} | Emp: {p.get('employee_id')} | Time: {p.get('punch_time')}",
                }
            )
            doc.insert(ignore_permissions=True)
            created.append(doc.name)
        except Exception as e:
            errors.append({"employee_id": p.get("employee_id"), "error": str(e)})
            if strict:
                frappe.db.rollback(save_point="bulk_punch_start")
                frappe.throw(_("Strict mode: batch rolled back due to error: {0}").format(str(e)))

    if not created and errors:
        frappe.db.rollback()
        frappe.throw(_("All punches failed: {0}").format(str(errors)))

    if strict and errors:
        frappe.db.rollback(save_point="bulk_punch_start")
        frappe.throw(_("Strict mode: batch rolled back due to {0} errors").format(len(errors)))

    return {"created": len(created), "errors": errors, "created_names": created}



# ═══════════════════════════════════════════════════════════════
# INTERNAL API ENDPOINTS (authenticated users only)
# ═══════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_shift_details(shift_name):
    """Return shift start_time, end_time, working_hours for the form."""
    if not shift_name:
        return {}
    shift = frappe.db.get_value(
        "Shift Type", shift_name, ["name", "start_time", "end_time"], as_dict=True
    )
    if shift:
        start = datetime.strptime(f"2000-01-01 {shift.start_time}", "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(f"2000-01-01 {shift.end_time}", "%Y-%m-%d %H:%M:%S")
        if end <= start:
            end += timedelta(days=1)
        shift.working_hours = round((end - start).total_seconds() / 3600, 2)
    return shift or {}


@frappe.whitelist()
def load_attendance_data(date, department, device_id=""):
    """
    Main data-loading endpoint for the Attendance Marker form.

    Returns:
        employees: list of active employees in the department (excluding already-marked)
        punch_logs: list of punch logs for the date
        matched: dict keyed by employee name with calculated hours/OT
    """
    if not date or not department:
        frappe.throw(_("Date and Department are required."))

    date_str = str(date)

    # ── Already-marked employees (single SQL, not N+1) ──
    marked_employees_list = frappe.db.sql(
        """
        SELECT DISTINCT amd.employee
        FROM `tabAttendance Marker Detail` amd
        INNER JOIN `tabAttendance Marker` am ON am.name = amd.parent
        WHERE am.date = %s AND am.docstatus = 1
        """,
        (date_str,),
        as_list=True,
    )
    marked_employees = {row[0] for row in marked_employees_list}

    # ── Active employees in this department ──
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active", "department": department},
        fields=[
            "name",
            "employee_name",
            "department",
            "designation",
            "company",
            "default_shift",
        ],
        order_by="employee_name asc",
    )
    employees = [e for e in employees if e.name not in marked_employees]

    # Early return if no employees to process
    if not employees:
        return {"employees": [], "punch_logs": [], "matched": {}}

    # ── Punch logs for this date (SQL-level date filter) ──
    punch_filters = {
        "punch_time": ["between", [f"{date_str} 00:00:00", f"{date_str} 23:59:59"]],
    }
    if device_id:
        punch_filters["source_device"] = device_id

    # Filter by employees in this department
    emp_names = [e.name for e in employees]
    if emp_names:
        punch_filters["employee"] = ["in", emp_names]

    punch_logs = frappe.get_all(
        "Biometric Punch Log",
        filters=punch_filters,
        order_by="punch_time asc",
        fields=[
            "name",
            "employee",
            "employee_name",
            "punch_time",
            "punch_type",
            "processing_status",
            "source_device",
        ],
    )

    # ── Group punches by employee ──
    emp_punches = {}
    for log in punch_logs:
        emp_punches.setdefault(log.employee, []).append(log)

    # ── Match employees to their punches, calculate hours ──
    matched = {}
    for emp in employees:
        emp_shift = emp.default_shift
        shift_start, shift_end, shift_hours = _get_shift_window(emp_shift, date_str)

        raw_punches = emp_punches.get(emp.name, [])
        # Filter punches to shift window for hour calculations
        filtered_punches = _filter_punches_in_shift(raw_punches, shift_start, shift_end)

        if filtered_punches:
            in_time = filtered_punches[0].punch_time
            out_time = filtered_punches[-1].punch_time
            worked = _calc_worked_hours(in_time, out_time)
            ot = max(0, round(worked - shift_hours, 2)) if shift_hours else 0
        else:
            in_time = None
            out_time = None
            worked = 0
            ot = 0

        warning = ""
        if len(raw_punches) == 1:
            warning = "Single punch only — missing OUT"

        matched[emp.name] = {
            "in_time": in_time,
            "out_time": out_time,
            "worked_hours": worked,
            "overtime_hours": ot,
            "shift_hours": shift_hours,
            "shift": emp_shift or "",
            "punch_count": len(raw_punches),
            "warning": warning,
        }

    return {
        "employees": employees,
        "punch_logs": punch_logs,
        "matched": matched,
    }


@frappe.whitelist()
def recalc_attendance_row(employee, date, shift):
    """
    Recalculate in_time, out_time, worked_hours, overtime_hours
    when user changes the shift on an attendance detail row.
    """
    if not employee or not date:
        frappe.throw(_("Employee and Date are required."))

    date_str = str(date)
    shift_start, shift_end, shift_hours = _get_shift_window(shift, date_str)

    punches = frappe.get_all(
        "Biometric Punch Log",
        filters={
            "employee": employee,
            "punch_time": ["between", [f"{date_str} 00:00:00", f"{date_str} 23:59:59"]],
        },
        order_by="punch_time asc",
        fields=["name", "punch_time", "punch_type", "source_device"],
    )

    # Filter to shift window
    filtered = _filter_punches_in_shift(punches, shift_start, shift_end)

    if filtered:
        in_time = filtered[0].punch_time
        out_time = filtered[-1].punch_time
        worked = _calc_worked_hours(in_time, out_time)
        ot = max(0, round(worked - shift_hours, 2)) if shift_hours else 0
    else:
        in_time = None
        out_time = None
        worked = 0
        ot = 0

    return {
        "in_time": in_time,
        "out_time": out_time,
        "worked_hours": worked,
        "overtime_hours": ot,
        "shift_hours": shift_hours,
        "punch_count": len(punches),
        "warning": "Single punch only — missing OUT" if len(punches) == 1 else "",
    }


@frappe.whitelist()
def get_punch_logs(device_id="", date=None):
    """Fetch punch logs for a specific device and date."""
    if not date:
        frappe.throw(_("Date is required."))

    filters = {
        "punch_time": ["between", [f"{date} 00:00:00", f"{date} 23:59:59"]],
    }
    if device_id:
        filters["source_device"] = device_id

    return frappe.get_all(
        "Biometric Punch Log",
        filters=filters,
        order_by="punch_time asc",
        fields=[
            "name",
            "employee",
            "employee_name",
            "punch_time",
            "punch_type",
            "processing_status",
        ],
    )

# ???????????????????????????????????????????????????????????????
# TEAM CHECK-IN ENDPOINTS
# ???????????????????????????????????????????????????????????????

@frappe.whitelist()
def get_team_checkins(employee, date):
    """
    Get team members' check-in status for a given date.
    Returns employees who report to the given employee with their check-in status.
    """
    if not employee or not date:
        frappe.throw(_("Employee and Date are required."))

    date_str = str(date)

    # Get all employees who report to this employee (direct reports)
    team_members = frappe.get_all(
        "Employee",
        filters={
            "reports_to": employee,
            "status": "Active",
        },
        fields=["name", "employee_name", "designation", "user_id"],
        order_by="employee_name asc",
    )

    if not team_members:
        return []

    # Get check-in records for these team members on the given date
    emp_names = [m.name for m in team_members]
    checkins = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": ["in", emp_names],
            "time": ["between", [f"{date_str} 00:00:00", f"{date_str} 23:59:59"]],
        },
        fields=["employee", "log_type", "time"],
        order_by="time asc",
    )

    # Group checkins by employee and get the latest status
    emp_checkins = {}
    for c in checkins:
        emp_name = c.employee
        if emp_name not in emp_checkins:
            emp_checkins[emp_name] = []
        emp_checkins[emp_name].append(c)

    # Build result
    result = []
    for member in team_members:
        emp_name = member.name
        emp_logs = emp_checkins.get(emp_name, [])

        log_type = None
        last_checkin = None

        if emp_logs:
            # Get the last check-in of the day
            last_log = emp_logs[-1]
            log_type = last_log.log_type
            last_checkin = last_log.time

        result.append({
            "employee": emp_name,
            "employee_name": member.employee_name,
            "designation": member.designation or "",
            "log_type": log_type,
            "last_checkin": last_checkin,
        })

    return result
