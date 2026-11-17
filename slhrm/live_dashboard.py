# slhrm/live_dashboard.py
"""Live Attendance Dashboard v2 (v0.4.6, page "slhrm-dashboard"): one card per branch + per-branch lists. Read-only,
permitted branches only (Branch User Permissions).

Today (site time, Asia/Colombo) from MATCHED punches paired with the marker's own logic (slhrm.attendance.split_sessions over
D−2 … now):
- On duty: the employee's latest session is OPEN (odd taps = an IN without its OUT) and started within ON_DUTY_HOURS (16) —
  also a night shift from yesterday. An older open session → "Missing OUT" (not on duty).
- Not punched yet: no punch today, not on duty / missing OUT, not on holiday (Holiday List Assignment) or approved leave.
  ONLY for branches served by an enabled device; a branch without one shows "No device — attendance by manual marker" and its
  staff are never "not punched". Shift start + 30 min passed → "late / not arrived".
- Late arrivals (default shift only): today's first session starts after the shift start.
- Unmatched punches today: devices serving the branch.
Card: device dot (worst status of the enabled devices serving the branch; "No device"), punched x / y, pills, yesterday's
marker (None / Draft / Submitted), month completed x / y (slhrm.attendance_calendar, cached 60 s).
"""
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime

READ_ROLES = ("HR Manager", "HR User", "Attendance Supervisor", "System Manager")
NOT_ARRIVED_GRACE = timedelta(minutes=30)
ON_DUTY_HOURS = 16
MONTH_CACHE_SECONDS = 60
BRANCH_COLORS = {"DUTCHPUB": "teal", "BRITISHPUB": "indigo", "FORTFUSION": "orange", "ALIYA": "purple"}
PALETTE = ("cyan", "pink", "blue", "green", "yellow", "red")
WORST = {"Offline": 3, "Delayed": 2, "Online": 1}


def branch_color(branch):
    """Fixed colour per branch (tokens resolved in the page); other branches get a stable palette colour."""
    return BRANCH_COLORS.get(branch) or PALETTE[sum(map(ord, branch or "")) % len(PALETTE)]


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


def _ceil5(t):
    """Next */5 cron tick at or after t."""
    t0 = t.replace(second=0, microsecond=0)
    if t0 < t:
        t0 += timedelta(minutes=1)
    return t0 + timedelta(minutes=(-t0.minute) % 5)


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


def _month(branch, today):
    key = f"slhrm:live_month:{branch}:{today:%Y-%m-%d}"
    cached = frappe.cache.get_value(key)
    if cached:
        return cached
    from slhrm.attendance_calendar import build as calendar

    first = today.replace(day=1)
    h = calendar(branch, f"{today:%Y-%m}")["header"]
    ot, short = frappe.db.sql("""select ifnull(sum(d.ot_hours), 0), ifnull(sum(d.short_hours), 0)
        from `tabAttendance Marker Detail` d join `tabAttendance Marker` m on m.name = d.parent
        where m.docstatus = 1 and m.branch = %s and m.date between %s and %s""", (branch, first, today))[0]
    out = {"completed": h["completed"], "working": h["working"], "ot_hours": flt(ot, 2), "short_hours": flt(short, 2)}
    frappe.cache.set_value(key, out, expires_in_sec=MONTH_CACHE_SECONDS)
    return out


