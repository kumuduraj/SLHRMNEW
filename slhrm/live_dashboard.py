# slhrm/live_dashboard.py
"""Live Attendance Dashboard (v0.4.5, page "slhrm-dashboard"). Read-only, permitted branches only (Branch User Permissions).

Today (site time, Asia/Colombo) from MATCHED Biometric Punch Log / app check-ins, paired with the marker's own logic
(slhrm.attendance.split_sessions over D−2 … now):
- Punched today: distinct employees with a punch since 00:00.
- Currently on duty: the employee's latest session is OPEN (odd number of taps = an IN without its OUT) and started less than
  max_session_hours ago — also a night shift that started yesterday. IN time, shift, hours so far.
- Not punched yet: active employees without a punch today and not on duty, excluding today's holiday (their Holiday List
  Assignment) and approved Leave Applications; with a shift and shift start + 30 min passed → "late / not arrived".
- Late arrivals (shift assigned): today's first session starts after the shift start → minutes late.
- Unmatched punches today: devices serving the branches (link: Unmatched Device Users).
Devices: status, last successful sync, next scheduled read (last read + interval, next 5-min cron tick, after quiet windows).
Yesterday: per branch marker status (none / draft / submitted) + P / A / NP / missing punch counts.
This month: per branch completed working days x / y (slhrm.attendance_calendar.build) + OT / short hours of submitted markers.
"""
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime

READ_ROLES = ("HR Manager", "HR User", "Attendance Supervisor", "System Manager")
NOT_ARRIVED_GRACE = timedelta(minutes=30)
MONTH_CACHE_SECONDS = 60


def permitted_branches(branch=None):
    from frappe.core.doctype.user_permission.user_permission import get_permitted_documents

    allowed = get_permitted_documents("Branch") or frappe.get_all("Branch", pluck="name", order_by="name")
    if branch:
        if branch not in allowed:
            frappe.throw(_("Not permitted for branch {0}.").format(branch), frappe.PermissionError)
        return [branch]
    return sorted(allowed)


def _shift_start(shift, day):
    if not shift:
        return None
    t = frappe.get_cached_value("Shift Type", shift, "start_time")
    if t is None:
        return None
    from slhrm.attendance import _to_timedelta

    return datetime.combine(day, datetime.min.time()) + _to_timedelta(t)


def _taps(session):
    from slhrm.attendance import _taps as taps

    return taps(session)


def _next_read(dev, now):
    from slhrm.biometric import parse_quiet_windows, quiet_until

    iv = 5 if dev.sync_interval_minutes in (None, "") else cint(dev.sync_interval_minutes)
    due = get_datetime(dev.last_pull) + timedelta(minutes=iv) - timedelta(seconds=45) if dev.last_pull else now  # agent tolerance
    t = _ceil5(max(due, now))
    windows = parse_quiet_windows(dev.quiet_windows)
    for _i in range(6):  # step past quiet windows
        until = quiet_until(windows, t)
        if not until:
            break
        h, m = [int(x) for x in until.split(":")]
        nt = t.replace(hour=h, minute=m)
        t = nt if nt > t else nt + timedelta(days=1)
    return t


def _ceil5(t):
    """Next */5 cron tick at or after t."""
    t0 = t.replace(second=0, microsecond=0)
    if t0 < t:
        t0 += timedelta(minutes=1)
    return t0 + timedelta(minutes=(-t0.minute) % 5)


def _month(branches, today):
    key = f"slhrm:live_month:{','.join(branches)}:{today:%Y-%m-%d}"
    cached = frappe.cache.get_value(key)
    if cached:
        return cached
    from slhrm.attendance_calendar import build as calendar

    out = []
    first = today.replace(day=1)
    for b in branches:
        h = calendar(b, f"{today:%Y-%m}")["header"]
        ot, short = frappe.db.sql("""select ifnull(sum(d.ot_hours), 0), ifnull(sum(d.short_hours), 0)
            from `tabAttendance Marker Detail` d join `tabAttendance Marker` m on m.name = d.parent
            where m.docstatus = 1 and m.branch = %s and m.date between %s and %s""", (b, first, today))[0]
        out.append({"branch": b, "completed": h["completed"], "working": h["working"], "ot_hours": flt(ot, 2), "short_hours": flt(short, 2)})
    frappe.cache.set_value(key, out, expires_in_sec=MONTH_CACHE_SECONDS)
    return out


