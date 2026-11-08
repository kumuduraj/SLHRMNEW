# slhrm/demo/data.py
"""DEMO dataset for manual testing on a site WITHOUT real employees.

    bench --site <site> execute slhrm.demo.data.create    # build (idempotent; skips existing)
    bench --site <site> execute slhrm.demo.data.report    # counts, OT totals, logins
    bench --site <site> execute slhrm.demo.data.preview_payroll --kwargs '{"branch": "DEMO Factory"}'
    bench --site <site> execute slhrm.demo.data.remove    # delete everything it created

Not whitelisted (bench execute only). Every record is named/prefixed "DEMO". Every created doc is
recorded in a manifest: private File "slhrm_demo_manifest.json" (no schema change; updated after
each insert, so a partial run can still be removed). remove() also sweeps records that hooks and
manual testing create for DEMO employees (Attendance, Leave Ledger, SSA from packages, Contacts,
User Permissions, worksheets / slips / payroll entries in DEMO branches) and restores settings.

Holiday List Assignment is per DEMO employee: HRMS v16 has no branch-level assignment and a
company-level one would change the real company's holidays.
"""
import json
import os
import random
from datetime import date, datetime, timedelta

import frappe
from frappe.utils import flt, getdate, nowdate

MANIFEST = "slhrm_demo_manifest.json"
PASSWORD = "Demo@2026"
EMAIL = "demo-{}@demo.local"
OCT_START, OCT_END = date(2026, 10, 1), date(2026, 10, 31)
DRAFT_FROM = date(2026, 10, 29)  # markers from this date stay draft
HOLIDAYS = {date(2026, 10, 6): "DEMO Poya Day", date(2026, 10, 17): "DEMO Deepavali"}
BR_FACTORY, BR_OFFICE = "DEMO Factory", "DEMO Office"
SH_DAY, SH_NIGHT = "DEMO Day", "DEMO Night"
HOLIDAY_LIST = "DEMO 2026"
STRUCTURE = "DEMO Monthly"
LT_LWP, LT_CASUAL = "DEMO LWP", "DEMO Casual"
C = {
    "basic": ("DEMO Basic", "DBAS"), "bra": ("DEMO BRA", "DBRA"), "aa": ("DEMO Attendance Allowance", "DAA"),
    "not": ("DEMO Normal OT", "DNOT"), "dot": ("DEMO Double OT", "DDOT"),
    "epf": ("DEMO EPF Employee 8%", "DEPF"), "epf_er": ("DEMO EPF Employer 12%", "DEPFR"),
    "etf": ("DEMO ETF Employer 3%", "DETF"),
}
SLHRM_SETTINGS = {
    "normal_ot_component": C["not"][0], "double_ot_component": C["dot"][0],
    "default_ot_rate": 300, "default_double_ot_rate": 600, "overtime_threshold": 0.5,
}

