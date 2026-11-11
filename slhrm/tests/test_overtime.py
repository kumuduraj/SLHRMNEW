"""Unit tests for slhrm.overtime (pure functions, no DB records). v0.3.0: 9-hour day rule.

Run: CI=1 bench --site <site> run-tests --app slhrm --module slhrm.tests.test_overtime --skip-before-tests
"""
from datetime import datetime

import frappe
from frappe.tests import UnitTestCase

from slhrm.overtime import (calculate_day_hours, calculate_no_pay_amount, calculate_no_pay_rate, calculate_ot_amount,
                            calculate_ot_hours, calculate_ot_rate, early_late_minutes, excused, net_ot_hours,
                            short_balance)

D, N = "2026-11-02", "2026-11-03"
SETTINGS = frappe._dict(standard_day_hours=9, ot_min_daily_hours=1)


def dt(day, hm):
    return datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M")


DAY = (dt(D, "08:00"), dt(D, "17:00"))      # Day Shift 08-17
NIGHT = (dt(D, "21:00"), dt(N, "06:00"))    # Night Shift 21-06


def day(worked, settings=SETTINGS, **kw):
    r = calculate_day_hours(dict({"ot_eligible": 1, "worked_hours": worked, "has_shift": True}, **kw), settings)
    return r["calc_ot"], r["short_hours"]


class TestEarlyLate(UnitTestCase):
    """Early / late minutes stay as information."""

    def test_early_in_late_out(self):
        m = early_late_minutes(*DAY, dt(D, "07:30"), dt(D, "18:15"))
        self.assertEqual(m, {"early_in_min": 30, "late_in_min": 0, "early_out_min": 0, "late_out_min": 75})

    def test_night_shift_out_next_day(self):
        m = early_late_minutes(*NIGHT, dt(D, "20:45"), dt(N, "06:30"))
        self.assertEqual(m, {"early_in_min": 15, "late_in_min": 0, "early_out_min": 0, "late_out_min": 30})

    def test_missing_times(self):
        self.assertEqual(early_late_minutes(*DAY, None, None),
                         {"early_in_min": 0, "late_in_min": 0, "early_out_min": 0, "late_out_min": 0})

    def test_partial_minutes_floor(self):
        m = early_late_minutes(*DAY, datetime(2026, 11, 2, 7, 59, 30), datetime(2026, 11, 2, 17, 0, 59))
        self.assertEqual((m["early_in_min"], m["late_out_min"]), (0, 0))


class TestShortLeaveExcuse(UnitTestCase):
    def test_excused(self):
        self.assertEqual(excused(20, 0, 1, 30), (1, 0))
        self.assertEqual(excused(20, 0, 0, 30), (0, 0))
        self.assertEqual(excused(40, 0, 1, 30), (0, 0))
        self.assertEqual(excused(20, 10, 1, 30), (1, 1))
        self.assertEqual(excused(40, 15, 1, 30), (0, 1))


class TestDayRule(UnitTestCase):
    def test_1_extra_below_minimum(self):  # 08:00-17:30 = 9.5 h -> OT 0, short 0
        self.assertEqual(day(9.5), (0.0, 0.0))

    def test_2_extra_counts_all(self):  # 08:00-19:15 = 11.25 h -> OT 2.25
        self.assertEqual(day(11.25), (2.25, 0.0))
        self.assertEqual(day(10.25), (1.25, 0.0))   # 10:15 worked -> 1.25 (all of it)
        self.assertEqual(day(10.0), (1.0, 0.0))     # exactly the minimum counts
        self.assertEqual(day(9.99), (0.0, 0.0))

    def test_3_short_no_minimum(self):  # 08:00-16:45 = 8.75 h -> short 0.25
        self.assertEqual(day(8.75), (0.0, 0.25))
        self.assertEqual(day(9.0), (0.0, 0.0))

    def test_4_short_leave_reduces_short(self):  # 09:00-17:00 = 8 h + 60 min short leave -> short 0
        self.assertEqual(day(8.0, short_leave=1, short_leave_min=60), (0.0, 0.0))
        self.assertEqual(day(8.0, short_leave=1, short_leave_min=30), (0.0, 0.5))
        self.assertEqual(day(8.0, short_leave=0, short_leave_min=60), (0.0, 1.0))      # not ticked
        self.assertEqual(day(8.0, status="Short Leave", short_leave_min=60), (0.0, 0.0))  # status implies it
        self.assertEqual(day(8.0, short_leave=1, short_leave_min=120), (0.0, 0.0))     # floor 0

    def test_5_holiday(self):  # holiday 6 h -> OT 6; 0.75 h -> 0
        self.assertEqual(day(6, holiday_type="holiday"), (6.0, 0.0))
        self.assertEqual(day(0.75, holiday_type="holiday"), (0.0, 0.0))
        self.assertEqual(day(4, holiday_type="weekly_off"), (4.0, 0.0))
        self.assertEqual(day(5, is_holiday=True, has_shift=False), (5.0, 0.0))  # holiday: shift not needed

    def test_statuses(self):
        for status in ("Absent", "Leave", "No Pay"):
            self.assertEqual(day(11.25, status=status), (0.0, 0.0), status)
            self.assertEqual(day(6, status=status, holiday_type="holiday"), (0.0, 0.0), status)
        self.assertEqual(day(11.25, status="Present"), (2.25, 0.0))
        self.assertEqual(day(11.25, status="Short Leave"), (2.25, 0.0))

    def test_not_eligible(self):
        self.assertEqual(day(11.25, ot_eligible=0), (0.0, 0.0))
        self.assertEqual(day(8.5, ot_eligible=0), (0.0, 0.5))   # short still shown
        self.assertEqual(day(6, ot_eligible=0, holiday_type="holiday"), (0.0, 0.0))

    def test_no_shift_working_day(self):
        self.assertEqual(day(11, has_shift=False), (0.0, 0.0))

    def test_settings(self):
        self.assertEqual(day(9.5, frappe._dict(standard_day_hours=8, ot_min_daily_hours=1)), (1.5, 0.0))
        self.assertEqual(day(9.5, frappe._dict(standard_day_hours=9, ot_min_daily_hours=0)), (0.5, 0.0))
        self.assertEqual(day(9.5, frappe._dict()), (0.0, 0.0))                 # defaults 9 / 1
        self.assertEqual(day(10.25, frappe._dict()), (1.25, 0.0))
        self.assertEqual(calculate_ot_hours({"ot_eligible": 1, "worked_hours": 11.25}, SETTINGS), 2.25)


