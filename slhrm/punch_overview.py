# slhrm/punch_overview.py
"""Attendance Marker "Punch Overview" (v0.4.2): one read-only line per Attendance Details row — Previous punch | IN | OUT |
Next punch | Hrs | Flags — built from SERVER data on every load / refresh (no stored child table). The rows come from the
marker itself (form: the current, possibly unsaved rows; print: the saved rows), so the overview always matches them;
punches are read live over the same window as the loader (D−2 00:00 … D+2 00:00, slhrm.attendance).

- Previous punch = last punch before IN (or before OUT when IN is missing); Next punch = first punch after OUT (or after IN
  when OUT is missing). Any date within the window.
- Every time is shown with its date (dd-mm hh:mm); a time on another date than the marker's is "muted"; OUT on D+1 → "+1".
- Flags: Missing punch / Long session / No shift (row flags) + Two sessions (no-shift row: more than one punch session starts
  on D, slhrm.attendance.sessions_for_day) + Other branch (the employee's branch is not the marker's, or a punch used by the
  row came from a device that does not serve the marker's branch).
Used by slhrm.api.marker_punch_overview (form) and the jinja method marker_overview (print format "Attendance Marker").
"""
from datetime import datetime, timedelta

import frappe
from frappe.utils import cint, cstr, flt, getdate

from slhrm.attendance import (combine, fetch_punches, get_settings, sessions_for_day, used_by_other_markers,
                              DEFAULT_MAX_SESSION_HOURS, DEFAULT_REST_GAP_HOURS)

FLAG_MISSING, FLAG_LONG, FLAG_NO_SHIFT, FLAG_TWO, FLAG_OTHER = "Missing punch", "Long session", "No shift", "Two sessions", "Other branch"
MAX_ROWS = 1000


def _cell(dt, day, out=False):
    if not dt:
        return {"text": "", "iso": None, "muted": 0, "plus1": 0}
    return {"text": dt.strftime("%d-%m %H:%M"), "iso": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "muted": 1 if dt.date() != day else 0, "plus1": 1 if out and dt.date() > day else 0}


def build(date_str, branch, rows):
    """rows: dicts / child docs with employee, employee_name, shift, in_time, out_time, out_next_day, worked_hours,
    missing_punch, long_session, no_shift. Returns {"date", "rows": [...], "counts": {all, flagged, missing}} sorted by name."""
    from slhrm.biometric import served_branches

    day = getdate(date_str)
    g = lambda r, k: r.get(k) if isinstance(r, dict) else getattr(r, k, None)  # noqa: E731
    rows = [r for r in (rows or []) if g(r, "employee")][:MAX_ROWS]
    names = list(dict.fromkeys(g(r, "employee") for r in rows))
    emps = {e.name: e for e in frappe.get_all("Employee", filters={"name": ["in", names or ["-"]]},
                                              fields=["name", "employee_name", "employee_number", "branch", "slhrm_allow_app_checkin"])}
    start = datetime.combine(day, datetime.min.time()) - timedelta(days=2)
    end = datetime.combine(day, datetime.min.time()) + timedelta(days=2) - timedelta(microseconds=1)
    punches = fetch_punches([{"name": n, "slhrm_allow_app_checkin": (emps.get(n) or {}).get("slhrm_allow_app_checkin")} for n in names],
                            start, end) if names else {}
    used = used_by_other_markers([p.name for ps in punches.values() for p in ps], str(day))
    devices = {d.name: d for d in frappe.get_all("Biometric Device", fields=["name", "device_name", "branch"])}
    serves = {s: branch in served_branches(s, d.branch) for s, d in devices.items()}
    settings = get_settings()
    gap = flt(settings.get("rest_gap_hours")) or DEFAULT_REST_GAP_HOURS
    max_h = flt(settings.get("max_session_hours")) or DEFAULT_MAX_SESSION_HOURS
    std = flt(settings.get("standard_day_hours")) or 9.0

    out = []
    for r in rows:
        emp = g(r, "employee")
        e = emps.get(emp) or frappe._dict()
        mine = punches.get(emp, [])
        in_dt = combine(day, g(r, "in_time")) if g(r, "in_time") else None
        out_dt = combine(day, g(r, "out_time"), g(r, "out_next_day")) if g(r, "out_time") else None
        first, last = in_dt or out_dt, out_dt or in_dt
        prev = [p for p in mine if first and p.time < first]
        nxt = [p for p in mine if last and p.time > last]
        session = [p for p in mine if first and first <= p.time <= last]
        flags = []
        if cint(g(r, "missing_punch")):
            flags.append(FLAG_MISSING)
        if cint(g(r, "long_session")):
            flags.append(FLAG_LONG)
        if not g(r, "shift"):
            if cint(g(r, "no_shift")):
                flags.append(FLAG_NO_SHIFT)
            if len(sessions_for_day([p for p in mine if p.name not in used], day, gap, max_h, std)) > 1:
                flags.append(FLAG_TWO)
        if (e.branch and e.branch != branch) or any(p.get("device") and not serves.get(p.get("device"), True) for p in session):
            flags.append(FLAG_OTHER)
        out.append({
            "employee": emp, "employee_name": g(r, "employee_name") or e.employee_name or emp,
            "employee_number": cstr(e.employee_number), "row_name": g(r, "name"), "idx": g(r, "idx"),
            "status": g(r, "attendance_status") or "",
            "prev": _cell(prev[-1].time if prev else None, day), "in": _cell(in_dt, day),
            "out": _cell(out_dt, day, out=True), "next": _cell(nxt[0].time if nxt else None, day),
            "hours": flt(g(r, "worked_hours"), 2), "flags": flags,
        })
    out.sort(key=lambda x: (cstr(x["employee_name"]).lower(), x["employee"]))
    return {"date": str(day), "rows": out, "counts": {
        "all": len(out), "flagged": sum(1 for x in out if x["flags"]),
        "missing": sum(1 for x in out if FLAG_MISSING in x["flags"])}}


def marker_overview(doc):
    """Jinja method for the "Attendance Marker" print format."""
    return build(str(doc.date), doc.branch, doc.get("attendance_details") or [])