# code, last name, branch, shift, ot_eligible, app_checkin, extra roles, base (None = no SSA), designation
EMPLOYEES = [
    ("E01", "Perera", BR_FACTORY, SH_DAY, 1, 0, ["HR Manager", "Leave Approver"], 150000, "DEMO Supervisor"),
    ("E02", "Silva", BR_FACTORY, SH_DAY, 1, 0, ["HR User"], 120000, "DEMO Supervisor"),
    ("E03", "Fernando", BR_FACTORY, SH_DAY, 1, 0, [], 65000, "DEMO Operator"),
    ("E04", "Jayasinghe", BR_FACTORY, SH_DAY, 1, 0, [], 55000, "DEMO Operator"),
    ("E05", "Bandara", BR_FACTORY, SH_NIGHT, 1, 0, [], 70000, "DEMO Operator"),
    ("E06", "Kumara", BR_FACTORY, SH_NIGHT, 1, 0, [], 68000, "DEMO Operator"),
    ("E07", "Wijesinghe", BR_FACTORY, SH_DAY, 0, 0, [], 45000, "DEMO Operator"),
    ("E08", "Rathnayake", BR_OFFICE, SH_DAY, 1, 1, [], 95000, "DEMO Clerk"),
    ("E09", "Gunawardena", BR_OFFICE, SH_DAY, 1, 1, [], 85000, "DEMO Clerk"),
    ("E10", "Dissanayake", BR_OFFICE, SH_DAY, 0, 1, [], 75000, "DEMO Clerk"),
    ("E11", "Herath", BR_OFFICE, SH_DAY, 1, 0, [], 110000, "DEMO Clerk"),  # Employee Salary Package
    ("E12", "Senanayake", BR_FACTORY, SH_DAY, 1, 0, [], None, "DEMO Operator"),  # no SSA -> row error
]
APP_USERS = {"E08", "E09", "E10"}
HOLIDAY_WORKERS = {"E01", "E03", "E05"}
ABSENT = {("E04", date(2026, 10, 14)), ("E04", date(2026, 10, 22))}
LWP_DAYS = ("E03", date(2026, 10, 20), date(2026, 10, 21))
CASUAL_DAY = ("E06", date(2026, 10, 27))
SINGLE_PUNCH = ("E02", date(2026, 10, 9))
NOV_EMPLOYEES = {"E01", "E02", "E05", "E08"}
ESP_EMPLOYEE, ESP_ALLOWANCE = "E11", 4000


# ── manifest ────────────────────────────────────────────────────


class Manifest:
    def __init__(self):
        self.path = frappe.get_site_path("private", "files", MANIFEST)
        self.data = {"created": [], "settings_before": {}, "employees": {}}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    def add(self, doctype, name):
        if [doctype, name] not in self.data["created"]:
            self.data["created"].append([doctype, name])
        self.save()

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=1, default=str)
        if not frappe.db.exists("File", {"file_url": f"/private/files/{MANIFEST}"}):
            frappe.get_doc({"doctype": "File", "file_url": f"/private/files/{MANIFEST}", "file_name": MANIFEST,
                            "is_private": 1, "attached_to_doctype": "SLHRM Settings",
                            "attached_to_name": "SLHRM Settings"}).insert(ignore_permissions=True)


def _commit():
    frappe.db.commit()


def _ensure(m, doctype, filters, build, submit=False):
    """Create the doc unless one matching `filters` exists; record it in the manifest."""
    existing = frappe.db.get_value(doctype, filters, "name") if filters else None
    if existing:
        return existing
    doc = build() if callable(build) else build
    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    doc.insert(ignore_permissions=True)
    if submit:
        doc.submit()
    m.add(doctype, doc.name)
    _commit()
    return doc.name


def _company():
    company = frappe.db.get_single_value("SLHRM Settings", "default_company")
    if not company:
        companies = frappe.get_all("Company", pluck="name")
        if len(companies) != 1:
            frappe.throw("Set SLHRM Settings > Default Company (more than one Company exists).")
        company = companies[0]
    return company


def _department(company, *candidates):
    for c in candidates:
        name = f"{c} - {frappe.get_cached_value('Company', company, 'abbr')}"
        if frappe.db.exists("Department", name):
            return name
    return None


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _is_off(d):
    return d.weekday() == 6 or d in HOLIDAYS


def _at(d, hh, mm, plus_minutes=0):
    return datetime(d.year, d.month, d.day, hh, mm) + timedelta(minutes=plus_minutes)


# ── create ──────────────────────────────────────────────────────