class TestMonth(UnitTestCase):
    def test_6_net(self):  # days 2 + 3: OT 2.25, short 0.25 -> net 2.0 -> 2,250.00
        rate = calculate_ot_rate("EMP-TEST", 150000)
        self.assertEqual(rate, 1125.0)
        self.assertEqual(net_ot_hours(2.25, 0.25), 2.0)
        self.assertEqual(calculate_ot_amount(net_ot_hours(2.25, 0.25), rate), 2250.0)

    def test_8_short_balance(self):  # OT 1.0, short 3.0 -> net 0, balance 2.0
        self.assertEqual((net_ot_hours(1, 3), short_balance(1, 3)), (0.0, 2.0))
        self.assertEqual(short_balance(2.25, 0.25), 0.0)

    def test_rate_rounding(self):
        self.assertEqual(calculate_ot_rate("E", 123457), 925.93)
        self.assertEqual(calculate_ot_rate("E", 0), 0.0)

    def test_amount(self):
        self.assertEqual(calculate_ot_amount(2.5, 150), 375.0)
        self.assertEqual(calculate_ot_amount(-3, 150), 0.0)


class TestNoPay(UnitTestCase):
    def test_7_placeholder_formula(self):  # (150,000 + 50,000) / 30 = 6,666.67/day; 2 days = 13,333.33
        rate = calculate_no_pay_rate({"BS": 150000, "BA": 50000, "VA": 20000})
        self.assertAlmostEqual(rate, 6666.6667, places=3)
        self.assertEqual(calculate_no_pay_amount(2, rate), 13333.33)
        self.assertEqual(calculate_no_pay_amount(0, rate), 0.0)

    def test_custom_formula(self):
        s = frappe._dict(no_pay_day_formula="BS / 26")
        self.assertEqual(calculate_no_pay_amount(1, calculate_no_pay_rate({"BS": 26000}, s)), 1000.0)
        s = frappe._dict(no_pay_day_formula="flt(base) / 30")
        self.assertEqual(calculate_no_pay_amount(3, calculate_no_pay_rate({"base": 30000}, s)), 3000.0)

    def test_missing_abbr_is_zero(self):
        self.assertEqual(calculate_no_pay_rate({"BS": 30000}), 1000.0)  # BA missing -> 0

    def test_bad_formula(self):
        with self.assertRaises(Exception):
            calculate_no_pay_rate({"BS": 1}, frappe._dict(no_pay_day_formula="BS +"))


class TestDayFigures(UnitTestCase):
    """slhrm.attendance.day_figures: shift / holiday / status wiring."""

    def fig(self, start, end, holiday_type=None, status="Present", out="19:15"):
        from slhrm.attendance import day_figures
        info = frappe._dict(start=start, end=end)
        worked = (dt(D, out) - dt(D, "08:00")).total_seconds() / 3600
        return day_figures(info, dt(D, "08:00"), dt(D, out), worked, 1, holiday_type, SETTINGS, status=status)

    def test_with_shift(self):
        f = self.fig(*DAY)
        self.assertEqual((f["no_shift"], f["calc_ot"], f["short_hours"], f["late_out_min"]), (0, 2.25, 0.0, 135))

    def test_short(self):
        f = self.fig(*DAY, out="16:45")
        self.assertEqual((f["calc_ot"], f["short_hours"], f["early_out_min"]), (0.0, 0.25, 15))

    def test_no_shift_working_day(self):
        f = self.fig(None, None)
        self.assertEqual((f["no_shift"], f["calc_ot"], f["short_hours"]), (1, 0.0, 0.0))

    def test_no_shift_not_flagged_for_absent(self):
        self.assertEqual(self.fig(None, None, status="No Pay")["no_shift"], 0)

    def test_holiday(self):
        f = self.fig(None, None, "holiday", out="14:00")
        self.assertEqual((f["no_shift"], f["calc_ot"], f["short_hours"]), (0, 6.0, 0.0))
