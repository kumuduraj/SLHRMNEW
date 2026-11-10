# slhrm/api.py
import frappe
from frappe import _
from frappe.utils import cint, cstr, flt
from datetime import datetime, timedelta
import hmac
import os
import json


# ═══════════════════════════════════════════════════════════════
# PWA SERVICE WORKER
# ═══════════════════════════════════════════════════════════════

@frappe.whitelist(allow_guest=True, methods=["GET"])
def pwa_sw():
    """Serve the built PWA service worker so it can control the /slhrm/ scope.

    The page itself is rendered by slhrm/www/slhrm.py; static assets are served
    from /assets/slhrm/frontend/. A SW served from /assets/... could only control
    that path, so it is served here with Service-Worker-Allowed: /slhrm/.
    """
    from werkzeug.wrappers import Response

    sw_path = frappe.get_app_path("slhrm", "public", "frontend", "sw.js")
    if not os.path.exists(sw_path):
        raise frappe.DoesNotExistError(_("PWA service worker not built"))

    with open(sw_path, "rb") as f:
        content = f.read()

    response = Response(content, mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/slhrm/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# ═══════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════

def _validate_device_api_key(header_only=False):
    """Fail closed: raise 403 unless the device API is enabled and the key matches.
    header_only: accept the key only from the X-Device-Key header (never from the URL / form,
    which can end up in access logs)."""
    settings = frappe.get_cached_doc("SLHRM Settings")
    if not settings.device_api_enabled:
        frappe.throw(_("Device API disabled"), frappe.PermissionError)

    stored_key = settings.get_password("device_api_key", raise_exception=False)
    if not stored_key:
        frappe.throw(_("Device API key not configured"), frappe.PermissionError)

    provided_key = frappe.request.headers.get("X-Device-Key") if frappe.request else None
    if not provided_key and not header_only:
        provided_key = frappe.form_dict.get("api_key")
    if not provided_key or not hmac.compare_digest(
        cstr(provided_key).encode(), cstr(stored_key).encode()
    ):
        frappe.throw(_("Invalid or missing device API key"), frappe.PermissionError)


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
    - Biometric Device ID (field: slhrm_biometric_device_id custom field)
    """
    _validate_device_api_key()

    if not device_id or not employee_id or not punch_time:
        frappe.throw(_("device_id, employee_id, and punch_time are required."))

    # Try lookup by ERPNext Employee ID first, then employee_number, then slhrm_biometric_device_id
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
            {"slhrm_biometric_device_id": employee_id, "status": "Active"},
            ["name", "employee_name", "employee_number"],
            as_dict=True,
        )
    if not employee:
        frappe.throw(_("Employee {0} not found or inactive.").format(employee_id))

    # Populate slhrm_biometric_device_name on Employee if not set
    if device_id:
        frappe.db.set_value("Employee", employee.name, "slhrm_biometric_device_name", device_id, update_modified=False)

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
            # Try lookup by ERPNext Employee ID first, then employee_number, then slhrm_biometric_device_id
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
                    {"slhrm_biometric_device_id": p.get("employee_id"), "status": "Active"},
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

            # Populate slhrm_biometric_device_name on Employee if not set
            if device_id:
                frappe.db.set_value("Employee", employee.name, "slhrm_biometric_device_name", device_id, update_modified=False)

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


@frappe.whitelist(allow_guest=True, methods=["POST"])
def device_ingest(serial, punches, agent=None):
    """SLHRM agent → raw device records (slhrm.biometric.ingest).

    POST /api/method/slhrm.api.device_ingest     Header: X-Device-Key
    Body (JSON): serial, punches [{device_user_id, timestamp "YYYY-MM-DD HH:MM:SS" device time,
                 punch_state, verify_mode}], agent
    Returns per-record results: inserted / duplicate / unknown_employee (stored) / error.
    """
    _validate_device_api_key(header_only=True)
    from slhrm.biometric import ingest

    return ingest(serial, punches, agent)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def device_users(serial, users, agent=None):
    """SLHRM agent → device user list (user_id, name, privilege; never PINs / cards / templates).
    Header: X-Device-Key."""
    _validate_device_api_key(header_only=True)
    from slhrm.biometric import sync_users

    return sync_users(serial, users)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def device_heartbeat(serial, info, agent=None):
    """SLHRM agent → device health (slhrm.biometric.heartbeat). Header: X-Device-Key."""
    _validate_device_api_key(header_only=True)
    from slhrm.biometric import heartbeat

    return heartbeat(serial, info, agent)


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

    Punches: Biometric Punch Log for everyone + Employee Checkin for employees with
    slhrm_allow_app_checkin. OT via slhrm.overtime (through slhrm.attendance).

    Returns:
        employees:  active employees in the branch (excluding already-marked)
        punch_refs: punches used per employee (punch_doctype, punch_log, punch_time, used_as)
        matched:    {employee: in/out, worked, shift_hours, ot_eligible, calc_normal_ot,
                     calc_double_ot, is_holiday, punch_source, punch_count, warning}
    """
    from slhrm.attendance import compute_for_employees

    frappe.has_permission("Attendance Marker", "create", throw=True)
    if not date or not branch:
        frappe.throw(_("Date and Branch are required."))

    date_str = str(date)

    # ── Already-marked employees (single SQL, not N+1) ──
    marked_employees = set(
        frappe.db.sql_list(
            """
            SELECT DISTINCT amd.employee
            FROM `tabAttendance Marker Detail` amd
            INNER JOIN `tabAttendance Marker` am ON am.name = amd.parent
            WHERE am.date = %s AND am.docstatus = 1
            """,
            (date_str,),
        )
    )

    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active", "branch": branch},
        fields=[
            "name", "employee_name", "department", "designation", "company", "default_shift",
            "slhrm_ot_eligible", "slhrm_allow_app_checkin",
        ],
        order_by="employee_name asc",
    )
    employees = [e for e in employees if e.name not in marked_employees]
    if not employees:
        return {"employees": [], "punch_refs": [], "matched": {}}

    computed = compute_for_employees(
        employees, date_str, {e.name: e.default_shift for e in employees}, device_id=device_id or None
    )

    matched, punch_refs = {}, []
    for emp in employees:
        day = computed[emp.name]
        punch_refs.extend(day.pop("refs"))
        matched[emp.name] = day

    return {"employees": employees, "punch_refs": punch_refs, "matched": matched}


