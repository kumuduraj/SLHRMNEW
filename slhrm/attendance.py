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

NO SHIFT → PUNCH SESSIONS (v0.4.1, Raj 2026-11-17): the employee's punches from D−2 00:00 to D+2 00:00 (minus punches used
by another date's submitted marker) are grouped into sessions (split_sessions). Punches less than TAP_MINUTES apart are ONE
tap (double / triple taps). Sessions may only be split where two taps are rest_gap_hours (default 6) or more apart (shorter
gaps — breaks — always stay together); WHICH long gaps are splits is chosen for the whole window at once (least cost):
a one-tap session (missing punch) costs MISSING_COST; a session costs SPAN_COST per hour away from the standard day; every
long gap inside a session after the first costs EXTRA_REST_COST; punch-state hints (device states 0/4 = IN, 1/5 = OUT; app
log_type) are soft: a session starting on an OUT-only tap, ending on an IN-only tap, or holding an OUT→IN long gap inside
costs STATE_COST each. A session longer than max_session_hours (default 20) is only allowed when it has no long gap
(then "Long session"). (Real DUTCHPUB data: IN→OUT ≈ 9–10 h and OUT→IN ≈ 14 h both exceed 6 h; states are often wrong; the
2026-10-01 cutoff starts many employees on an OUT — a left-to-right pairing never recovers from one missing punch.) (Real DUTCHPUB data: both IN→OUT ≈ 9–10 h and
OUT→IN ≈ 14 h exceed 6 h, and device punch states are unreliable, so a plain gap split cannot pair IN/OUT.) The look-back
starts at D−2 so that D−1's session is paired from its own IN. A session belongs to the date of its FIRST punch; D's row = the first session that starts on D:
IN = its first punch, OUT = its last punch (OUT +1 when on D+1). A session that started on D−1 and ends after midnight is
D−1's (never D's IN). Longer than max_session_hours (default 20) → "Long session". More than one session starting on D →
warning (only the first is used; the supervisor adjusts). Shift employees keep the shift-window logic.
MISSING PUNCH: a Present / Short Leave row with IN but no OUT (or OUT but no IN) → missing_punch, worked / short / OT 0.
Every row gets context for the row editor: previous punch before IN, next punch after OUT, the session's punches + range.
OT hours, short hours and early/late minutes come from slhrm.overtime (the only OT math) via day_figures().
"""
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, cint, cstr, flt, get_datetime, getdate

from slhrm.overtime import STATUS_ABSENT, STATUS_PRESENT, WORKED_STATUSES, calculate_day_hours, early_late_minutes, excused

DEFAULT_REST_GAP_HOURS = 6
DEFAULT_MAX_SESSION_HOURS = 20
TAP_MINUTES = 15  # punches closer than this are one tap
MISSING_COST, SPAN_COST, EXTRA_REST_COST, STATE_COST = 6.0, 0.2, 8.0, 2.0
IN_STATES, OUT_STATES = (0, 4), (1, 5)

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
        PUNCH_BIOMETRIC, filters=filters, fields=["name", "employee", "punch_time", "punch_type", "source_device",
                                                  "device_punch_state"],
        order_by="punch_time asc"
    ):
        result[r.employee].append(
            frappe._dict(
                doctype=PUNCH_BIOMETRIC, name=r.name, employee=r.employee,
                time=get_datetime(r.punch_time), log_type=r.punch_type, source="Biometric", device=r.source_device,
                state=r.device_punch_state,
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
                short_leave=0, short_leave_min=0, status=STATUS_PRESENT):
    """Early/late minutes (information), short-leave excuses, calculated OT and short hours for one employee-day
    (rule: slhrm.overtime.calculate_day_hours). shift_info from get_shift_info (start/end None = no shift);
    in_dt / out_dt datetimes or None. Holiday / weekly off: all worked hours are OT, no early/late minutes."""
    status = status or STATUS_PRESENT
    working_day = holiday_type not in ("weekly_off", "holiday")
    missing = 1 if status in WORKED_STATUSES and (in_dt is None) != (out_dt is None) else 0
    mins = early_late_minutes(shift_info.start, shift_info.end, in_dt, out_dt) if shift_info.start and working_day else \
        dict.fromkeys(("early_in_min", "late_in_min", "early_out_min", "late_out_min"), 0)
    late_ok, early_ok = excused(mins["late_in_min"], mins["early_out_min"], short_leave, short_leave_min)
    hours = calculate_day_hours({
        "status": status, "ot_eligible": ot_eligible, "worked_hours": worked, "holiday_type": holiday_type,
        "short_leave": short_leave, "short_leave_min": short_leave_min,
    }, settings)
    if missing:  # IN without OUT (or OUT without IN): nothing is counted until the supervisor fills the missing time
        hours = {"calc_ot": 0.0, "short_hours": 0.0}
    # warning only (v0.3.1): OT / short hours still come from the worked hours; early/late minutes stay blank
    no_shift = 1 if working_day and not shift_info.start and status in WORKED_STATUSES else 0
    return dict(mins, late_in_excused=late_ok, early_out_excused=early_ok, no_shift=no_shift, missing_punch=missing, **hours)


def _hint(p):
    """(in, out) hint of one punch: device state 0/4 → IN, 1/5 → OUT; app log_type IN / OUT."""
    st = p.get("state")
    if st is not None and st != "":
        return cint(st) in IN_STATES, cint(st) in OUT_STATES
    lt = cstr(p.get("log_type")).upper() if p.get("doctype") == PUNCH_APP else ""
    return lt == "IN", lt == "OUT"


def _taps(punches):
    """Sorted punches → taps: [{punches, start, end, in_hint, out_hint}] (punches < TAP_MINUTES apart = one tap)."""
    tap = timedelta(minutes=TAP_MINUTES)
    out = []
    for p in sorted(punches, key=lambda x: x.time):
        i, o = _hint(p)
        if out and p.time - out[-1]["end"] < tap:
            t = out[-1]
            t["punches"].append(p)
            t["end"] = p.time
            t["in_hint"] |= i
            t["out_hint"] |= o
        else:
            out.append({"punches": [p], "start": p.time, "end": p.time, "in_hint": i, "out_hint": o})
    return out


def _session_cost(taps, rest, longest, std_hours):
    """Cost of one session made of consecutive taps, or None when not allowed."""
    if len(taps) == 1:
        return MISSING_COST
    span = (taps[-1]["end"] - taps[0]["start"]).total_seconds() / 3600
    long_gaps = [k for k in range(1, len(taps)) if taps[k]["start"] - taps[k - 1]["end"] >= rest]
    if span > longest and long_gaps:
        return None
    cost = SPAN_COST * abs(span - std_hours) + EXTRA_REST_COST * max(0, len(long_gaps) - 1)
    first, last = taps[0], taps[-1]
    if first["out_hint"] and not first["in_hint"]:
        cost += STATE_COST
    if last["in_hint"] and not last["out_hint"]:
        cost += STATE_COST
    for k in long_gaps:  # an OUT → IN long gap inside a session is a rest, not work
        a, b = taps[k - 1], taps[k]
        if a["out_hint"] and not a["in_hint"] and b["in_hint"] and not b["out_hint"]:
            cost += STATE_COST
    return cost


def split_sessions(punches, rest_gap_hours=DEFAULT_REST_GAP_HOURS, max_session_hours=DEFAULT_MAX_SESSION_HOURS,
                   std_hours=9.0):
    """Pure: punches → sessions (lists of punches), least total cost over the window (module docstring).
    Splits only where consecutive taps are >= rest_gap_hours apart."""
    rest = timedelta(hours=flt(rest_gap_hours) or DEFAULT_REST_GAP_HOURS)
    longest = flt(max_session_hours) or DEFAULT_MAX_SESSION_HOURS
    taps = _taps(punches)
    n = len(taps)
    if not n:
        return []
    cuts = [0] + [k for k in range(1, n) if taps[k]["start"] - taps[k - 1]["end"] >= rest] + [n]
    best = {0: (0.0, None)}  # cut position → (cost, previous cut)
    for b in cuts[1:]:
        for a in [c for c in cuts if c < b]:
            if a not in best:
                continue
            c = _session_cost(taps[a:b], rest, longest, flt(std_hours) or 9.0)
            if c is not None and (b not in best or best[a][0] + c < best[b][0] - 1e-9):
                best[b] = (best[a][0] + c, a)
    if n not in best:  # cannot happen (single-tap sessions are always allowed); be safe
        return [t["punches"] for t in taps]
    bounds, b = [], n
    while b:
        a = best[b][1]
        bounds.append((a, b))
        b = a
    return [[p for t in taps[a:b] for p in t["punches"]] for a, b in reversed(bounds)]


def session_hint_warning(session):
    """Warning when the chosen IN is a punch the device recorded as OUT only (staff often press IN for both punches, so
    an IN-type OUT is normal and not reported)."""
    taps = _taps(session)
    if len(taps) >= 2 and taps[0]["out_hint"] and not taps[0]["in_hint"]:
        return "IN is a punch the device recorded as OUT — check"
    return ""


def sessions_for_day(punches, date_str, rest_gap_hours=DEFAULT_REST_GAP_HOURS, max_session_hours=DEFAULT_MAX_SESSION_HOURS,
                     std_hours=9.0):
    """Pure: the sessions whose FIRST punch is on date_str (in order)."""
    d = getdate(date_str)
    return [s for s in split_sessions(punches, rest_gap_hours, max_session_hours, std_hours) if s[0].time.date() == d]


def _fmt_punch(p, device_names):
    src = device_names.get(p.get("device")) or p.get("device") or p.source
    return f"{p.time:%d-%m %H:%M:%S}  {src}"


def punch_context(all_punches, used, in_dt, out_dt, device_names):
    """Row-editor context: previous punch before IN, next punch after OUT, the used punches (time + device), range."""
    ordered = sorted(all_punches, key=lambda x: x.time)
    first = in_dt or out_dt
    last = out_dt or in_dt
    prev = [p for p in ordered if first and p.time < first and p not in used]
    nxt = [p for p in ordered if last and p.time > last and p not in used]
    return {
        "prev_punch": str(prev[-1].time) if prev else None,
        "next_punch": str(nxt[0].time) if nxt else None,
        "session_range": f"{used[0].time:%d-%m-%Y %H:%M} → {used[-1].time:%d-%m-%Y %H:%M}" if used else "",
        "session_punches": "\n".join(_fmt_punch(p, device_names) for p in used),
    }


def compute_day_session(employee, date_str, punches, ot_eligible, holiday, settings, device_names=None):
    """No shift: D's row from punch sessions (see module docstring). Same keys as compute_day + context."""
    gap = flt(settings.get("rest_gap_hours")) or DEFAULT_REST_GAP_HOURS
    max_h = flt(settings.get("max_session_hours")) or DEFAULT_MAX_SESSION_HOURS
    todays = sessions_for_day(punches, date_str, gap, max_h, flt(settings.get("standard_day_hours")) or 9.0)
    session = todays[0] if todays else []
    in_dt = session[0].time if session else None
    out_dt = session[-1].time if len(session) >= 2 else None
    worked = flt((out_dt - in_dt).total_seconds() / 3600, 2) if in_dt and out_dt else 0.0
    is_holiday, holiday_type = holiday
    status = STATUS_PRESENT if session else STATUS_ABSENT
    info = frappe._dict(start=None, end=None, hours=0.0, shift="")
    figures = day_figures(info, in_dt, out_dt, worked, ot_eligible, holiday_type or ("holiday" if is_holiday else None),
                          settings, status=status)
    long_session = 1 if worked > max_h else 0  # only possible without a long gap inside
    warnings = []
    if len(session) == 1:
        warnings.append("Single punch only — missing OUT")
    if long_session:
        warnings.append(f"Long session ({worked} h > {max_h:g} h) — check IN / OUT")
    elif worked > MAX_PLAUSIBLE_HOURS:
        warnings.append(f"Unusually long session ({worked} h) — check IN / OUT")
    if session_hint_warning(session):
        warnings.append(session_hint_warning(session))
    if len(todays) > 1:
        warnings.append("Another session on this day starts " + ", ".join(f"{s[0].time:%H:%M}" for s in todays[1:])
                        + f" (gap ≥ {gap:g} h) — only the first is used")
    sources = {p.source for p in session}
    refs = [{"employee": employee, "punch_doctype": p.doctype, "punch_log": p.name, "punch_time": str(p.time),
             "used_as": "IN" if i == 0 else ("OUT" if i == len(session) - 1 else "Intermediate")} for i, p in enumerate(session)]
    return {
        "in_time": in_dt.strftime("%H:%M:%S") if in_dt else None,
        "out_time": out_dt.strftime("%H:%M:%S") if out_dt else None,
        "out_next_day": 1 if out_dt and out_dt.date() > getdate(date_str) else 0,
        "worked_hours": worked, "shift_hours": 0.0, "shift": "", "ot_eligible": 1 if cint(ot_eligible) else 0,
        **figures, "long_session": long_session, "attendance_status": status,
        "is_holiday": 1 if is_holiday else 0, "holiday_type": holiday_type,
        "punch_source": "Both" if len(sources) > 1 else (next(iter(sources)) if sources else ""),
        "punch_count": len(session), "refs": refs, "warning": "; ".join(warnings),
        **punch_context(punches, session, in_dt, out_dt, device_names or {}),
    }