def create():
    frappe.set_user("Administrator")
    real = frappe.db.sql_list("SELECT name FROM tabEmployee WHERE employee_name NOT LIKE 'DEMO%%'")
    if real:
        frappe.throw(f"Refusing to create DEMO data: {len(real)} non-DEMO Employee(s) exist on this site.")

    m = Manifest()
    company = _company()
    currency = frappe.get_cached_value("Company", company, "default_currency")

    # settings (record originals once)
    if not m.data["settings_before"]:
        s = frappe.get_single("SLHRM Settings")
        m.data["settings_before"] = {k: s.get(k) for k in SLHRM_SETTINGS}
        m.save()

    for b in (BR_FACTORY, BR_OFFICE):
        _ensure(m, "Branch", {"name": b}, {"doctype": "Branch", "branch": b})
    for dsg in ("DEMO Operator", "DEMO Supervisor", "DEMO Clerk"):
        _ensure(m, "Designation", {"name": dsg}, {"doctype": "Designation", "designation_name": dsg})
    _ensure(m, "Shift Type", {"name": SH_DAY}, {"doctype": "Shift Type", "__newname": SH_DAY,
                                               "start_time": "08:00:00", "end_time": "17:00:00"})
    _ensure(m, "Shift Type", {"name": SH_NIGHT}, {"doctype": "Shift Type", "__newname": SH_NIGHT,
                                                 "start_time": "20:00:00", "end_time": "05:00:00"})

    def holiday_list():
        hl = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": HOLIDAY_LIST,
                             "from_date": "2026-10-01", "to_date": "2026-12-31", "weekly_off": "Sunday"})
        hl.get_weekly_off_dates()
        for d, desc in HOLIDAYS.items():
            hl.append("holidays", {"holiday_date": d, "description": desc, "weekly_off": 0})
        return hl
    _ensure(m, "Holiday List", {"name": HOLIDAY_LIST}, holiday_list)

    comp = lambda key, typ, **kw: _ensure(m, "Salary Component", {"name": C[key][0]}, dict(
        doctype="Salary Component", salary_component=C[key][0], salary_component_abbr=C[key][1], type=typ, **kw))
    comp("basic", "Earning", depends_on_payment_days=1)
    comp("bra", "Earning", depends_on_payment_days=1)
    comp("aa", "Earning", depends_on_payment_days=0)
    comp("not", "Earning", depends_on_payment_days=0)
    comp("dot", "Earning", depends_on_payment_days=0)
    comp("epf", "Deduction", depends_on_payment_days=1)
    comp("epf_er", "Deduction", depends_on_payment_days=1, statistical_component=1, do_not_include_in_total=1)
    comp("etf", "Deduction", depends_on_payment_days=1, statistical_component=1, do_not_include_in_total=1)

    _ensure(m, "Salary Structure", {"name": STRUCTURE}, {
        "doctype": "Salary Structure", "__newname": STRUCTURE, "company": company, "currency": currency,
        "payroll_frequency": "Monthly", "is_active": "Yes",
        "earnings": [
            {"salary_component": C["basic"][0], "amount_based_on_formula": 1, "formula": "base", "depends_on_payment_days": 1},
            {"salary_component": C["bra"][0], "amount": 3500, "depends_on_payment_days": 1},
            {"salary_component": C["aa"][0], "amount": 2500, "depends_on_payment_days": 0},
        ],
        "deductions": [
            {"salary_component": C["epf"][0], "amount_based_on_formula": 1, "formula": "(DBAS + DBRA) * 0.08", "depends_on_payment_days": 1},
            {"salary_component": C["epf_er"][0], "amount_based_on_formula": 1, "formula": "(DBAS + DBRA) * 0.12",
             "depends_on_payment_days": 1, "statistical_component": 1, "do_not_include_in_total": 1},
            {"salary_component": C["etf"][0], "amount_based_on_formula": 1, "formula": "(DBAS + DBRA) * 0.03",
             "depends_on_payment_days": 1, "statistical_component": 1, "do_not_include_in_total": 1},
        ],
    }, submit=True)

    _ensure(m, "Leave Type", {"name": LT_LWP}, {"doctype": "Leave Type", "leave_type_name": LT_LWP, "is_lwp": 1})
    _ensure(m, "Leave Type", {"name": LT_CASUAL}, {"doctype": "Leave Type", "leave_type_name": LT_CASUAL,
                                                   "max_leaves_allowed": 7})

    # ── users + employees ──
    approver = EMAIL.format("e01")
    for code, last, branch, shift, ot, app, roles, base, dsg in EMPLOYEES:
        email = EMAIL.format(code.lower())
        if not frappe.db.exists("User", email):
            u = frappe.get_doc({"doctype": "User", "email": email, "first_name": f"DEMO {code}", "last_name": last,
                                "send_welcome_email": 0, "user_type": "System User",
                                "roles": [{"role": r} for r in ["Employee", *roles]]})
            u.flags.no_welcome_mail = True
            u.insert(ignore_permissions=True)
            m.add("User", u.name)
        from frappe.utils.password import update_password
        update_password(email, PASSWORD)
        frappe.db.set_value("User", email, "slhrm_must_change_password", 0)
        _commit()

        dept = _department(company, "Human Resources") if roles else (
            _department(company, "Dispatch", "Production") if branch == BR_FACTORY else _department(company, "Accounts"))
        emp = _ensure(m, "Employee", {"user_id": email}, {
            "doctype": "Employee", "first_name": f"DEMO {code}", "last_name": last, "company": company,
            "status": "Active", "gender": "Male", "date_of_birth": "1990-01-01", "date_of_joining": "2026-01-15",
            "branch": branch, "department": dept, "designation": dsg, "default_shift": shift, "user_id": email,
            "create_user_permission": 0 if roles else 1, "leave_approver": approver if code != "E01" else None,
            "slhrm_ot_eligible": ot, "slhrm_allow_app_checkin": app,
        })
        m.data["employees"][code] = emp
        m.save()
        _ensure(m, "Holiday List Assignment", {"assigned_to": emp, "holiday_list": HOLIDAY_LIST, "docstatus": 1}, {
            "doctype": "Holiday List Assignment", "applicable_for": "Employee", "assigned_to": emp,
            "holiday_list": HOLIDAY_LIST, "from_date": "2026-10-01"}, submit=True)
        if base and code != ESP_EMPLOYEE:
            _ensure(m, "Salary Structure Assignment", {"employee": emp, "docstatus": 1}, {
                "doctype": "Salary Structure Assignment", "employee": emp, "salary_structure": STRUCTURE,
                "company": company, "currency": currency, "from_date": "2026-10-01", "base": base}, submit=True)

    E = m.data["employees"]

    # Employee Salary Package (creates its own SSA): Basic override = base, allowance override 2500 -> 4000
    base_esp = next(e[7] for e in EMPLOYEES if e[0] == ESP_EMPLOYEE)
    _ensure(m, "Employee Salary Package", {"employee": E[ESP_EMPLOYEE]}, {
        "doctype": "Employee Salary Package", "employee": E[ESP_EMPLOYEE], "company": company,
        "salary_structure": STRUCTURE, "effective_from": "2026-10-01", "payroll_frequency": "Monthly",
        "components": [
            {"salary_component": C["basic"][0], "salary_component_type": "Earning", "amount": base_esp,
             "override": 1, "depends_on_payment_days": 1},
            {"salary_component": C["aa"][0], "salary_component_type": "Earning", "amount": ESP_ALLOWANCE,
             "override": 1, "depends_on_payment_days": 0},
        ]})

    # leave: casual allocation + applications (before markers; they create Attendance)
    _ensure(m, "Leave Allocation", {"employee": E["E06"], "leave_type": LT_CASUAL, "docstatus": 1}, {
        "doctype": "Leave Allocation", "employee": E["E06"], "leave_type": LT_CASUAL, "from_date": "2026-10-01",
        "to_date": "2026-12-31", "new_leaves_allocated": 7}, submit=True)
    for code, lt, d1, d2 in ((LWP_DAYS[0], LT_LWP, LWP_DAYS[1], LWP_DAYS[2]),
                             (CASUAL_DAY[0], LT_CASUAL, CASUAL_DAY[1], CASUAL_DAY[1])):
        _ensure(m, "Leave Application", {"employee": E[code], "from_date": d1, "docstatus": 1}, {
            "doctype": "Leave Application", "employee": E[code], "leave_type": lt, "from_date": d1, "to_date": d2,
            "leave_approver": approver, "status": "Approved", "company": company, "posting_date": "2026-10-15",
            "description": "DEMO leave"}, submit=True)

    # settings
    s = frappe.get_single("SLHRM Settings")
    for k, v in SLHRM_SETTINGS.items():
        s.set(k, v)
    s.save(ignore_permissions=True)
    _commit()

    # ── punches ──
    yesterday = getdate(nowdate()) - timedelta(days=1)
    for code, _last, branch, shift, *_ in EMPLOYEES:
        emp = E[code]
        days = list(_days(OCT_START, OCT_END))
        if code in NOV_EMPLOYEES:
            days += list(_days(date(2026, 11, 1), yesterday))
        for d in days:
            punches = _punches_for(code, shift, d)
            for i, t in enumerate(punches):
                _punch(m, code, emp, branch, t, "IN" if i == 0 else "OUT")

    # ── attendance markers (Oct): submitted up to Oct 28, draft from Oct 29 ──
    from slhrm.api import load_attendance_data
    for d in _days(OCT_START, OCT_END):
        for branch in (BR_FACTORY, BR_OFFICE):
            if frappe.db.exists("Attendance Marker", {"date": d, "branch": branch, "docstatus": ["<", 2]}):
                continue
            data = load_attendance_data(str(d), branch)
            rows, refs = [], []
            for e in data["employees"]:
                mm = data["matched"][e.name]
                if frappe.db.exists("Attendance", {"employee": e.name, "attendance_date": d, "docstatus": 1}):
                    continue  # leave already marked by the Leave Application
                if not mm["punch_count"] and mm["is_holiday"]:
                    continue  # not working on a holiday / Sunday
                rows.append({
                    "employee": e.name, "employee_name": e.employee_name, "department": e.department,
                    "shift": e.default_shift, "attendance_status": "Present" if mm["punch_count"] else "Absent",
                    "attendance_source": ("App" if mm["punch_source"] == "App" else "Biometric") if mm["punch_count"] else "Manual",
                    "punch_source": mm["punch_source"], "in_time": mm["in_time"], "out_time": mm["out_time"],
                    "auto_in_time": mm["in_time"], "auto_out_time": mm["out_time"],
                    "normal_ot_hours": mm["calc_normal_ot"] if mm["ot_eligible"] else 0,
                    "double_ot_hours": mm["calc_double_ot"] if mm["ot_eligible"] else 0,
                })
                refs += [r for r in data["punch_refs"] if r["employee"] == e.name]
            if not rows:
                continue
            mk = frappe.get_doc({"doctype": "Attendance Marker", "date": d, "branch": branch, "company": company,
                                 "attendance_details": rows,
                                 "punch_references": [dict(r, punch_sequence=i + 1) for i, r in enumerate(refs)]})
            mk.insert(ignore_permissions=True)
            m.add("Attendance Marker", mk.name)
            if d < DRAFT_FROM:
                mk.submit()
            _commit()

    print(json.dumps(report(print_out=False), indent=1, default=str))
    return "DEMO data created"


