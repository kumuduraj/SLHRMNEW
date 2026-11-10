"""Single source of overtime (OT) and early/late math for SLHRM (v0.2.0: ONE OT type).

Every OT number in SLHRM (Attendance Marker, Payroll Worksheet, Additional Salary) comes from
these functions. They are pure: no DB reads or writes. Callers pass in everything needed,
including the SLHRM Settings document (or any object/dict with the same attributes).

Per employee-day (shift start S, shift end E, IN, OUT incl. "OUT +1"), whole minutes:
    early_in_min  = IN before S        late_in_min   = IN after S
    early_out_min = OUT before E       late_out_min  = OUT after E
OT hours:
    working day            -> (early_in_min + late_out_min) / 60
    holiday / weekly off   -> all worked hours
    no shift times         -> 0 on a working day (nothing to compare with)
    not OT-eligible        -> 0
    below the minimum OT (SLHRM Settings overtime_threshold, hours) -> 0
Short leave (row tick + minutes): the allowance is used by late_in first, then early_out; a value
that fits in what is left is "excused" (not highlighted, not counted in Lates).
"""

from frappe.utils import cint, flt

PRECISION = 2


def _get(obj, key, default=None):
    """Read `key` from a dict or an attribute-style object (frappe._dict / Document)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _round(value):
    return flt(value, PRECISION)


def _minutes(later, earlier):
    """Whole minutes later - earlier, 0 when not positive or a value is missing."""
    if later is None or earlier is None:
        return 0
    seconds = (later - earlier).total_seconds()
    return int(seconds // 60) if seconds > 0 else 0


def early_late_minutes(shift_start, shift_end, in_dt, out_dt):
    """{early_in_min, late_in_min, early_out_min, late_out_min} (ints) from datetimes."""
    return {
        "early_in_min": _minutes(shift_start, in_dt) if in_dt else 0,
        "late_in_min": _minutes(in_dt, shift_start) if in_dt else 0,
        "early_out_min": _minutes(shift_end, out_dt) if out_dt else 0,
        "late_out_min": _minutes(out_dt, shift_end) if out_dt else 0,
    }


def excused(late_in_min, early_out_min, short_leave=0, short_leave_min=0):
    """(late_in_excused, early_out_excused) for a short-leave allowance in minutes."""
    allowance = max(0, cint(short_leave_min)) if cint(short_leave) else 0
    late_ok = 0 < cint(late_in_min) <= allowance
    if late_ok:
        allowance -= cint(late_in_min)
    early_ok = 0 < cint(early_out_min) <= allowance
    return (1 if late_ok else 0), (1 if early_ok else 0)


def calculate_ot_hours(ctx, settings=None):
    """OT hours (float, 2 dp) for one employee-day.

    ctx keys: ot_eligible, worked_hours, is_holiday, holiday_type ("weekly_off" / "holiday" / None),
              early_in_min, late_out_min, min_ot_hours (optional; overrides settings.overtime_threshold)
    """
    if not flt(_get(ctx, "ot_eligible")):
        return 0.0
    worked = max(0.0, flt(_get(ctx, "worked_hours")))
    if not worked:
        return 0.0

    is_holiday = bool(_get(ctx, "is_holiday")) or _get(ctx, "holiday_type") in ("weekly_off", "holiday")
    if is_holiday:
        hours = worked
    else:
        minutes = max(0, cint(_get(ctx, "early_in_min"))) + max(0, cint(_get(ctx, "late_out_min")))
        hours = min(minutes / 60.0, worked)

    min_hours = _get(ctx, "min_ot_hours")
    if min_hours is None:
        min_hours = _get(settings, "overtime_threshold", 0)
    if flt(min_hours) > 0 and hours < flt(min_hours):
        hours = 0.0
    return _round(hours)


def calculate_ot_rate(employee, base, settings):
    """OT rate per hour. `employee` / `base` are accepted for a future formula; today the rate is
    SLHRM Settings default_ot_rate."""
    return _round(_get(settings, "default_ot_rate", 0))


def calculate_ot_amount(hours, rate):
    """hours x rate (2 dp). Negative inputs count as 0."""
    return _round(max(0.0, flt(hours)) * max(0.0, flt(rate)))
