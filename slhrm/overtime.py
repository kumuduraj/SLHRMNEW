# PLACEHOLDER FORMULAS — replace when Raj provides Normal/Double OT formulas.
"""Single source of overtime (OT) math for SLHRM.

Every OT number in SLHRM (Attendance Marker, Payroll Worksheet, Additional Salary)
comes from these functions. They are pure: no DB reads or writes. Callers pass in
everything needed, including the SLHRM Settings document (or any object/dict with
the same attributes).

Two OT types:
- normal: extra hours worked on a working day beyond the shift length
- double: hours worked on a holiday or weekly off
"""

from frappe.utils import flt

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


def calculate_ot_hours(ctx, settings=None):
    """Return {"normal": hours, "double": hours} for one employee-day.

    ctx keys: employee, date, ot_eligible, shift, shift_hours, in_time, out_time,
              worked_hours, is_holiday, holiday_type ("weekly_off" / "holiday" / None),
              min_ot_hours (optional; overrides settings.overtime_threshold)
    settings: SLHRM Settings (reads overtime_threshold = minimum OT hours)

    Placeholder rules:
    - not eligible            -> 0 / 0
    - holiday or weekly off   -> normal 0, double = worked_hours
    - working day             -> normal = max(0, worked_hours - shift_hours), double 0
    - each type below the minimum OT hours -> 0
    """
    zero = {"normal": 0.0, "double": 0.0}
    if not flt(_get(ctx, "ot_eligible")):
        return zero

    worked = max(0.0, flt(_get(ctx, "worked_hours")))
    if not worked:
        return zero

    is_holiday = bool(_get(ctx, "is_holiday")) or _get(ctx, "holiday_type") in ("weekly_off", "holiday")
    if is_holiday:
        normal, double = 0.0, worked
    else:
        shift_hours = max(0.0, flt(_get(ctx, "shift_hours")))
        normal, double = max(0.0, worked - shift_hours), 0.0

    min_hours = _get(ctx, "min_ot_hours")
    if min_hours is None:
        min_hours = _get(settings, "overtime_threshold", 0)
    min_hours = flt(min_hours)
    if min_hours > 0:
        normal = normal if normal >= min_hours else 0.0
        double = double if double >= min_hours else 0.0

    return {"normal": _round(normal), "double": _round(double)}


def calculate_ot_rates(employee, base, settings):
    """Return {"normal_rate", "double_rate"} per hour for an employee.

    `employee` and `base` (monthly base salary) are accepted so the real formulas
    can use them; the placeholder only reads SLHRM Settings.
    """
    return {
        "normal_rate": _round(_get(settings, "default_ot_rate", 0)),
        "double_rate": _round(_get(settings, "default_double_ot_rate", 0)),
    }


def calculate_ot_amounts(normal_hours, double_hours, rates):
    """Return {"normal", "double"} amounts (hours x rate, 2 dp). Negative inputs count as 0."""
    normal_hours = max(0.0, flt(normal_hours))
    double_hours = max(0.0, flt(double_hours))
    normal_rate = max(0.0, flt(_get(rates, "normal_rate", 0)))
    double_rate = max(0.0, flt(_get(rates, "double_rate", 0)))
    return {
        "normal": _round(normal_hours * normal_rate),
        "double": _round(double_hours * double_rate),
    }