def build(branch=None, now=None):
    from slhrm.attendance import (DEFAULT_MAX_SESSION_HOURS, DEFAULT_REST_GAP_HOURS, _taps, fetch_punches, get_holiday_info,
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

    devices = frappe.get_all("Biometric Device", fields=["name", "device_name", "branch", "enabled", "connection_status", "last_success_at",
                                                         "last_pull", "sync_interval_minutes", "quiet_windows", "last_error"])
    serves = {d.name: set(served_branches(d.name, d.branch)) for d in devices}
    emps = frappe.get_all("Employee", filters={"status": "Active", "branch": ["in", branches or ["-"]]},
                          fields=["name", "employee_name", "branch", "default_shift", "slhrm_allow_app_checkin"], order_by="employee_name asc")
    punches = fetch_punches(emps, day0 - timedelta(days=2), now) if emps else {}
    on_leave = set(frappe.get_all("Leave Application", filters={"employee": ["in", [e.name for e in emps] or ["-"]], "status": "Approved",
                                                                 "docstatus": 1, "from_date": ["<=", today], "to_date": [">=", today]},
                                  pluck="employee"))
    yday = add_days(today, -1)
    cards, lists = [], {}
    for b in branches:
        bdev = [d for d in devices if cint(d.enabled) and b in serves[d.name]]
        has_device = bool(bdev)
        worst = max((d.connection_status or "Offline" for d in bdev), key=lambda s: WORST.get(s, 3), default=None)
        L = {"on_duty": [], "not_punched": [], "late": [], "missing_out": []}
        staff = [e for e in emps if e.branch == b]
        punched = 0
        for e in staff:
            mine = [p for p in punches.get(e.name, []) if p.time <= now]
            today_p = [p for p in mine if p.time >= day0]
            punched += 1 if today_p else 0
            sessions = split_sessions(mine, gap, max_h, std)
            last = sessions[-1] if sessions else None
            is_open = bool(last) and len(_taps(last)) % 2 == 1
            age_h = (now - last[0].time).total_seconds() / 3600 if last else None
            row = {"employee": e.name, "employee_name": e.employee_name, "shift": e.default_shift or ""}
            if is_open and age_h <= ON_DUTY_HOURS:
                L["on_duty"].append(dict(row, time=str(last[0].time), hours=round(age_h, 2)))
            elif is_open:
                L["missing_out"].append(dict(row, time=str(last[0].time), hours=round(age_h, 2)))
            start_shift = _shift_start(e.default_shift, today)
            todays = [s for s in sessions if s[0].time >= day0]
            if start_shift and todays and todays[0][0].time > start_shift:
                L["late"].append(dict(row, time=str(todays[0][0].time), shift_start=str(start_shift),
                                      minutes=int((todays[0][0].time - start_shift).total_seconds() // 60)))
            if has_device and not today_p and not is_open:
                if get_holiday_info(e.name, str(today))[0] or e.name in on_leave:
                    continue
                L["not_punched"].append(dict(row, time=str(start_shift) if start_shift else None,
                                             not_arrived=1 if start_shift and now > start_shift + NOT_ARRIVED_GRACE else 0))
        L["on_duty"].sort(key=lambda x: x["time"])
        L["not_punched"].sort(key=lambda x: (-x["not_arrived"], x["employee_name"]))
        L["late"].sort(key=lambda x: -x["minutes"])
        serials = [d.name for d in bdev]
        unmatched = frappe.db.count("Biometric Punch Log", {"processing_status": "Unmatched", "device_serial": ["in", serials],
                                                            "punch_time": [">=", day0]}) if serials else 0
        ms = frappe.get_all("Attendance Marker", filters={"branch": b, "date": yday, "docstatus": ["<", 2]},
                            fields=["name", "docstatus"], order_by="docstatus desc, modified desc")
        ym = ms[0] if ms else None
        cards.append({
            "branch": b, "color": branch_color(b), "employees": len(staff), "punched": punched,
            "device": worst or "No device", "has_device": has_device,
            "devices": [{"name": d.name, "device_name": d.device_name, "status": d.connection_status or "Offline",
                         "last_success_at": str(d.last_success_at) if d.last_success_at else None,
                         "next_read": str(_next_read(d, now))} for d in bdev],
            "on_duty": len(L["on_duty"]), "not_punched": len(L["not_punched"]), "late": len(L["late"]),
            "missing_out": len(L["missing_out"]), "not_arrived": sum(1 for x in L["not_punched"] if x["not_arrived"]),
            "unmatched": unmatched,
            "yesterday": {"date": str(yday), "status": ("Submitted" if ym.docstatus == 1 else "Draft") if ym else "None",
                          "marker": ym.name if ym else None},
            "month": _month(b, today),
        })
        lists[b] = L
    return {"now": str(now), "today": str(today), "branches": cards, "lists": lists}


@frappe.whitelist()
def get_dashboard(branch=None):
    frappe.only_for(READ_ROLES)
    return build(branch or None)
