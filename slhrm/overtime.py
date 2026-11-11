"""Single source of overtime (OT), short-hours, OT-rate and No Pay math for SLHRM.

Every OT / short / No Pay number in SLHRM (Attendance Marker, Payroll Worksheet, Additional Salary) comes
from these functions. They are pure: no DB reads or writes. Callers pass in everything needed,
including the SLHRM Settings document (or any object/dict with the same attributes).

v0.3.0 (Phase 3.4) daily rule, per Attendance Marker row:
    counted only for status Present / Short Leave (Absent, Leave, No Pay -> OT 0, short 0)
    worked  = OUT - IN (incl. OUT +1)
    working day:
        extra = worked - standard_day_hours (9)
        OT    = extra when extra >= ot_min_daily_hours (1.0) — ALL of it (10:15 worked -> 1.25); else 0
        short = standard_day_hours - worked - approved short-leave minutes / 60   (floor 0, no minimum)
    holiday / weekly off: OT = all worked hours with the same >= ot_min_daily_hours rule; short 0
    working day without a shift: OT 0, short 0 (warning "No shift"; HR assigns shifts)
    not OT-eligible: OT 0 (short hours still shown)
Early In / Late In / Early Out / Late Out minutes are information only (Lates highlighting).
Short leave (row tick or status Short Leave + minutes): excuses Late In first, then Early Out, and reduces
the short hours.

Month (Payroll Worksheet): net OT = max(0, OT - short); short balance = max(0, short - OT) (information only).
OT rate per hour = Basic / 200 x 1.5 (Basic = package Basic Salary of the period, not prorated).
No Pay per day = SLHRM Settings no_pay_day_formula over the period's unprorated earnings by abbreviation
(default "(BS + BA) / 30" — PLACEHOLDER until Raj confirms).
"""

from frappe.utils import cint, flt

PRECISION = 2
EPSILON = 1e-9

DEFAULT_STANDARD_DAY_HOURS = 9.0
DEFAULT_OT_MIN_DAILY_HOURS = 1.0
OT_RATE_DIVISOR = 200
OT_RATE_MULTIPLIER = 1.5
OT_BASIC_ABBR = "BS"  # Basic Salary
DEFAULT_NO_PAY_DAY_FORMULA = "(BS + BA) / 30"  # PLACEHOLDER — to be confirmed by Raj

STATUS_PRESENT = "Present"
STATUS_ABSENT = "Absent"
STATUS_LEAVE = "Leave"
STATUS_NO_PAY = "No Pay"
STATUS_SHORT_LEAVE = "Short Leave"
STATUSES = (STATUS_PRESENT, STATUS_ABSENT, STATUS_LEAVE, STATUS_NO_PAY, STATUS_SHORT_LEAVE)
WORKED_STATUSES = (STATUS_PRESENT, STATUS_SHORT_LEAVE)  # only these count OT / short hours
# Marker status -> HRMS Attendance status (HRMS has no No Pay / Short Leave). Payroll Settings
# payroll_based_on = Leave, so an HRMS "Absent" does not cut pay: No Pay is deducted by the worksheet.
HRMS_STATUS = {STATUS_PRESENT: "Present", STATUS_SHORT_LEAVE: "Present", STATUS_ABSENT: "Absent",
               STATUS_NO_PAY: "Absent", STATUS_LEAVE: "On Leave"}