def _punches_for(code, shift, d):
    """Deterministic punch times for one employee-day ([] = no punch)."""
    rng = random.Random(f"slhrm-demo-{code}-{d.isoformat()}")
    if (code, d) in ABSENT:
        return []
    if code == LWP_DAYS[0] and LWP_DAYS[1] <= d <= LWP_DAYS[2]:
        return []
    if (code, d) == CASUAL_DAY:
        return []
    night = shift == SH_NIGHT
    if _is_off(d):
        if code not in HOLIDAY_WORKERS:
            return []
        start = _at(d, 20, 0, rng.randint(-10, 10)) if night else _at(d, 8, 0, rng.randint(-10, 10))
        return [start, start + timedelta(minutes=rng.randint(360, 480))]
    if night:
        tin = _at(d, 19, 45, rng.randint(0, 30))
        tout = _at(d + timedelta(days=1), 5, 0, rng.randint(0, 120))
    else:
        tin = _at(d, 7, 45, rng.randint(0, 30))
        tout = _at(d, 17, 0, rng.randint(0, 210))
    if (code, d) == SINGLE_PUNCH:
        return [tin]
    return [tin, tout]


def _punch(m, code, emp, branch, t, log_type):
    if code in APP_USERS:
        if frappe.db.exists("Employee Checkin", {"employee": emp, "time": t}):
            return
        ci = frappe.get_doc({"doctype": "Employee Checkin", "employee": emp, "log_type": log_type, "time": t,
                             "device_id": "DEMO-APP"})
        ci.insert(ignore_permissions=True)  # Administrator: explicit historical time allowed
        m.data["created"].append(["Employee Checkin", ci.name])
    else:
        if frappe.db.exists("Biometric Punch Log", {"employee": emp, "punch_time": t}):
            return
        p = frappe.get_doc({"doctype": "Biometric Punch Log", "employee": emp, "punch_time": t,
                            "punch_type": log_type,
                            "source_device": "DEMO-BIO-FACTORY" if branch == BR_FACTORY else "DEMO-BIO-OFFICE"})
        p.insert(ignore_permissions=True)
        m.data["created"].append(["Biometric Punch Log", p.name])
    m.save()
    _commit()


