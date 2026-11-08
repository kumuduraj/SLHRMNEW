# slhrm/api.py
import frappe
from frappe import _
from frappe.utils import cint, cstr
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

def _validate_device_api_key():
    """Fail closed: raise 403 unless the device API is enabled and the key matches."""
    settings = frappe.get_cached_doc("SLHRM Settings")
    if not settings.device_api_enabled:
        frappe.throw(_("Device API disabled"), frappe.PermissionError)

    stored_key = settings.get_password("device_api_key", raise_exception=False)
    if not stored_key:
        frappe.throw(_("Device API key not configured"), frappe.PermissionError)

    provided_key = (
        frappe.request.headers.get("X-Device-Key") if frappe.request else None
    ) or frappe.form_dict.get("api_key")
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
def calc_worksheet_row(employee, start_date, end_date, normal_ot_hours=0, double_ot_hours=0,
                       normal_ot_rate=0, double_ot_rate=0, loan_deduction=0):
    """Server-side totals for one Payroll Worksheet row (used by the inline editor; the JS does
    no math). OT via slhrm.overtime, pay via slhrm.payroll_pay.compose_pay. Eligibility is
    re-read from Employee."""
    from slhrm.overtime import calculate_ot_amounts
    from slhrm.payroll_ot import get_ot_eligibility
    from slhrm.payroll_pay import compose_pay, get_additional_salary, get_structure_amounts

    frappe.has_permission("Payroll Worksheet", "read", throw=True)
    eligible = cint(get_ot_eligibility([employee]).get(employee))
    if not eligible:
        normal_ot_hours = double_ot_hours = normal_ot_rate = double_ot_rate = 0
    amounts = calculate_ot_amounts(
        normal_ot_hours, double_ot_hours, {"normal_rate": normal_ot_rate, "double_rate": double_ot_rate}
    )
    structure = get_structure_amounts([employee], end_date)[0][employee]
    _rows, addl = get_additional_salary([employee], start_date, end_date)
    addl = addl.get(employee, {"earning": 0, "deduction": 0})
    ot_amount = flt(amounts["normal"] + amounts["double"], 2)
    pay = compose_pay(structure.structure_earning_total, structure.structure_deduction_total, ot_amount,
                      addl["earning"], addl["deduction"], loan_deduction)
    return {
        "ot_eligible": eligible,
        "normal_ot_amount": amounts["normal"],
        "double_ot_amount": amounts["double"],
        "ot_amount": ot_amount,
        "structure_earning_total": structure.structure_earning_total,
        "structure_deduction_total": structure.structure_deduction_total,
        "additional_earning_total": addl["earning"],
        "additional_deduction_total": addl["deduction"],
        **pay,
    }


