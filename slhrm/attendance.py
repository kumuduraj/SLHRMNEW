# slhrm/attendance.py
"""Attendance-day computation shared by the Attendance Marker loader, the row
recalculation endpoint and the Attendance Marker controller.

Punch sources:
- Biometric Punch Log for every employee
- Employee Checkin (log_type IN/OUT) only for employees with slhrm_allow_app_checkin = 1

Window: shift start - shift_match_window_before  ...  shift end + ot_punch_window_after, then
ONE PUNCH -> ONE EMPLOYEE-DAY (v0.0.16): the window is cut at the midpoint between the previous day's
shift end and this shift's start, and between this shift's end and the next day's shift start
(neighbour shifts: submitted marker row of D-1 / D+1, else Employee.default_shift). Shifts that really
overlap are not guessed: no automatic IN/OUT, warning "Overlapping shifts". Punches used by another
date's submitted Attendance Marker are skipped.
IN = D + in_time, OUT = (D + 1 if out_next_day else D) + out_time (combine / span_hours).
OT hours and early/late minutes come from slhrm.overtime (the only OT math) via day_figures().
"""
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, getdate

from slhrm.overtime import calculate_ot_hours, early_late_minutes, excused

DEFAULT_WINDOW_BEFORE = 120
DEFAULT_OT_WINDOW_AFTER = 360
MAX_PLAUSIBLE_HOURS = 16  # manual rows above this get a warning (not blocked)

PUNCH_BIOMETRIC = "Biometric Punch Log"
PUNCH_APP = "Employee Checkin"


def get_settings():
    return frappe.get_cached_doc("SLHRM Settings")


# ── Shift ───────────────────────────────────────────────────────


def get_shift_info(shift_name, date_str, settings=None):
    """Shift start/end datetimes, length in hours, and the punch window for date_str.

    No shift -> hours 0 and the window is the whole calendar day.
    """
    day_start = get_datetime(f"{date_str} 00:00:00")
    info = frappe._dict(
        shift=shift_name or "",
        start=None,
        end=None,
        hours=0.0,
        window_start=day_start,
        window_end=day_start + timedelta(days=1) - timedelta(seconds=1),
    )
    if not shift_name:
        return info

    shift = frappe.get_cached_value("Shift Type", shift_name, ["start_time", "end_time"], as_dict=True)
    if not shift or shift.start_time is None or shift.end_time is None:
        return info

    start = datetime.combine(getdate(date_str), datetime.min.time()) + _to_timedelta(shift.start_time)
    end = datetime.combine(getdate(date_str), datetime.min.time()) + _to_timedelta(shift.end_time)
    if end <= start:
        end += timedelta(days=1)  # overnight shift

    settings = settings or get_settings()
    # unset (0/None) -> defaults, same convention as the original shift window code
    before = cint(settings.shift_match_window_before) or DEFAULT_WINDOW_BEFORE
    after = cint(settings.ot_punch_window_after) or DEFAULT_OT_WINDOW_AFTER

    info.update(
        start=start,
        end=end,
        hours=flt((end - start).total_seconds() / 3600, 2),
        window_start=start - timedelta(minutes=before),
        window_end=end + timedelta(minutes=after),
    )
    return info


def clip_windows(info, prev=None, nxt=None):
    """Pure: cut info's punch window against the neighbour days' shifts (frappe._dict from get_shift_info).
    Sets info.overlap (text) when a neighbour shift really overlaps this one. Returns info."""
    info.overlap = ""
    if info.start is None:
        return info
    if prev is not None and prev.end is not None:
        if prev.end > info.start:
            info.overlap = f"previous day's {prev.shift} ends {prev.end:%d-%m %H:%M}, after this shift starts {info.start:%H:%M}"
        else:
            boundary = prev.end + (info.start - prev.end) / 2
            if boundary > info.window_start:
                info.window_start = boundary
    if nxt is not None and nxt.start is not None:
        if info.end > nxt.start:
            info.overlap = (info.overlap + "; " if info.overlap else "") + \
                f"next day's {nxt.shift} starts {nxt.start:%d-%m %H:%M}, before this shift ends {info.end:%d-%m %H:%M}"
        else:
            boundary = info.end + (nxt.start - info.end) / 2
            if boundary <= info.window_end:
                info.window_end = boundary - timedelta(microseconds=1)  # the midpoint itself belongs to the next shift
    return info


