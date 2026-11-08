# slhrm/attendance.py
"""Attendance-day computation shared by the Attendance Marker loader, the row
recalculation endpoint and the Attendance Marker controller.

Punch sources:
- Biometric Punch Log for every employee
- Employee Checkin (log_type IN/OUT) only for employees with slhrm_allow_app_checkin = 1

Window: shift start - shift_match_window_before  ...  shift end + ot_punch_window_after.
OT hours come from slhrm.overtime (the only OT math).
"""
from datetime import datetime, timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, getdate

from slhrm.overtime import calculate_ot_hours

DEFAULT_WINDOW_BEFORE = 120
DEFAULT_OT_WINDOW_AFTER = 360

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


def _to_timedelta(value):
    if isinstance(value, timedelta):
        return value
    if isinstance(value, str):
        h, m, *s = value.split(":")
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


def compute_day(employee, date_str, shift_info, punches, ot_eligible, holiday, settings=None):
    """Compute IN/OUT, worked hours, OT and punch refs for one employee-day."""
    settings = settings or get_settings()
    in_window = [p for p in punches if shift_info.window_start <= p.time <= shift_info.window_end]

    in_dt = in_window[0].time if in_window else None
    out_dt = in_window[-1].time if len(in_window) >= 2 else None
    worked = flt((out_dt - in_dt).total_seconds() / 3600, 2) if in_dt and out_dt else 0.0

    sources = {p.source for p in in_window}
    punch_source = "Both" if len(sources) > 1 else (next(iter(sources)) if sources else "")

    is_holiday, holiday_type = holiday
    ot = calculate_ot_hours(
        {
            "employee": employee, "date": date_str, "ot_eligible": ot_eligible,
            "shift": shift_info.shift, "shift_hours": shift_info.hours,
            "in_time": in_dt, "out_time": out_dt, "worked_hours": worked,
            "is_holiday": is_holiday, "holiday_type": holiday_type,
        },
        settings,
    )

    refs = []
    for i, p in enumerate(in_window):
        used_as = "IN" if i == 0 else ("OUT" if i == len(in_window) - 1 else "Intermediate")
        refs.append({
            "employee": employee, "punch_doctype": p.doctype, "punch_log": p.name,
            "punch_time": str(p.time), "used_as": used_as,
        })

    warning = ""
    if len(punches) == 1 or len(in_window) == 1:
        warning = "Single punch only — missing OUT"
    elif punches and not in_window:
        warning = "Punches found but none inside the shift window"

    return {
        "in_time": in_dt.strftime("%H:%M:%S") if in_dt else None,
        "out_time": out_dt.strftime("%H:%M:%S") if out_dt else None,
        "worked_hours": worked,
        "shift_hours": shift_info.hours,
        "shift": shift_info.shift,
        "ot_eligible": 1 if cint(ot_eligible) else 0,
        "calc_normal_ot": ot["normal"],
        "calc_double_ot": ot["double"],
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
    range_start = min(i.window_start for i in infos.values())
    range_end = max(i.window_end for i in infos.values())
    punches = fetch_punches(employees, range_start, range_end, device_id=device_id)

    out = {}
    for e in employees:
        out[e["name"]] = compute_day(
            e["name"], date_str, infos[e["name"]], punches.get(e["name"], []),
            e.get("slhrm_ot_eligible"), get_holiday_info(e["name"], date_str), settings,
        )
    return out


def worked_hours_from_times(in_time, out_time):
    """Worked hours between two Time values (timedelta/str); overnight if OUT < IN."""
    if not in_time or not out_time:
        return 0.0
    diff = _to_timedelta(out_time) - _to_timedelta(in_time)
    if diff.total_seconds() < 0:
        diff += timedelta(days=1)
    return flt(diff.total_seconds() / 3600, 2)
