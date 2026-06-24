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

    csrf_token = ""
    try:
        csrf_token = frappe.sessions.get_csrf_token()
    except Exception:
        pass

    site_name = getattr(frappe.local, "site", "")

    boot = {"sitename": site_name}

    rendered = content.replace("{{ boot }}", json.dumps(boot))
    rendered = rendered.replace("{{ csrf_token }}", csrf_token)
    rendered = rendered.replace("{{ site_name }}", site_name)

    frappe.local.response.filename = "index.html"
    frappe.local.response.filecontent = rendered.encode("utf-8")
    frappe.local.response.type = "download"
    frappe.local.response.content_type = "text/html; charset=utf-8"
    frappe.local.response.display_content_as = "inline"
    if not os.path.exists(pwa_path):
        frappe.throw("PWA not found")

    with open(pwa_path, "r") as f:
        content = f.read()

    csrf_token = ""
    try:
        csrf_token = frappe.sessions.get_csrf_token()
    except Exception:
        pass

    site_name = getattr(frappe.local, "site", "")

    boot = {"sitename": site_name}

    rendered = content.replace("{{ boot }}", json.dumps(boot))
    rendered = rendered.replace("{{ csrf_token }}", csrf_token)
    rendered = rendered.replace("{{ site_name }}", site_name)

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
    - Employee Number (field: employee_number)
    - Biometric Device ID (field: biometric_device_id custom field)
    """
    _validate_device_api_key()

    if not device_id or not employee_id or not punch_time:
        frappe.throw(_("device_id, employee_id, and punch_time are required."))

    # Try lookup by ERPNext Employee ID first, then employee_number, then biometric_device_id
    employee = frappe.db.get_value(
        "Employee",
        {"employee": employee_id, "status": "Active"},
        ["name", "employee_name", "employee_number"],
        as_dict=True,
    )
    if not employee:
        employee = frappe.db.get_value(
            "Employee",
            {"employee_number": employee_id, "status": "Active"},
            ["name", "employee_name", "employee_number"],
            as_dict=True,
        )
    if not employee:
        employee = frappe.db.get_value(
            "Employee",
            {"biometric_device_id": employee_id, "status": "Active"},
            ["name", "employee_name", "employee_number"],
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
            "employee_number": employee.employee_number or employee_id,
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
            # Try lookup by ERPNext Employee ID first, then employee_number, then biometric_device_id
            employee = frappe.db.get_value(
                "Employee",
                {"employee": p.get("employee_id"), "status": "Active"},
                ["name", "employee_name", "employee_number"],
                as_dict=True,
            )
            if not employee:
                employee = frappe.db.get_value(
                    "Employee",
                    {"employee_number": p.get("employee_id"), "status": "Active"},
                    ["name", "employee_name", "employee_number"],
                    as_dict=True,
                )
            if not employee:
                employee = frappe.db.get_value(
                    "Employee",
                    {"biometric_device_id": p.get("employee_id"), "status": "Active"},
                    ["name", "employee_name", "employee_number"],
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
                    "employee_number": employee.employee_number or p.get("employee_id"),
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
def load_attendance_data(date, branch, device_id=""):
    """
    Main data-loading endpoint for the Attendance Marker form.

    Returns:
        employees: list of active employees in the branch (excluding already-marked)
        punch_logs: list of punch logs for the date
        matched: dict keyed by employee name with calculated hours/OT
    """
    if not date or not branch:
        frappe.throw(_("Date and Branch are required."))

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

    # ── Active employees in this branch ──
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active", "branch": branch},
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

    # Filter by employees in this branch
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


# ═══════════════════════════════════════════════════════════════
# PAYROLL WORKSHEET DATA LOADER
# ═══════════════════════════════════════════════════════════════

@frappe.whitelist()
def load_payroll_data(branch, company, payroll_month, payroll_year):
    """
    Main data-loading endpoint for the Payroll Worksheet form.
    Same pattern as load_attendance_data() for the Attendance Marker.

    Returns:
        employees: list of dicts with salary, attendance, OT data per employee
        earnings:  list of Additional Salary (Earning) records for the period
        deductions: list of Additional Salary (Deduction) + Loan records
        summary: totals dict
        warnings: list of warning strings
    """
    from frappe.utils import getdate, get_first_day, get_last_day, flt, cint

    if not branch or not company or not payroll_month or not payroll_year:
        frappe.throw(_("Branch, Company, Month and Year are required."))

    year = cint(payroll_year)
    month = cint(payroll_month)
    start_date = get_first_day(f"{year}-{month:02d}-01")
    end_date = get_last_day(f"{year}-{month:02d}-01")

    # ── 1. Active employees in branch ──
    employees_raw = frappe.db.get_all(
        "Employee",
        filters={
            "company": company,
            "branch": branch,
            "status": "Active",
        },
        fields=["name", "employee_name", "designation"],
        order_by="employee_name asc",
    )

    if not employees_raw:
        return {
            "employees": [],
            "earnings": [],
            "deductions": [],
            "summary": {},
            "warnings": ["No active employees found in this branch."],
        }

    emp_names = [e.name for e in employees_raw]
    warnings = []

    # ── 2. Salary Structure Assignments (batch — latest per employee) ──
    ssa_map = {}
    ssas = frappe.db.sql(
        """
        SELECT ssa.employee, ssa.base, ssa.salary_structure,
               ssa.custom_basic_salary, ssa.custom_base_allowance, ssa.custom_vehicle_allowance
        FROM `tabSalary Structure Assignment` ssa
        INNER JOIN (
            SELECT employee, MAX(from_date) as max_date
            FROM `tabSalary Structure Assignment`
            WHERE employee IN %(employees)s
                AND from_date <= %(end_date)s
                AND docstatus = 1
            GROUP BY employee
        ) latest ON ssa.employee = latest.employee AND ssa.from_date = latest.max_date
        WHERE ssa.docstatus = 1
        """,
        {"employees": emp_names, "end_date": end_date},
        as_dict=True,
    )
    for row in ssas:
        ssa_map[row.employee] = {
            "base": flt(row.base),
            "salary_structure": row.salary_structure,
            "custom_basic_salary": flt(row.custom_basic_salary),
            "custom_base_allowance": flt(row.custom_base_allowance),
            "custom_vehicle_allowance": flt(row.custom_vehicle_allowance),
        }

    no_ssa = [e.employee_name for e in employees_raw if e.name not in ssa_map]
    if no_ssa:
        warnings.append(
            f"{len(no_ssa)} employee(s) have no Salary Structure Assignment: "
            + ", ".join(no_ssa[:5])
            + ("..." if len(no_ssa) > 5 else "")
        )

    # ── 3. Attendance summary (batch) ──
    att_map = {}
    att_records = frappe.db.sql(
        """
        SELECT employee, status, COUNT(*) as cnt
        FROM `tabAttendance`
        WHERE employee IN %(employees)s
            AND attendance_date BETWEEN %(start)s AND %(end)s
            AND docstatus = 1
        GROUP BY employee, status
        """,
        {"employees": emp_names, "start": start_date, "end": end_date},
        as_dict=True,
    )
    for row in att_records:
        if row.employee not in att_map:
            att_map[row.employee] = {"present": 0, "leave": 0}
        if row.status == "Present":
            att_map[row.employee]["present"] += row.cnt
        elif row.status == "Half Day":
            att_map[row.employee]["present"] += row.cnt * 0.5
            att_map[row.employee]["leave"] += row.cnt * 0.5
        elif row.status == "On Leave":
            att_map[row.employee]["leave"] += row.cnt
        elif row.status == "Work From Home":
            att_map[row.employee]["present"] += row.cnt

    # ── 4. OT hours from Attendance Marker Detail (batch, submitted only) ──
    ot_map = {}
    ot_records = frappe.db.sql(
        """
        SELECT amd.employee, SUM(amd.overtime_hours) as total_ot
        FROM `tabAttendance Marker Detail` amd
        INNER JOIN `tabAttendance Marker` am ON am.name = amd.parent
        WHERE amd.employee IN %(employees)s
            AND am.date BETWEEN %(start)s AND %(end)s
            AND am.docstatus = 1
        GROUP BY amd.employee
        """,
        {"employees": emp_names, "start": start_date, "end": end_date},
        as_dict=True,
    )
    for row in ot_records:
        ot_map[row.employee] = flt(row.total_ot)

    # ── 5. Additional Salary records (batch) ──
    addl_records = frappe.db.sql(
        """
        SELECT
            ads.name,
            ads.employee,
            ads.employee_name,
            ads.salary_component,
            ads.amount,
            ads.type,
            sc.type as component_type
        FROM `tabAdditional Salary` ads
        LEFT JOIN `tabSalary Component` sc ON sc.name = ads.salary_component
        WHERE ads.employee IN %(employees)s
            AND ads.docstatus = 1
            AND (
                (ads.payroll_date BETWEEN %(start)s AND %(end)s)
                OR (
                    ads.from_date IS NOT NULL
                    AND ads.to_date IS NOT NULL
                    AND ads.from_date <= %(end)s
                    AND ads.to_date >= %(start)s
                )
            )
        """,
        {"employees": emp_names, "start": start_date, "end": end_date},
        as_dict=True,
    )

    addl_earn_map = {}
    addl_ded_map = {}
    earnings_list = []
    deductions_list = []

    # ── 5a. Salary Structure components (calculated from formulas) ──
    unique_ss = list(set(
        ssa_map[e]["salary_structure"] for e in ssa_map if ssa_map[e].get("salary_structure")
    ))
    ss_components = {}
    ss_abbr_map = {}
    if unique_ss:
        ss_details = frappe.db.sql(
            """
            SELECT parent, parentfield, salary_component, amount, formula, idx
            FROM `tabSalary Detail`
            WHERE parent IN %(structures)s
            ORDER BY parent, parentfield, idx
            """,
            {"structures": unique_ss},
            as_dict=True,
        )
        for d in ss_details:
            ss_components.setdefault(d.parent, []).append(d)

        # Fetch abbreviations for all salary components
        all_comp_names = list(set(d.salary_component for comps in ss_components.values() for d in comps))
        if all_comp_names:
            comps_meta = frappe.get_all("Salary Component",
                filters={"name": ["in", all_comp_names]},
                fields=["name", "salary_component_abbr"]
            )
            for cm in comps_meta:
                ss_abbr_map[cm.name] = cm.salary_component_abbr or cm.name.upper()[:10]

    def _eval_formula(formula, base_vals):
        """Simple formula evaluator for salary components.
        Supports: BS, BA, VA, basic, etc. as variable names + basic math."""
        if not formula:
            return 0
        import re as _re
        expr = formula.strip()
        # Map common variable names to values
        var_map = {k.upper(): v for k, v in base_vals.items()}
        # Replace variable names (case-insensitive) with values
        def _replace_var(m):
            name = m.group(0).upper()
            return str(var_map.get(name, 0))
        expr = _re.sub(r'[A-Za-z_]+', _replace_var, expr)
        try:
            return flt(eval(expr, {"__builtins__": {}}, {}))
        except Exception:
            return 0

    for emp in employees_raw:
        ssa = ssa_map.get(emp.name, {})
        ss_name = ssa.get("salary_structure")
        base = flt(ssa.get("base", 0))
        if not ss_name or ss_name not in ss_components:
            continue

        # Build variable context using actual abbreviations from Salary Component
        comp_vals = {
            "BS": flt(ssa.get("custom_basic_salary", 0)),
            "BA": flt(ssa.get("custom_base_allowance", 0)),
            "VA": flt(ssa.get("custom_vehicle_allowance", 0)),
            "basic": flt(ssa.get("custom_basic_salary", 0)),
            "base": flt(ssa.get("base", 0)),
        }
        for comp in ss_components[ss_name]:
            comp_name = comp.salary_component
            abbr = ss_abbr_map.get(comp_name, comp_name.upper()[:10])
            if comp.formula:
                amt = _eval_formula(comp.formula, comp_vals)
            else:
                amt = flt(comp.amount)
            comp_vals[abbr] = amt
            comp_vals[comp_name.upper()] = amt
            comp_vals[comp_name] = amt

            is_earning = comp.parentfield == "earnings"
            entry = {
                "employee": emp.name,
                "employee_name": emp.employee_name,
                "salary_component": comp_name,
                "amount": amt,
                "source_type": "Salary Structure",
                "reference_name": "",
            }
            if is_earning:
                earnings_list.append(entry)
                addl_earn_map[emp.name] = flt(addl_earn_map.get(emp.name, 0)) + amt
            else:
                deductions_list.append(entry)
                addl_ded_map[emp.name] = flt(addl_ded_map.get(emp.name, 0)) + amt

    # ── 5b. Additional Salary records (batch) ──
    for row in addl_records:
        is_earning = (row.type == "Earning") if row.type else (row.component_type == "Earning")
        entry = {
            "employee": row.employee,
            "employee_name": row.employee_name,
            "salary_component": row.salary_component,
            "amount": flt(row.amount),
            "additional_salary": row.name,
        }

        if is_earning:
            earnings_list.append(entry)
            addl_earn_map[row.employee] = flt(addl_earn_map.get(row.employee, 0)) + flt(row.amount)
        else:
            entry["source_type"] = "Additional Salary"
            entry["reference_name"] = row.name
            deductions_list.append(entry)
            addl_ded_map[row.employee] = flt(addl_ded_map.get(row.employee, 0)) + flt(row.amount)

    # ── 6. Loan Repayments (batch, graceful fallback) ──
    loan_map = {}
    try:
        if frappe.db.table_exists("tabLoan"):
            loan_records = frappe.db.sql(
                """
                SELECT
                    l.applicant as employee,
                    SUM(rs.total_payment) as total_due
                FROM `tabRepayment Schedule` rs
                INNER JOIN `tabLoan` l ON l.name = rs.parent
                WHERE l.applicant_type = 'Employee'
                    AND l.applicant IN %(employees)s
                    AND l.docstatus = 1
                    AND l.status IN ('Disbursed', 'Partially Paid')
                    AND rs.payment_date BETWEEN %(start)s AND %(end)s
                    AND rs.is_accrued = 0
                GROUP BY l.applicant
                """,
                {"employees": emp_names, "start": start_date, "end": end_date},
                as_dict=True,
            )
            for row in loan_records:
                loan_map[row.employee] = flt(row.total_due)
                deductions_list.append({
                    "employee": row.employee,
                    "employee_name": "",
                    "salary_component": "",
                    "amount": flt(row.total_due),
                    "source_type": "Loan Repayment",
                    "reference_name": "",
                })
    except Exception:
        pass

    # ── 7. Working days (cap at today for current month) ──
    from frappe.utils import today as _today
    effective_end = min(getdate(end_date), getdate(_today()))
    total_days = (effective_end - getdate(start_date)).days + 1
    holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
    if holiday_list:
        holidays = frappe.db.count(
            "Holiday",
            filters={
                "parent": holiday_list,
                "holiday_date": ["between", [start_date, effective_end]],
            },
        )
        total_working_days = total_days - holidays
    else:
        total_working_days = total_days

    # ── 8. Default OT rate ──
    default_ot_rate = flt(
        frappe.db.get_single_value("SLHRM Settings", "default_ot_rate") or 0
    )

    # ── 9. Build employee result list ──
    employees_result = []
    sum_ot = 0
    sum_gross = 0
    sum_ded = 0
    sum_net = 0

    for emp in employees_raw:
        ssa = ssa_map.get(emp.name, {})
        att = att_map.get(emp.name, {"present": 0, "leave": 0})
        ot_hours = flt(ot_map.get(emp.name, 0))
        addl_earn = flt(addl_earn_map.get(emp.name, 0))
        addl_ded = flt(addl_ded_map.get(emp.name, 0))
        loan_amt = flt(loan_map.get(emp.name, 0))
        base = flt(ssa.get("base", 0))

        present = flt(att["present"])
        leave = flt(att["leave"])
        absent = max(0, flt(total_working_days) - present - leave)

        ot_rate = default_ot_rate
        ot_amount = flt(ot_hours) * flt(ot_rate)

        total_earning = base + ot_amount + addl_earn
        total_deduction = addl_ded + loan_amt
        net_pay = total_earning - total_deduction

        sum_ot += ot_amount
        sum_gross += total_earning
        sum_ded += total_deduction
        sum_net += net_pay

        employees_result.append({
            "employee": emp.name,
            "employee_name": emp.employee_name,
            "designation": emp.designation or "",
            "salary_structure": ssa.get("salary_structure", ""),
            "base": base,
            "custom_basic_salary": flt(ssa.get("custom_basic_salary", 0)),
            "custom_base_allowance": flt(ssa.get("custom_base_allowance", 0)),
            "custom_vehicle_allowance": flt(ssa.get("custom_vehicle_allowance", 0)),
            "total_working_days": total_working_days,
            "present_days": present,
            "absent_days": absent,
            "leave_days": leave,
            "ot_hours": ot_hours,
            "ot_rate": ot_rate,
            "ot_amount": ot_amount,
            "additional_earning_total": addl_earn,
            "additional_deduction_total": addl_ded,
            "loan_deduction": loan_amt,
            "total_earning": total_earning,
            "total_deduction": total_deduction,
            "net_pay": net_pay,
        })

    emp_name_map = {e.name: e.employee_name for e in employees_raw}
    for d in deductions_list:
        if not d.get("employee_name"):
            d["employee_name"] = emp_name_map.get(d["employee"], "")

    no_att = [e.employee_name for e in employees_raw if e.name not in att_map]
    if no_att:
        warnings.append(
            f"{len(no_att)} employee(s) have no attendance records for this period: "
            + ", ".join(no_att[:5])
            + ("..." if len(no_att) > 5 else "")
        )

    # ── 10. Build salary component columns data ──
    all_components = []
    comp_set = set()
    for emp in employees_raw:
        ssa = ssa_map.get(emp.name, {})
        ss_name = ssa.get("salary_structure")
        if ss_name and ss_name in ss_components:
            for comp in ss_components[ss_name]:
                if comp.salary_component not in comp_set:
                    comp_set.add(comp.salary_component)
                    all_components.append({
                        "name": comp.salary_component,
                        "type": comp.parentfield,
                        "abbr": ss_abbr_map.get(comp.salary_component, comp.salary_component.upper()[:10]),
                    })

    # Build per-employee component amounts
    comp_amounts = {}
    for emp in employees_raw:
        ssa = ssa_map.get(emp.name, {})
        ss_name = ssa.get("salary_structure")
        base = flt(ssa.get("base", 0))
        emp_comps = {}
        if ss_name and ss_name in ss_components:
            comp_vals = {"BS": base, "basic": base, "base": base}
            for comp in ss_components[ss_name]:
                comp_name = comp.salary_component
                abbr = ss_abbr_map.get(comp_name, comp_name.upper()[:10])
                if comp.formula:
                    amt = _eval_formula(comp.formula, comp_vals)
                else:
                    amt = flt(comp.amount)
                comp_vals[abbr] = amt
                comp_vals[comp_name.upper()] = amt
                comp_vals[comp_name] = amt
                emp_comps[comp_name] = amt
        comp_amounts[emp.name] = emp_comps

    return {
        "employees": employees_result,
        "earnings": earnings_list,
        "deductions": deductions_list,
        "salary_components": all_components,
        "component_amounts": comp_amounts,
        "summary": {
            "total_employees": len(employees_result),
            "total_ot_amount": sum_ot,
            "total_gross_pay": sum_gross,
            "total_deductions": sum_ded,
            "total_net_pay": sum_net,
            "total_working_days": total_working_days,
        },
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════
# AUTO-CREATE USER FROM EMPLOYEE
# ═══════════════════════════════════════════════════════════════


def create_employee_user(doc, method=None):
    """
    Auto-create a Frappe User when an Employee is created.
    Called via doc_events -> Employee -> after_insert.

    - Skips if employee already has user_id
    - Skips if no company_email or personal_email
    - Creates User with default password "Abc@12345"
    - Assigns "Employee" role only
    - Sets slhrm_must_change_password = 1 (forces password change on first PWA login)
    - Links user_id on Employee
    """
    if doc.user_id:
        return

    email = doc.company_email or doc.personal_email
    if not email:
        frappe.log_error(
            title="SLHRM: No email for User creation",
            message=f"Employee {doc.name} ({doc.employee_name}) has no company_email "
                    f"or personal_email. User account was NOT created.",
        )
        frappe.msgprint(
            _("No email found for {0}. User account was not created. "
              "Set Company Email or Personal Email and save again to create login.").format(
                doc.employee_name
            ),
            indicator="orange",
            alert=True,
        )
        return

    if frappe.db.exists("User", email):
        doc.db_set("user_id", email)
        frappe.msgprint(
            _("User {0} already exists. Linked to employee.").format(email),
            indicator="blue",
            alert=True,
        )
        return

    try:
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = doc.first_name or doc.employee_name
        user.last_name = doc.last_name or ""
        user.enabled = 1
        user.user_type = "System User"
        user.new_password = "Abc@12345"
        user.send_welcome_email = 0

        user.append("roles", {"role": "Employee"})

        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        frappe.db.set_value("User", user.name, "slhrm_must_change_password", 1)

        doc.db_set("user_id", user.name)

        frappe.msgprint(
            _("User {0} created for {1}. Default password: Abc@12345").format(
                email, doc.employee_name
            ),
            indicator="green",
            alert=True,
        )

    except Exception as e:
        frappe.log_error(
            title="SLHRM: User creation failed",
            message=f"Failed to create User for Employee {doc.name} ({email}): {str(e)}",
        )
        frappe.msgprint(
            _("Failed to create User for {0}: {1}").format(doc.employee_name, str(e)),
            indicator="red",
            alert=True,
        )


@frappe.whitelist()
def check_must_change_password():
    """
    Check if current user must change password on first login.
    Called by PWA after successful login.
    """
    if frappe.session.user in ("Administrator", "Guest"):
        return False

    must_change = frappe.db.get_value(
        "User", frappe.session.user, "slhrm_must_change_password"
    )
    return bool(must_change)


@frappe.whitelist()
def clear_must_change_password():
    """
    Clear the must-change-password flag after successful password change.
    Called by PWA ChangePassword view after update_password succeeds.
    """
    if frappe.session.user in ("Administrator", "Guest"):
        return

    frappe.db.set_value(
        "User", frappe.session.user, "slhrm_must_change_password", 0
    )
    frappe.db.commit()