@frappe.whitelist()
def recalc_attendance_row(employee, date, shift):
    """Recalculate one Attendance Marker row when the user changes its shift."""
    from slhrm.attendance import compute_for_employees

    frappe.has_permission("Attendance Marker", "create", throw=True)
    if not employee or not date:
        frappe.throw(_("Employee and Date are required."))

    emp = frappe.db.get_value(
        "Employee", employee, ["name", "slhrm_ot_eligible", "slhrm_allow_app_checkin"], as_dict=True
    )
    if not emp:
        frappe.throw(_("Employee {0} not found.").format(employee))

    return compute_for_employees([emp], str(date), {emp.name: shift})[emp.name]


@frappe.whitelist()
def marker_previous_day(branch, date, company=None):
    """Previous day's Attendance Marker status for the form banner (read-only)."""
    from slhrm.attendance import previous_day_marker

    frappe.has_permission("Attendance Marker", "read", throw=True)
    if not branch or not date:
        return None
    return previous_day_marker(branch, company, str(date))


@frappe.whitelist()
def calc_attendance_times(employee, date, shift=None, in_time=None, out_time=None, out_next_day=0):
    """Attendance Marker row edited by hand (no punches needed): worked hours + calculated OT for
    IN = date + in_time, OUT = (date + 1 if out_next_day) + out_time. OUT before IN on the same day
    is impossible, so out_next_day is returned ticked then. Nothing is written."""
    from slhrm.attendance import MAX_PLAUSIBLE_HOURS, combine, get_holiday_info, get_settings, get_shift_info, out_is_next_day, span_hours
    from slhrm.overtime import calculate_ot_hours

    frappe.has_permission("Attendance Marker", "create", throw=True)
    if not employee or not date:
        frappe.throw(_("Employee and Date are required."))
    emp = frappe.db.get_value("Employee", employee, ["name", "slhrm_ot_eligible"], as_dict=True)
    if not emp:
        frappe.throw(_("Employee {0} not found.").format(employee))
    in_time, out_time = (in_time or None), (out_time or None)
    nxt = 1 if out_time and (cint(out_next_day) or out_is_next_day(in_time, out_time)) else 0
    settings = get_settings()
    info = get_shift_info(shift, str(date), settings)
    worked = span_hours(date, in_time, out_time, nxt)
    ot = calculate_ot_hours({
        "employee": emp.name, "date": str(date), "ot_eligible": cint(emp.slhrm_ot_eligible), "shift": shift,
        "shift_hours": info.hours, "in_time": combine(date, in_time), "out_time": combine(date, out_time, nxt),
        "worked_hours": worked, "is_holiday": None, "holiday_type": get_holiday_info(emp.name, str(date))[1],
    }, settings)
    return {
        "out_next_day": nxt, "worked_hours": worked, "shift_hours": info.hours,
        "ot_eligible": 1 if cint(emp.slhrm_ot_eligible) else 0,
        "calc_normal_ot": ot["normal"], "calc_double_ot": ot["double"],
        "warning": _("More than {0} worked hours — check IN / OUT and the OUT next day box.").format(MAX_PLAUSIBLE_HOURS)
        if worked > MAX_PLAUSIBLE_HOURS else "",
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

# ── Payroll Worksheet data (HRMS Salary Slip preview + OT; see slhrm/payroll_pay.py) ──

PAYROLL_BACKGROUND_THRESHOLD = 100  # employees; above this load/refresh run as a background job
PAYROLL_JOB_CACHE_KEY = "slhrm:payroll_job:{}"


def _payroll_period(payroll_month, payroll_year):
    from frappe.utils import get_first_day, get_last_day

    year, month = cint(payroll_year), cint(payroll_month)
    if not year or not month:
        frappe.throw(_("Month and Year are required."))
    return get_first_day(f"{year}-{month:02d}-01"), get_last_day(f"{year}-{month:02d}-01")


def _employee_details(names):
    rows = frappe.get_all(
        "Employee", filters={"name": ["in", list(names)]},
        fields=["name", "employee_name", "designation", "slhrm_ot_eligible"],
    )
    by_name = {r.name: r for r in rows}
    return [by_name[n] for n in names if n in by_name]


def _payroll_payload(employees, company, start_date, end_date, ot_inputs=None, progress=None):
    from slhrm.payroll_pay import build_rows, summarize

    rows, lines = build_rows(employees, company, start_date, end_date, ot_inputs=ot_inputs, progress=progress)
    components, seen = [], set()
    for kind, table in (("earnings", lines["earnings"]), ("deductions", lines["deductions"])):
        for line in table:
            if line["salary_component"] not in seen:
                seen.add(line["salary_component"])
                components.append({"name": line["salary_component"], "type": kind})
    errors = [f"{r['employee_name'] or r['employee']}: {r['row_error']}" for r in rows if r["row_error"]]
    warnings = []
    if errors:
        warnings.append(
            _("{0} employee(s) could not be calculated (fix them before submitting):").format(len(errors))
            + "<br>" + "<br>".join(frappe.utils.escape_html(e) for e in errors[:20])
            + ("<br>…" if len(errors) > 20 else "")
        )
    return {
        "employees": rows, "earnings": lines["earnings"], "deductions": lines["deductions"],
        "salary_components": components, "summary": summarize(rows), "warnings": warnings,
        "start_date": str(start_date), "end_date": str(end_date),
    }


def _enqueue_payroll_job(employees, company, start_date, end_date, ot_inputs):
    key = frappe.generate_hash(length=16)
    frappe.enqueue(
        "slhrm.api.run_payroll_job", queue="long", timeout=3600, key=key, employees=employees,
        company=company, start_date=str(start_date), end_date=str(end_date), ot_inputs=ot_inputs,
        owner=frappe.session.user,
    )
    return {"job": key, "total": len(employees)}


def run_payroll_job(key, employees, company, start_date, end_date, ot_inputs, owner):
    """Background job (>PAYROLL_BACKGROUND_THRESHOLD employees): builds previews, stores the
    payload in cache for the owner, publishes progress/completion over realtime."""
    def progress(done, total):
        if done == total or done % 5 == 0:
            frappe.publish_realtime("slhrm_payroll_progress", {"key": key, "done": done, "total": total}, user=owner)

    try:
        payload = _payroll_payload(employees, company, start_date, end_date, ot_inputs=ot_inputs, progress=progress)
        frappe.cache.set_value(PAYROLL_JOB_CACHE_KEY.format(key), {"owner": owner, "payload": payload},
                               expires_in_sec=3600)
        frappe.publish_realtime("slhrm_payroll_progress", {"key": key, "status": "done"}, user=owner)
    except Exception:
        frappe.log_error(title="SLHRM: Payroll Worksheet background load failed")
        frappe.publish_realtime("slhrm_payroll_progress", {"key": key, "status": "failed"}, user=owner)


@frappe.whitelist()
def get_payroll_job_result(key):
    frappe.has_permission("Payroll Worksheet", "read", throw=True)
    data = frappe.cache.get_value(PAYROLL_JOB_CACHE_KEY.format(key))
    if not data or data.get("owner") != frappe.session.user:
        frappe.throw(_("Payroll data is not ready or has expired. Load it again."))
    return data["payload"]


@frappe.whitelist()
def load_payroll_data(branch, company, payroll_month, payroll_year):
    """Payroll Worksheet loader: HRMS Salary Slip preview (in memory, never saved) per active
    employee in the branch + OT from submitted Attendance Markers. >100 employees -> background
    job ({"job": key, "total": n}; result via get_payroll_job_result)."""
    frappe.has_permission("Payroll Worksheet", "create", throw=True)
    if not branch or not company:
        frappe.throw(_("Branch and Company are required."))
    start_date, end_date = _payroll_period(payroll_month, payroll_year)

    employees = frappe.db.get_all(
        "Employee", filters={"company": company, "branch": branch, "status": "Active"},
        fields=["name", "employee_name", "designation", "slhrm_ot_eligible"], order_by="employee_name asc",
    )
    if not employees:
        return {"employees": [], "earnings": [], "deductions": [], "salary_components": [],
                "summary": {}, "warnings": [_("No active employees found in this branch.")]}
    if len(employees) > PAYROLL_BACKGROUND_THRESHOLD:
        return _enqueue_payroll_job(employees, company, start_date, end_date, None)
    return _payroll_payload(employees, company, start_date, end_date)


@frappe.whitelist()
def refresh_salary_data(company, payroll_month, payroll_year, rows):
    """"Refresh Salary Data": rebuild the HRMS previews for the given worksheet rows, keeping
    their OT hours/rates. rows: JSON [{employee, normal_ot_hours, normal_ot_rate,
    double_ot_hours, double_ot_rate}]. Eligibility is re-read from Employee."""
    frappe.has_permission("Payroll Worksheet", "write", throw=True)
    start_date, end_date = _payroll_period(payroll_month, payroll_year)
    rows = json.loads(rows) if isinstance(rows, str) else rows or []
    ot_inputs = {r["employee"]: {f: flt(r.get(f)) for f in ("normal_ot_hours", "normal_ot_rate",
                                                             "double_ot_hours", "double_ot_rate")}
                 for r in rows if r.get("employee")}
    employees = _employee_details(list(ot_inputs))
    if len(employees) > PAYROLL_BACKGROUND_THRESHOLD:
        return _enqueue_payroll_job(employees, company, start_date, end_date, ot_inputs)
    return _payroll_payload(employees, company, start_date, end_date, ot_inputs=ot_inputs)


@frappe.whitelist()
def download_worksheet_xlsx(name):
    """"Download Excel": the worksheet table (same columns + totals as the form / print)."""
    from frappe.utils.xlsxutils import make_xlsx

    from slhrm.payroll_table import build_table, sheet_rows

    doc = frappe.get_doc("Payroll Worksheet", name)
    doc.check_permission("read")
    title = f"Payroll Worksheet {doc.name} - {doc.branch} - {doc.month_name} {doc.payroll_year}"
    xlsx = make_xlsx(sheet_rows(title, build_table(doc.employees)), "Payroll Worksheet")
    frappe.response["filename"] = f"{doc.name}.xlsx"
    frappe.response["filecontent"] = xlsx.getvalue()
    frappe.response["type"] = "binary"


@frappe.whitelist()
def calc_worksheet_row(employee, structure_gross=0, structure_deduction=0, loan_deduction=0,
                       normal_ot_hours=0, double_ot_hours=0, normal_ot_rate=0, double_ot_rate=0,
                       apit_taxable_base=None, apit_preview=0, start_date=None):
    """OT + totals for one row (inline OT editor). Does NOT rebuild the salary preview.
    With apit_taxable_base (stored row value) the row's APIT is recomputed including the OT."""
    from slhrm.overtime import calculate_ot_amounts
    from slhrm.payroll_ot import get_ot_eligibility
    from slhrm.payroll_pay import compose_pay
    from slhrm.statutory import apit_component, worksheet_apit

    frappe.has_permission("Payroll Worksheet", "read", throw=True)
    eligible = cint(get_ot_eligibility([employee]).get(employee))
    if not eligible:
        normal_ot_hours = double_ot_hours = normal_ot_rate = double_ot_rate = 0
    amounts = calculate_ot_amounts(
        normal_ot_hours, double_ot_hours, {"normal_rate": normal_ot_rate, "double_rate": double_ot_rate}
    )
    return {
        "ot_eligible": eligible,
        "normal_ot_amount": amounts["normal"],
        "double_ot_amount": amounts["double"],
        "ot_amount": flt(amounts["normal"] + amounts["double"], 2),
        **compose_pay(structure_gross, structure_deduction, amounts["normal"], amounts["double"], loan_deduction,
                      apit_preview, (worksheet_apit(apit_taxable_base, amounts["normal"], amounts["double"], employee, start_date)
                                     if apit_taxable_base not in (None, "") and start_date and apit_component() else None)),
    }


# ═══════════════════════════════════════════════════════════════
# FORCED PASSWORD CHANGE (user creation + enforcement: slhrm/user_setup.py)
# ═══════════════════════════════════════════════════════════════


@frappe.whitelist()
def check_must_change_password():
    """True while the session user must change the password (PWA routes to its change view)."""
    from slhrm.user_setup import must_change_password

    return must_change_password()


@frappe.whitelist()
def clear_must_change_password():
    """Called by the PWA after update_password. Does NOT clear on request: the requirement ends only
    when Frappe recorded a real password change (last_password_reset_date). Returns the new state."""
    from slhrm.user_setup import _forget, must_change_password

    _forget(frappe.session.user)
    return must_change_password()


@frappe.whitelist()
def get_app_permissions():
    """What the SLHRM app may show the session user (server is the source of truth).

    app_checkin: Employee.slhrm_allow_app_checkin and HR Settings
                 allow_employee_checkin_from_mobile_app are both on
    ot_eligible: Employee.slhrm_ot_eligible
    """
    from slhrm.overrides.employee_checkin import app_checkin_allowed, get_session_employee

    emp = get_session_employee()
    return {
        "app_checkin": app_checkin_allowed(emp),
        "ot_eligible": bool(emp and cint(emp.slhrm_ot_eligible)),
    }


@frappe.whitelist()
def get_my_holidays():
    """Holidays (not weekly offs) of the session user's own active Employee, for the PWA.

    HRMS's hrms.api.get_holidays_for_employee requires read permission on Holiday List, which the
    Employee role does not have. The list is resolved by ERPNext/HRMS's own
    get_holiday_list_for_employee; only the user's own employee is ever served (no parameter).
    """
    from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
    from frappe.utils import strip_html
    from slhrm.overrides.employee_checkin import get_session_employee

    emp = get_session_employee()
    if not emp:
        return []
    holiday_list = get_holiday_list_for_employee(emp.name, raise_exception=False)
    if not holiday_list:
        return []
    holidays = frappe.get_all(
        "Holiday",
        filters={"parenttype": "Holiday List", "parent": holiday_list, "weekly_off": 0},
        fields=["name", "holiday_date", "description"],
        order_by="holiday_date asc",
    )
    for h in holidays:
        h["description"] = strip_html(h["description"] or "").strip()
    return holidays