def neighbour_shifts(employees, date_str):
    """{employee: (shift of D-1, shift of D+1)}: submitted marker row for that date, else default_shift."""
    names = [e["name"] for e in employees]
    if not names:
        return {}
    prev_d, next_d = str(add_days(date_str, -1)), str(add_days(date_str, 1))
    default = dict(frappe.get_all("Employee", filters={"name": ["in", names]}, fields=["name", "default_shift"], as_list=True))
    marked = {}
    for r in frappe.db.sql("""select d.employee, m.date, d.shift from `tabAttendance Marker Detail` d
                              join `tabAttendance Marker` m on m.name = d.parent
                              where m.docstatus = 1 and m.date in (%s, %s) and d.employee in %s""",
                           (prev_d, next_d, tuple(names)), as_dict=True):
        marked[(r.employee, str(r.date))] = r.shift
    return {n: (marked.get((n, prev_d), default.get(n)), marked.get((n, next_d), default.get(n))) for n in names}


def used_by_other_markers(punch_names, date_str):
    """Punches already used by a SUBMITTED Attendance Marker of another date."""
    if not punch_names:
        return set()
    return set(frappe.db.sql_list("""select r.punch_log from `tabAttendance Marker Punch Reference` r
                                     join `tabAttendance Marker` m on m.name = r.parent
                                     where m.docstatus = 1 and m.date != %s and r.punch_log in %s""",
                                  (date_str, tuple(punch_names))))


def previous_day_marker(branch, company, date_str):
    """Status of the previous day's Attendance Marker for the branch: Submitted / Draft / Cancelled / Not created."""
    prev = str(add_days(date_str, -1))
    filters = {"branch": branch, "date": prev}
    if company:
        filters["company"] = company
    rows = frappe.get_all("Attendance Marker", filters=filters, fields=["name", "docstatus"], order_by="docstatus desc, modified desc")
    best = next((r for r in rows if r.docstatus == 1), None) or next((r for r in rows if r.docstatus == 0), None) or (rows[0] if rows else None)
    status = {1: "Submitted", 0: "Draft", 2: "Cancelled"}.get(best.docstatus) if best else "Not created"
    return frappe._dict(date=prev, status=status, name=best.name if best else None)


def combine(date_value, time_value, next_day=False):
    """datetime of a row's Time value on the shift date (or the next day)."""
    if time_value in (None, ""):
        return None
    d = getdate(date_value)
    return datetime.combine(d, datetime.min.time()) + _to_timedelta(time_value) + timedelta(days=1 if cint(next_day) else 0)


def out_is_next_day(in_time, out_time):
    """OUT before IN on the same day is impossible -> the OUT is on the next day."""
    if in_time in (None, "") or out_time in (None, ""):
        return False
    return _to_timedelta(out_time) < _to_timedelta(in_time)


def span_hours(date_value, in_time, out_time, out_next_day=0):
    """Worked hours from IN = D + in_time to OUT = (D [+1]) + out_time; 0 if a time is missing."""
    i, o = combine(date_value, in_time), combine(date_value, out_time, out_next_day)
    if not i or not o or o < i:
        return 0.0
    return flt((o - i).total_seconds() / 3600, 2)


def _to_timedelta(value):
    if isinstance(value, timedelta):
        return value
    if isinstance(value, datetime):
        return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
    if isinstance(value, str):
        h, m, *s = value.strip().split(":")
        return timedelta(hours=int(h), minutes=int(m), seconds=int(float(s[0])) if s else 0)
    return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)


