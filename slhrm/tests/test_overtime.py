"""Unit tests for slhrm.overtime (pure functions, no DB records). v0.2.0: ONE OT type.

Run: bench --site <site> run-tests --app slhrm --module slhrm.tests.test_overtime
"""
from datetime import datetime

import frappe
from frappe.tests import UnitTestCase

from slhrm.overtime import (calculate_ot_amount, calculate_ot_hours, calculate_ot_rate, early_late_minutes,
                            excused)

D, N = "2026-11-02", "2026-11-03"
SETTINGS = frappe._dict(overtime_threshold=0, default_ot_rate=150)


def dt(day, hm):
    return datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M")


DAY = (dt(D, "08:00"), dt(D, "17:00"))      # Day Shift 08-17
NIGHT = (dt(D, "21:00"), dt(N, "06:00"))    # Night Shift 21-06


def ot(mins, worked, **kw):
    return calculate_ot_hours(dict({"ot_eligible": 1, "worked_hours": worked, **mins}, **kw), SETTINGS)


class TestEarlyLate(UnitTestCase):
    def test_early_in_late_out(self):  # spec 1: IN 07:30, OUT 18:15 -> 30 / 75, OT 1.75
        m = early_late_minutes(*DAY, dt(D, "07:30"), dt(D, "18:15"))
        self.assertEqual(m, {"early_in_min": 30, "late_in_min": 0, "early_out_min": 0, "late_out_min": 75})
        self.assertEqual(ot(m, 10.75), 1.75)

    def test_late_in_no_ot(self):  # spec 2: IN 08:20, OUT 17:00 -> late 20, OT 0
        m = early_late_minutes(*DAY, dt(D, "08:20"), dt(D, "17:00"))
        self.assertEqual(m, {"early_in_min": 0, "late_in_min": 20, "early_out_min": 0, "late_out_min": 0})
        self.assertEqual(ot(m, 8.67), 0.0)

    def test_night_shift_out_next_day(self):  # spec 4: 21-06, IN 20:45, OUT 06:30 (+1) -> 15 / 30, OT 0.75
        m = early_late_minutes(*NIGHT, dt(D, "20:45"), dt(N, "06:30"))
        self.assertEqual(m, {"early_in_min": 15, "late_in_min": 0, "early_out_min": 0, "late_out_min": 30})
        self.assertEqual(ot(m, 9.75), 0.75)

    def test_early_out(self):
        m = early_late_minutes(*DAY, dt(D, "08:00"), dt(D, "16:10"))
        self.assertEqual((m["early_out_min"], m["late_out_min"]), (50, 0))

    def test_missing_times(self):
        self.assertEqual(early_late_minutes(*DAY, None, None),
                         {"early_in_min": 0, "late_in_min": 0, "early_out_min": 0, "late_out_min": 0})
        m = early_late_minutes(*DAY, dt(D, "08:10"), None)
        self.assertEqual((m["late_in_min"], m["early_out_min"]), (10, 0))

    def test_partial_minutes_floor(self):
        m = early_late_minutes(*DAY, datetime(2026, 11, 2, 7, 59, 30), datetime(2026, 11, 2, 17, 0, 59))
        self.assertEqual((m["early_in_min"], m["late_out_min"]), (0, 0))


class TestShortLeave(UnitTestCase):
    def test_excused(self):  # spec 3: late 20 + short leave 30 -> excused
        self.assertEqual(excused(20, 0, 1, 30), (1, 0))

    def test_not_ticked(self):
        self.assertEqual(excused(20, 0, 0, 30), (0, 0))

    def test_too_long(self):
        self.assertEqual(excused(40, 0, 1, 30), (0, 0))

    def test_allowance_used_late_in_first(self):
        self.assertEqual(excused(20, 10, 1, 30), (1, 1))
        self.assertEqual(excused(20, 15, 1, 30), (1, 0))
        self.assertEqual(excused(40, 15, 1, 30), (0, 1))

    def test_nothing_to_excuse(self):
        self.assertEqual(excused(0, 0, 1, 30), (0, 0))


class TestOTHours(UnitTestCase):
    def test_holiday_all_hours(self):  # spec 5
        self.assertEqual(ot({}, 6, holiday_type="holiday"), 6.0)
        self.assertEqual(ot({}, 4, holiday_type="weekly_off"), 4.0)
        self.assertEqual(ot({}, 5, is_holiday=True), 5.0)

    def test_not_eligible(self):
        self.assertEqual(ot({"early_in_min": 30, "late_out_min": 75}, 10.75, ot_eligible=0), 0.0)
        self.assertEqual(ot({}, 6, ot_eligible=0, holiday_type="holiday"), 0.0)

    def test_minimum(self):
        m = {"early_in_min": 15, "late_out_min": 30}
        self.assertEqual(calculate_ot_hours(dict(m, ot_eligible=1, worked_hours=9.75), {"overtime_threshold": 1}), 0.0)
        self.assertEqual(calculate_ot_hours(dict(m, ot_eligible=1, worked_hours=9.75), {"overtime_threshold": 0.75}), 0.75)
        self.assertEqual(calculate_ot_hours({"ot_eligible": 1, "worked_hours": 0.5, "holiday_type": "holiday"},
                                            {"overtime_threshold": 1}), 0.0)
        self.assertEqual(ot(m, 9.75, min_ot_hours=1), 0.0)

    def test_zero_or_negative_worked(self):
        self.assertEqual(ot({"early_in_min": 30}, 0), 0.0)
        self.assertEqual(ot({"early_in_min": 30}, -2), 0.0)

    def test_rounding(self):
        self.assertEqual(ot({"early_in_min": 0, "late_out_min": 20}, 9.33), 0.33)

    def test_no_shift_working_day(self):  # no shift -> no early/late minutes -> no OT on a working day
        self.assertEqual(ot({}, 11), 0.0)


class TestOTRateAmount(UnitTestCase):
    def test_rate(self):
        self.assertEqual(calculate_ot_rate("EMP-TEST", 50000, SETTINGS), 150.0)
        self.assertEqual(calculate_ot_rate("EMP-TEST", 0, frappe._dict()), 0.0)

    def test_amount(self):
        self.assertEqual(calculate_ot_amount(2.5, 150), 375.0)
        self.assertEqual(calculate_ot_amount(1.333, 123.45), 164.56)
        self.assertEqual(calculate_ot_amount(-3, 150), 0.0)
        self.assertEqual(calculate_ot_amount(3, -1), 0.0)


class TestDayFigures(UnitTestCase):
    """slhrm.attendance.day_figures: no-shift warning (v0.2.1)."""

    def fig(self, start, end, holiday_type=None):
        from slhrm.attendance import day_figures
        info = frappe._dict(start=start, end=end)
        return day_figures(info, dt(D, "07:30"), dt(D, "18:15"), 10.75, 1, holiday_type, SETTINGS)

    def test_no_shift_working_day(self):
        f = self.fig(None, None)
        self.assertEqual((f["no_shift"], f["calc_ot"], f["late_in_min"], f["early_in_min"]), (1, 0.0, 0, 0))

    def test_no_shift_on_holiday_is_not_a_warning(self):
        f = self.fig(None, None, "holiday")
        self.assertEqual((f["no_shift"], f["calc_ot"]), (0, 10.75))

    def test_with_shift(self):
        f = self.fig(*DAY)
        self.assertEqual((f["no_shift"], f["calc_ot"], f["early_in_min"], f["late_out_min"]), (0, 1.75, 30, 75))