def build(branch=None, now=None):
    from slhrm.attendance import (DEFAULT_MAX_SESSION_HOURS, DEFAULT_REST_GAP_HOURS, fetch_punches, get_holiday_info,
                                  get_settings, split_sessions)
    from slhrm.biometric import served_branches

    branches = permitted_branches(branch)
    now = now or now_datetime()
    today = now.date()
    day0 = datetime.combine(today, datetime.min.time())
    settings = get_settings()
    gap = flt(settings.get("rest_gap_hours")) or DEFAULT_REST_GAP_HOURS
    max_h = flt(settings.get("max_session_hours")) or DEFAULT_MAX_SESSION_HOURS
    std = flt(settings.get("standard_day_hours")) or 9.0
    emps = frappe.get_all("Employee", filters={"status": "Active", "branch": ["in", branches or ["-"]]},
                          fields=["name", "employee_name", "employee_number", "branch", "default_shift", "slhrm_allow_app_checkin"],
                          order_by="employee_name asc")
    punches = fetch_punches(emps, day0 - timedelta(days=2), now) if emps else {}
    on_leave = set(frappe.get_all("Leave Application", filters={"employee": ["in", [e.name for e in emps] or ["-"]], "status": "Approved",
                                                                 "docstatus": 1, "from_date": ["<=", today], "to_date": [">=", today]},
                                  pluck="employee"))
    punched, on_duty, not_punched, late = [], [], [], []
    for e in emps:
        mine = [p for p in punches.get(e.name, []) if p.time <= now]
        today_p = [p for p in mine if p.time >= day0]
        sessions = split_sessions(mine, gap, max_h, std)
        last = sessions[-1] if sessions else None
        open_session = bool(last) and len(_taps(last)) % 2 == 1 and (now - last[0].time).total_seconds() / 3600 <= max_h
        row = {"employee": e.name, "employee_name": e.employee_name, "employee_number": e.employee_number or "", "branch": e.branch,
               "shift": e.default_shift or ""}
        if today_p:
            punched.append(dict(row, first=str(today_p[0].time)))
        if open_session:
            start = last[0].time
            on_duty.append(dict(row, in_time=str(start), hours=round((now - start).total_seconds() / 3600, 2),
                                overnight=1 if start.date() < today else 0))
        start_shift = _shift_start(e.default_shift, today)
        todays = [s for s in sessions if s[0].time >= day0]
        if start_shift and todays and todays[0][0].time > start_shift:
            late.append(dict(row, first=str(todays[0][0].time), shift_start=str(start_shift),
                             minutes=int((todays[0][0].time - start_shift).total_seconds() // 60)))
        if not today_p and not open_session:
            is_holiday, _kind = get_holiday_info(e.name, str(today))
            if is_holiday or e.name in on_leave:
                continue
            not_punched.append(dict(row, not_arrived=1 if start_shift and now > start_shift + NOT_ARRIVED_GRACE else 0,
                                    shift_start=str(start_shift) if start_shift else None))
    devices_all = frappe.get_all("Biometric Device", fields=["name", "device_name", "branch", "enabled", "connection_status",
                                                             "last_success_at", "last_pull", "sync_interval_minutes", "quiet_windows",
                                                             "clock_drift_seconds", "last_error"])
    devices = [d for d in devices_all if set(served_branches(d.name, d.branch)) & set(branches)]
    serials = [d.name for d in devices]
    unmatched = frappe.db.count("Biometric Punch Log", {"processing_status": "Unmatched", "device_serial": ["in", serials or ["-"]],
                                                        "punch_time": [">=", day0]}) if serials else 0
    yday = add_days(today, -1)
    yesterday = []
    for b in branches:
        ms = frappe.get_all("Attendance Marker", filters={"branch": b, "date": yday, "docstatus": ["<", 2]},
                            fields=["name", "docstatus"], order_by="docstatus desc, modified desc")
        m = ms[0] if ms else None
        c = {"P": 0, "A": 0, "NP": 0, "missing": 0}
        if m:
            for r in frappe.get_all("Attendance Marker Detail", filters={"parent": m.name, "parenttype": "Attendance Marker"},
                                    fields=["attendance_status", "missing_punch"]):
                k = {"Present": "P", "Short Leave": "P", "Absent": "A", "No Pay": "NP"}.get(r.attendance_status)
                if k:
                    c[k] += 1
                c["missing"] += cint(r.missing_punch)
        yesterday.append({"branch": b, "marker": m.name if m else None,
                          "status": ("Submitted" if m.docstatus == 1 else "Draft") if m else "None", **c})
    return {
        "now": str(now), "today": str(today), "yesterday_date": str(yday), "branches": branches,
        "counts": {"employees": len(emps), "punched": len(punched), "on_duty": len(on_duty), "not_punched": len(not_punched),
                   "not_arrived": sum(1 for x in not_punched if x["not_arrived"]), "late": len(late), "unmatched": unmatched},
        "on_duty": sorted(on_duty, key=lambda x: x["in_time"]), "not_punched": sorted(not_punched, key=lambda x: (-x["not_arrived"], x["employee_name"])),
        "late": sorted(late, key=lambda x: -x["minutes"]), "punched": punched,
        "devices": [{"name": d.name, "device_name": d.device_name, "status": d.connection_status or "Offline",
                     "last_success_at": str(d.last_success_at) if d.last_success_at else None,
                     "next_read": str(_next_read(d, now)) if cint(d.enabled) else None,
                     "interval": 5 if d.sync_interval_minutes in (None, "") else cint(d.sync_interval_minutes),
                     "drift": flt(d.clock_drift_seconds), "error": (d.last_error or "")[:200]} for d in devices],
        "yesterday": yesterday,
        "month": _month(branches, today),
    }


@frappe.whitelist()
def get_dashboard(branch=None):
    frappe.only_for(READ_ROLES)
    return build(branch or None)