# ── Holiday ─────────────────────────────────────────────────────


def get_holiday_info(employee, date_str):
    """(is_holiday, holiday_type) from the employee's holiday list (fallback: company default).

    holiday_type is "weekly_off", "holiday" or None.
    """
    from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

    holiday_list = get_holiday_list_for_employee(employee, raise_exception=False, as_on=getdate(date_str))
    if not holiday_list:
        return False, None
    row = frappe.db.get_value(
        "Holiday", {"parent": holiday_list, "holiday_date": getdate(date_str)}, ["name", "weekly_off"], as_dict=True
    )
    if not row:
        return False, None
    return True, ("weekly_off" if cint(row.weekly_off) else "holiday")


# ── Punches ─────────────────────────────────────────────────────


def fetch_punches(employees, range_start, range_end, device_id=None):
    """Return {employee: [punch, ...]} sorted by time, merged from both sources.

    employees: list of dicts with name and slhrm_allow_app_checkin.
    punch: frappe._dict(doctype, name, employee, time, log_type, source)
    """
    names = [e["name"] for e in employees]
    app_names = [e["name"] for e in employees if cint(e.get("slhrm_allow_app_checkin"))]
    result = {n: [] for n in names}
    if not names:
        return result

    filters = {"employee": ["in", names], "punch_time": ["between", [range_start, range_end]]}
    if device_id:
        filters["source_device"] = device_id
    for r in frappe.get_all(
        PUNCH_BIOMETRIC, filters=filters, fields=["name", "employee", "punch_time", "punch_type"], order_by="punch_time asc"
    ):
        result[r.employee].append(
            frappe._dict(
                doctype=PUNCH_BIOMETRIC, name=r.name, employee=r.employee,
                time=get_datetime(r.punch_time), log_type=r.punch_type, source="Biometric",
            )
        )

    if app_names:
        for r in frappe.get_all(
            PUNCH_APP,
            filters={"employee": ["in", app_names], "time": ["between", [range_start, range_end]], "log_type": ["in", ["IN", "OUT"]]},
            fields=["name", "employee", "time", "log_type"],
            order_by="time asc",
        ):
            result[r.employee].append(
                frappe._dict(
                    doctype=PUNCH_APP, name=r.name, employee=r.employee,
                    time=get_datetime(r.time), log_type=r.log_type, source="App",
                )
            )

    for punches in result.values():
        punches.sort(key=lambda p: p.time)
    return result


# ── Day computation ─────────────────────────────────────────────


def day_figures(shift_info, in_dt, out_dt, worked, ot_eligible, holiday_type, settings,
                short_leave=0, short_leave_min=0):
    """Early/late minutes, short-leave excuses and calculated OT for one employee-day.
    shift_info from get_shift_info (start/end None = no shift); in_dt / out_dt datetimes or None.
    Holiday / weekly off: all worked hours are OT, so no early/late minutes (nothing counts as late)."""
    working_day = holiday_type not in ("weekly_off", "holiday")
    mins = early_late_minutes(shift_info.start, shift_info.end, in_dt, out_dt) if shift_info.start and working_day else \
        dict.fromkeys(("early_in_min", "late_in_min", "early_out_min", "late_out_min"), 0)
    late_ok, early_ok = excused(mins["late_in_min"], mins["early_out_min"], short_leave, short_leave_min)
    calc_ot = calculate_ot_hours({
        "ot_eligible": ot_eligible, "worked_hours": worked, "holiday_type": holiday_type,
        "early_in_min": mins["early_in_min"], "late_out_min": mins["late_out_min"],
    }, settings)
    return dict(mins, late_in_excused=late_ok, early_out_excused=early_ok, calc_ot=calc_ot)