# ── report / preview ────────────────────────────────────────────


def report(print_out=True):
    m = Manifest()
    E = m.data.get("employees", {})
    counts = {}
    for dt, _n in m.data["created"]:
        counts[dt] = counts.get(dt, 0) + 1
    emp_names = list(E.values())
    ot = {}
    if emp_names:
        for r in frappe.db.sql(
            """SELECT amd.employee, SUM(amd.normal_ot_hours) n, SUM(amd.double_ot_hours) d, COUNT(*) days
               FROM `tabAttendance Marker Detail` amd JOIN `tabAttendance Marker` am ON am.name = amd.parent
               WHERE am.docstatus = 1 AND am.date BETWEEN %s AND %s AND amd.employee IN %s
               GROUP BY amd.employee""", (OCT_START, OCT_END, emp_names), as_dict=True):
            ot[r.employee] = (flt(r.n, 2), flt(r.d, 2), r.days)
    logins = []
    for code, last, branch, shift, ot_el, app, roles, base, dsg in EMPLOYEES:
        emp = E.get(code)
        n, d, days = ot.get(emp, (0, 0, 0))
        logins.append({"code": code, "employee": emp, "user": EMAIL.format(code.lower()), "password": PASSWORD,
                       "roles": ", ".join(["Employee", *roles]), "branch": branch, "shift": shift,
                       "ot_eligible": ot_el, "app_checkin": app, "base": base or "NO SSA",
                       "oct_marker_days(submitted)": days, "oct_normal_ot_h": n, "oct_double_ot_h": d})
    live = {dt: frappe.db.count(dt, {"name": ["in", [x[1] for x in m.data["created"] if x[0] == dt]]})
            for dt in counts}
    out = {"created_by_manifest": counts, "still_existing": live, "employees": logins}
    if print_out:
        print(json.dumps(out, indent=1, default=str))
    return out