def compute_day(employee, date_str, shift_info, punches, ot_eligible, holiday, settings=None, device_names=None):
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
    status = STATUS_PRESENT if in_window else STATUS_ABSENT  # same default as the marker form
    figures = day_figures(shift_info, in_dt, out_dt, worked, ot_eligible,
                          holiday_type or ("holiday" if is_holiday else None), settings, status=status)

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
        **punch_context(punches, in_window, in_dt, out_dt, device_names or {}),
        "long_session": 0,
        "in_time": in_dt.strftime("%H:%M:%S") if in_dt else None,
        "out_time": out_dt.strftime("%H:%M:%S") if out_dt else None,
        "out_next_day": 1 if out_dt and out_dt.date() > getdate(date_str) else 0,
        "worked_hours": worked,
        "shift_hours": shift_info.hours,
        "shift": shift_info.shift,
        "ot_eligible": 1 if cint(ot_eligible) else 0,
        **figures,
        "attendance_status": status,
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
    day = datetime.combine(getdate(date_str), datetime.min.time())
    session_start, session_end = day - timedelta(days=2), day + timedelta(days=2)  # D−2 00:00 … D+2 00:00
    range_start = min([i.window_start for i in infos.values()] + [session_start])
    range_end = max([i.window_end for i in infos.values()] + [session_end - timedelta(microseconds=1)])
    punches = fetch_punches(employees, range_start, range_end, device_id=device_id)
    used = used_by_other_markers([p.name for ps in punches.values() for p in ps], date_str)
    if used:
        punches = {k: [p for p in ps if p.name not in used] for k, ps in punches.items()}

    device_names = dict(frappe.get_all("Biometric Device", fields=["name", "device_name"], as_list=True))
    out = {}
    for e in employees:
        info, mine = infos[e["name"]], punches.get(e["name"], [])
        holiday = get_holiday_info(e["name"], date_str)
        if info.start is None:  # no shift → punch sessions
            out[e["name"]] = compute_day_session(e["name"], date_str, mine, e.get("slhrm_ot_eligible"), holiday, settings,
                                                 device_names)
        else:
            out[e["name"]] = compute_day(e["name"], date_str, info, mine, e.get("slhrm_ot_eligible"), holiday, settings,
                                         device_names)
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