def compute_day(employee, date_str, shift_info, punches, ot_eligible, holiday, settings=None):
    """Compute IN/OUT, worked hours, OT and punch refs for one employee-day."""
    settings = settings or get_settings()
    overlap = shift_info.get("overlap") or ""
    in_window = [] if overlap else [p for p in punches if shift_info.window_start <= p.time <= shift_info.window_end]

    in_dt = in_window[0].time if in_window else None
    out_dt = in_window[-1].time if len(in_window) >= 2 else None
    worked = flt((out_dt - in_dt).total_seconds() / 3600, 2) if in_dt and out_dt else 0.0

    sources = {p.source for p in in_window}
    punch_source = "Both" if len(sources) > 1 else (next(iter(sources)) if sources else "")

    is_holiday, holiday_type = holiday
    figures = day_figures(shift_info, in_dt, out_dt, worked, ot_eligible,
                          holiday_type or ("holiday" if is_holiday else None), settings)

    refs = []
    for i, p in enumerate(in_window):
        used_as = "IN" if i == 0 else ("OUT" if i == len(in_window) - 1 else "Intermediate")
        refs.append({
            "employee": employee, "punch_doctype": p.doctype, "punch_log": p.name,
            "punch_time": str(p.time), "used_as": used_as,
        })

    warning = ""
    if overlap:
        warning = f"Overlapping shifts ({overlap}) — enter IN/OUT manually"
    elif len(punches) == 1 or len(in_window) == 1:
        warning = "Single punch only — missing OUT"
    elif punches and not in_window:
        warning = "Punches found but none inside the shift window"

    return {
        "in_time": in_dt.strftime("%H:%M:%S") if in_dt else None,
        "out_time": out_dt.strftime("%H:%M:%S") if out_dt else None,
        "out_next_day": 1 if out_dt and out_dt.date() > getdate(date_str) else 0,
        "worked_hours": worked,
        "shift_hours": shift_info.hours,
        "shift": shift_info.shift,
        "ot_eligible": 1 if cint(ot_eligible) else 0,
        **figures,
        "is_holiday": 1 if is_holiday else 0,
        "holiday_type": holiday_type,
        "punch_source": punch_source,
        "punch_count": len(in_window),
        "refs": refs,
        "warning": warning,
    }


def compute_for_employees(employees, date_str, shift_by_employee, device_id=None, settings=None):
    """Batch: {employee: compute_day(...)} for a list of employee dicts
    (name, slhrm_ot_eligible, slhrm_allow_app_checkin)."""
    settings = settings or get_settings()
    infos = {e["name"]: get_shift_info(shift_by_employee.get(e["name"]), date_str, settings) for e in employees}
    if not infos:
        return {}
    neighbours = neighbour_shifts(employees, date_str)
    prev_d, next_d = str(add_days(date_str, -1)), str(add_days(date_str, 1))
    for name, info in infos.items():
        prev_shift, next_shift = neighbours.get(name, (None, None))
        clip_windows(info,
                     get_shift_info(prev_shift, prev_d, settings) if prev_shift else None,
                     get_shift_info(next_shift, next_d, settings) if next_shift else None)
    range_start = min(i.window_start for i in infos.values())
    range_end = max(i.window_end for i in infos.values())
    punches = fetch_punches(employees, range_start, range_end, device_id=device_id)
    used = used_by_other_markers([p.name for ps in punches.values() for p in ps], date_str)
    if used:
        punches = {k: [p for p in ps if p.name not in used] for k, ps in punches.items()}

    out = {}
    for e in employees:
        out[e["name"]] = compute_day(
            e["name"], date_str, infos[e["name"]], punches.get(e["name"], []),
            e.get("slhrm_ot_eligible"), get_holiday_info(e["name"], date_str), settings,
        )
    return out


def worked_hours_from_times(in_time, out_time):
    """Worked hours between two Time values (timedelta/str); overnight if OUT < IN.
    Legacy helper (no shift date) — the marker uses span_hours with out_next_day."""
    if not in_time or not out_time:
        return 0.0
    diff = _to_timedelta(out_time) - _to_timedelta(in_time)
    if diff.total_seconds() < 0:
        diff += timedelta(days=1)
    return flt(diff.total_seconds() / 3600, 2)