def _get(obj, key, default=None):
    """Read `key` from a dict or an attribute-style object (frappe._dict / Document)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _round(value):
    return flt(value, PRECISION)


def standard_day_hours(settings):
    """SLHRM Settings standard_day_hours; unset / 0 -> 9."""
    return flt(_get(settings, "standard_day_hours")) or DEFAULT_STANDARD_DAY_HOURS


def ot_min_daily_hours(settings):
    """SLHRM Settings ot_min_daily_hours; unset -> 1.0 (0 = no minimum)."""
    value = _get(settings, "ot_min_daily_hours")
    return DEFAULT_OT_MIN_DAILY_HOURS if value in (None, "") else max(0.0, flt(value))


def _minutes(later, earlier):
    """Whole minutes later - earlier, 0 when not positive or a value is missing."""
    if later is None or earlier is None:
        return 0
    seconds = (later - earlier).total_seconds()
    return int(seconds // 60) if seconds > 0 else 0


def early_late_minutes(shift_start, shift_end, in_dt, out_dt):
    """{early_in_min, late_in_min, early_out_min, late_out_min} (ints) from datetimes — information only."""
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


def is_holiday_ctx(ctx):
    return bool(_get(ctx, "is_holiday")) or _get(ctx, "holiday_type") in ("weekly_off", "holiday")


def calculate_day_hours(ctx, settings=None):
    """{"calc_ot": h, "short_hours": h} (2 dp) for one employee-day (rule in the module docstring).

    ctx keys: status (default Present), worked_hours, ot_eligible, holiday_type ("weekly_off" / "holiday" / None)
              or is_holiday, has_shift (default True), short_leave, short_leave_min
    """
    zero = {"calc_ot": 0.0, "short_hours": 0.0}
    status = _get(ctx, "status") or STATUS_PRESENT
    if status not in WORKED_STATUSES:
        return zero
    worked = max(0.0, flt(_get(ctx, "worked_hours")))
    min_ot = ot_min_daily_hours(settings)
    eligible = bool(flt(_get(ctx, "ot_eligible")))

    if is_holiday_ctx(ctx):
        ot = worked if eligible and worked > 0 and worked + EPSILON >= min_ot else 0.0
        return {"calc_ot": _round(ot), "short_hours": 0.0}

    has_shift = _get(ctx, "has_shift")
    if has_shift is not None and not has_shift:
        return zero

    std = standard_day_hours(settings)
    extra = worked - std
    ot = extra if eligible and extra > EPSILON and extra + EPSILON >= min_ot else 0.0
    leave = cint(_get(ctx, "short_leave")) or status == STATUS_SHORT_LEAVE
    excused_hours = max(0, cint(_get(ctx, "short_leave_min"))) / 60.0 if leave else 0.0
    short = max(0.0, std - worked - excused_hours)
    return {"calc_ot": _round(ot), "short_hours": _round(short)}


def calculate_ot_hours(ctx, settings=None):
    """Calculated daily OT hours only (see calculate_day_hours)."""
    return calculate_day_hours(ctx, settings)["calc_ot"]


def net_ot_hours(ot_hours, short_hours):
    """Month: max(0, OT - short)."""
    return _round(max(0.0, flt(ot_hours) - flt(short_hours)))


def short_balance(ot_hours, short_hours):
    """Month: short hours not covered by OT (information only, never deducted)."""
    return _round(max(0.0, flt(short_hours) - flt(ot_hours)))


def calculate_ot_rate(employee, basic, settings=None):
    """OT rate per hour = Basic / 200 x 1.5 (2 dp). `basic` = the employee's package Basic Salary for the
    period, not prorated. `employee` / `settings` are accepted for future per-employee rules."""
    return _round(max(0.0, flt(basic)) / OT_RATE_DIVISOR * OT_RATE_MULTIPLIER)


def calculate_ot_amount(hours, rate):
    """hours x rate (2 dp). Negative inputs count as 0."""
    return _round(max(0.0, flt(hours)) * max(0.0, flt(rate)))


def no_pay_day_formula(settings):
    return (_get(settings, "no_pay_day_formula") or "").strip() or DEFAULT_NO_PAY_DAY_FORMULA


def calculate_no_pay_rate(values, settings=None):
    """No Pay per-day rate, UNROUNDED (amount = round(days x rate, 2); the rate is shown rounded).
    values = {abbreviation: unprorated period amount} (missing abbreviations count as 0).
    Raises frappe.ValidationError-like exceptions from safe_eval on a bad formula (caller reports them)."""
    from frappe.utils.safe_exec import safe_eval

    names = {k: flt(v) for k, v in (values or {}).items() if k}

    class _Zero(dict):
        """An abbreviation (starts upper-case) missing from the period counts as 0; other names
        (flt, round, max …) fall through to safe_eval's globals."""
        def __missing__(self, key):
            if key[:1].isupper():
                return 0.0
            raise KeyError(key)

    helpers = {"flt": flt, "cint": cint, "round": round, "min": min, "max": max, "abs": abs}
    rate = safe_eval(no_pay_day_formula(settings), helpers, _Zero(names))
    return max(0.0, flt(rate))


def calculate_no_pay_amount(days, rate):
    """days x per-day rate (rate unrounded) -> 2 dp."""
    return _round(max(0.0, flt(days)) * max(0.0, flt(rate)))