# ── OT eligibility default (v0.4.1) ─────────────────────────────


def employee_ot_default(doc, method=None):
    """doc_events Employee.before_insert: SLHRM Settings "OT eligible by default" (default on) ticks
    slhrm_ot_eligible on new employees. HR can untick it afterwards; set doc.flags.slhrm_no_ot_default to skip."""
    if doc.flags.get("slhrm_no_ot_default"):
        return
    if cint(frappe.db.get_single_value("SLHRM Settings", "ot_eligible_by_default")):
        doc.slhrm_ot_eligible = 1


def tick_ot_eligible(dry_run=1):
    """bench execute (dry run first): tick slhrm_ot_eligible on every Active employee that has it unticked.
    Returns {"count", "by_branch", "employees"}; dry_run=0 writes (db.set_value, modified updated) and commits."""
    rows = frappe.get_all("Employee", filters={"status": "Active", "slhrm_ot_eligible": 0},
                          fields=["name", "employee_name", "branch"], order_by="branch, employee_name")
    by_branch = {}
    for r in rows:
        by_branch[r.branch or "-"] = by_branch.get(r.branch or "-", 0) + 1
    if not cint(dry_run):
        for r in rows:
            frappe.db.set_value("Employee", r.name, "slhrm_ot_eligible", 1)
        frappe.db.commit()
    out = {"dry_run": cint(dry_run), "count": len(rows), "by_branch": by_branch,
           "ticked_now": frappe.db.count("Employee", {"status": "Active", "slhrm_ot_eligible": 1})}
    print(out)
    return out