@frappe.whitelist()
def load_payroll_data(branch, company, payroll_month, payroll_year):
    """
    Main data-loading endpoint for the Payroll Worksheet form.

    Pay rule (slhrm.payroll_pay): gross = structure earnings + OT + Additional Salary earnings;
    deductions = structure deductions + Additional Salary deductions + loans. `base` is shown
    for reference only (the structure's Basic formula already carries it).

    Returns:
        employees: per-employee salary, attendance, OT and pay totals
        earnings / deductions: structure + Additional Salary lines (child tables, display)
        salary_components: column list; component_amounts: {employee: {component: amount}}
        summary: totals; warnings: list of strings
    """
    from frappe.utils import getdate, get_first_day, get_last_day, today as _today

    from slhrm.overtime import calculate_ot_amounts, calculate_ot_rates
    from slhrm.payroll_ot import get_marker_ot_hours
    from slhrm.payroll_pay import compose_pay, get_additional_salary, get_structure_amounts

    frappe.has_permission("Payroll Worksheet", "create", throw=True)
    if not branch or not company or not payroll_month or not payroll_year:
        frappe.throw(_("Branch, Company, Month and Year are required."))

    year = cint(payroll_year)
    month = cint(payroll_month)
    start_date = get_first_day(f"{year}-{month:02d}-01")
    end_date = get_last_day(f"{year}-{month:02d}-01")

    # ── 1. Active employees in branch ──
    employees_raw = frappe.db.get_all(
        "Employee",
        filters={"company": company, "branch": branch, "status": "Active"},
        fields=["name", "employee_name", "designation", "slhrm_ot_eligible"],
        order_by="employee_name asc",
    )
    if not employees_raw:
        return {
            "employees": [], "earnings": [], "deductions": [], "salary_components": [],
            "component_amounts": {}, "summary": {},
            "warnings": ["No active employees found in this branch."],
        }
    emp_names = [e.name for e in employees_raw]
    emp_name_map = {e.name: e.employee_name for e in employees_raw}
    warnings = []

    # ── 2. Salary Structure components (formula-evaluated; display + structure totals) ──
    structures, all_components = get_structure_amounts(emp_names, end_date)
    count_with_ssa = sum(1 for s in structures.values() if s.salary_structure)

    # ── 3. Attendance summary (batch) ──
    att_map = {}
    for row in frappe.db.sql(
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
    ):
        a = att_map.setdefault(row.employee, {"present": 0, "leave": 0})
        if row.status == "Present":
            a["present"] += row.cnt
        elif row.status == "Half Day":
            a["present"] += row.cnt * 0.5
            a["leave"] += row.cnt * 0.5
        elif row.status == "On Leave":
            a["leave"] += row.cnt
        elif row.status == "Work From Home":
            a["present"] += row.cnt

    # ── 4. OT hours from submitted Attendance Markers (approved normal/double hours) ──
    ot_map = get_marker_ot_hours(emp_names, start_date, end_date)

    # ── 5. Additional Salary (submitted, period; excludes Payroll Worksheet OT records) ──
    addl_records, addl_totals = get_additional_salary(emp_names, start_date, end_date)

    # ── 6. Loan Repayments (batch, graceful fallback) ──
    loan_map = {}
    deductions_list = []
    try:
        if frappe.db.table_exists("Loan"):
            for row in frappe.db.sql(
                """
                SELECT l.applicant as employee, SUM(rs.total_payment) as total_due
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
            ):
                loan_map[row.employee] = flt(row.total_due)
                deductions_list.append({
                    "employee": row.employee, "employee_name": emp_name_map.get(row.employee, ""),
                    "salary_component": "", "amount": flt(row.total_due),
                    "source_type": "Loan Repayment", "reference_name": "",
                })
    except Exception:
        pass

    # ── 7. Working days (cap at today for current month) ──
    effective_end = min(getdate(end_date), getdate(_today()))
    total_days = (effective_end - getdate(start_date)).days + 1
    holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
    if holiday_list:
        holidays = frappe.db.count(
            "Holiday", filters={"parent": holiday_list, "holiday_date": ["between", [start_date, effective_end]]}
        )
        total_working_days = total_days - holidays
    else:
        total_working_days = total_days

    # ── 8. Child-table lines + component columns (display only) ──
    earnings_list = []
    comp_amounts = {}
    for emp in employees_raw:
        s = structures[emp.name]
        comp_amounts[emp.name] = {**s.earnings, **s.deductions}
        for comp, amt in s.earnings.items():
            earnings_list.append({"employee": emp.name, "employee_name": emp.employee_name,
                                  "salary_component": comp, "amount": amt,
                                  "source_type": "Salary Structure", "reference_name": ""})
        for comp, amt in s.deductions.items():
            deductions_list.append({"employee": emp.name, "employee_name": emp.employee_name,
                                    "salary_component": comp, "amount": amt,
                                    "source_type": "Salary Structure", "reference_name": ""})

    comp_set = {c["name"] for c in all_components}
    for row in addl_records:
        entry = {"employee": row.employee, "employee_name": row.employee_name or emp_name_map.get(row.employee, ""),
                 "salary_component": row.salary_component, "amount": flt(row.amount),
                 "additional_salary": row.name, "source_type": "Additional Salary", "reference_name": row.name}
        (earnings_list if row.is_earning else deductions_list).append(entry)
        amounts = comp_amounts.setdefault(row.employee, {})
        amounts[row.salary_component] = flt(amounts.get(row.salary_component, 0) + flt(row.amount), 2)
        if row.salary_component not in comp_set:
            comp_set.add(row.salary_component)
            all_components.append({"name": row.salary_component,
                                   "type": "earnings" if row.is_earning else "deductions",
                                   "abbr": row.salary_component.upper()[:10]})

    # ── 9. Employee rows (pay via slhrm.payroll_pay.compose_pay) ──
    ot_settings = frappe.get_cached_doc("SLHRM Settings")
    employees_result = []
    sums = dict(ot=0, normal=0, double=0, gross=0, ded=0, net=0)
    for emp in employees_raw:
        s = structures[emp.name]
        att = att_map.get(emp.name, {"present": 0, "leave": 0})
        present, leave = flt(att["present"]), flt(att["leave"])
        absent = max(0, flt(total_working_days) - present - leave)

        ot_eligible = cint(emp.slhrm_ot_eligible)
        hours = ot_map.get(emp.name, {}) if ot_eligible else {}
        normal_ot_hours, double_ot_hours = flt(hours.get("normal", 0)), flt(hours.get("double", 0))
        rates = calculate_ot_rates(emp.name, s.base, ot_settings)
        amounts = calculate_ot_amounts(normal_ot_hours, double_ot_hours, rates)
        ot_amount = flt(amounts["normal"] + amounts["double"], 2)

        addl = addl_totals.get(emp.name, {"earning": 0.0, "deduction": 0.0})
        loan_amt = flt(loan_map.get(emp.name, 0))
        pay = compose_pay(s.structure_earning_total, s.structure_deduction_total, ot_amount,
                          addl["earning"], addl["deduction"], loan_amt)

        sums["ot"] += ot_amount
        sums["normal"] += amounts["normal"]
        sums["double"] += amounts["double"]
        sums["gross"] += pay["total_earning"]
        sums["ded"] += pay["total_deduction"]
        sums["net"] += pay["net_pay"]

        employees_result.append({
            "employee": emp.name,
            "employee_name": emp.employee_name,
            "designation": emp.designation or "",
            "salary_structure": s.salary_structure,
            "base": s.base,
            "components": comp_amounts.get(emp.name, {}),
            "total_working_days": total_working_days,
            "present_days": present,
            "absent_days": absent,
            "leave_days": leave,
            "ot_eligible": ot_eligible,
            "normal_ot_hours": normal_ot_hours,
            "normal_ot_rate": rates["normal_rate"],
            "normal_ot_amount": amounts["normal"],
            "double_ot_hours": double_ot_hours,
            "double_ot_rate": rates["double_rate"],
            "double_ot_amount": amounts["double"],
            "ot_amount": ot_amount,
            "structure_earning_total": s.structure_earning_total,
            "structure_deduction_total": s.structure_deduction_total,
            "additional_earning_total": addl["earning"],
            "additional_deduction_total": addl["deduction"],
            "loan_deduction": loan_amt,
            **pay,
        })

    no_att = [e.employee_name for e in employees_raw if e.name not in att_map]
    if no_att:
        warnings.append(
            f"{len(no_att)} employee(s) have no attendance records for this period: "
            + ", ".join(no_att[:5])
            + ("..." if len(no_att) > 5 else "")
        )

    return {
        "employees": employees_result,
        "earnings": earnings_list,
        "deductions": deductions_list,
        "salary_components": all_components,
        "component_amounts": comp_amounts,
        "summary": {
            "total_employees": len(employees_result),
            "employees_with_ssa": count_with_ssa,
            "total_ot_amount": flt(sums["ot"], 2),
            "total_normal_ot_amount": flt(sums["normal"], 2),
            "total_double_ot_amount": flt(sums["double"], 2),
            "total_gross_pay": flt(sums["gross"], 2),
            "total_deductions": flt(sums["ded"], 2),
            "total_net_pay": flt(sums["net"], 2),
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