def preview_payroll(branch=BR_FACTORY, payroll_month="10", payroll_year=2026):
    """Payroll Worksheet numbers IN MEMORY (nothing saved)."""
    from slhrm.api import load_payroll_data

    data = load_payroll_data(branch, _company(), payroll_month, payroll_year)
    rows = data.get("employees", [])
    print(f"{'employee':16} {'name':22} {'pay/work days':>13} {'normal OT':>10} {'double OT':>10} "
          f"{'salary gross':>13} {'gross':>12} {'deductions':>11} {'net':>12}  error")
    for r in rows:
        print(f"{r['employee']:16} {(r['employee_name'] or '')[:22]:22} "
              f"{flt(r['payment_days']):>6.1f}/{flt(r['total_working_days']):<6.1f} "
              f"{r['normal_ot_amount']:>10.2f} {r['double_ot_amount']:>10.2f} {r['structure_gross']:>13.2f} "
              f"{r['total_earning']:>12.2f} {r['total_deduction']:>11.2f} {r['net_pay']:>12.2f}  {r['row_error'] or ''}")
    print("summary:", json.dumps(data.get("summary"), default=str))
    return data.get("summary")


# ── remove ──────────────────────────────────────────────────────

REMOVE_ORDER = [
    "Salary Slip", "Payroll Entry", "Payroll Worksheet", "Additional Salary", "Leave Application",
    "Leave Allocation", "Leave Ledger Entry", "Attendance Marker", "Attendance", "Employee Checkin",
    "Biometric Punch Log", "Employee Salary Package", "Salary Structure Assignment", "Salary Structure",
    "Holiday List Assignment", "User Permission", "Employee", "Contact", "User", "Leave Type", "Shift Type",
    "Holiday List", "Designation", "Branch", "Salary Component",
]


def remove():
    frappe.set_user("Administrator")
    m = Manifest()
    docs = [tuple(x) for x in m.data["created"]]
    emps = list(m.data.get("employees", {}).values())
    branches = [BR_FACTORY, BR_OFFICE]

    # sweep records created by hooks or by manual testing for DEMO employees / branches
    sweep = []
    if emps:
        for dt, field in (("Salary Slip", "employee"), ("Additional Salary", "employee"),
                          ("Leave Application", "employee"), ("Leave Allocation", "employee"),
                          ("Leave Ledger Entry", "employee"), ("Attendance", "employee"),
                          ("Employee Checkin", "employee"), ("Biometric Punch Log", "employee"),
                          ("Employee Salary Package", "employee"), ("Salary Structure Assignment", "employee"),
                          ("Holiday List Assignment", "assigned_to")):
            sweep += [(dt, n) for n in frappe.get_all(dt, filters={field: ["in", emps]}, pluck="name")]
    for dt in ("Payroll Worksheet", "Attendance Marker", "Payroll Entry"):
        sweep += [(dt, n) for n in frappe.get_all(dt, filters={"branch": ["in", branches]}, pluck="name")]
    sweep += [("Contact", n) for n in frappe.get_all("Contact", filters={"email_id": ["like", "demo-%@demo.local"]}, pluck="name")]
    sweep += [("User Permission", n) for n in frappe.get_all("User Permission", filters={"user": ["like", "demo-%@demo.local"]}, pluck="name")]
    all_docs = list(dict.fromkeys(docs + sweep))

    log = []
    for dt in REMOVE_ORDER:
        for d, name in all_docs:
            if d != dt:
                continue
            try:
                if not frappe.db.exists(dt, name):
                    log.append((dt, name, "already gone"))
                    continue
                doc = frappe.get_doc(dt, name)
                doc.flags.ignore_permissions = True
                if doc.meta.is_submittable and doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc(dt, name, force=1, ignore_permissions=True)
                log.append((dt, name, "deleted"))
                _commit()
            except Exception as e:
                frappe.db.rollback()
                log.append((dt, name, f"ERROR {type(e).__name__}: {str(e)[:160]}"))

    before = m.data.get("settings_before") or {}
    if before:
        for k, v in before.items():
            frappe.db.set_single_value("SLHRM Settings", k, v)
    _commit()

    print("=== remove log ===")
    for row in log:
        print(" | ".join(row))
    print("=== proof ===")
    remaining = [(d, n) for d, n in all_docs if frappe.db.exists(d, n)]
    for d, n in all_docs:
        print(f"{d} | {n} | {'STILL EXISTS' if frappe.db.exists(d, n) else 'gone'}")
    counts = {dt: frappe.db.count(dt) for dt in ("Employee", "Attendance", "Salary Slip", "Additional Salary")}
    print("remaining:", remaining)
    print("counts:", counts)
    print("settings restored:", {k: frappe.db.get_single_value("SLHRM Settings", k) for k in before})

    if not remaining:
        f = frappe.db.get_value("File", {"file_url": f"/private/files/{MANIFEST}"})
        if f:
            frappe.delete_doc("File", f, force=1, ignore_permissions=True)
        if os.path.exists(m.path):
            os.remove(m.path)
        _commit()
        print("manifest removed")
    return {"remaining": len(remaining), "counts": counts}
