"""Unit tests for slhrm.overtime (pure functions, no DB records).

Run: bench --site <site> run-tests --app slhrm --module slhrm.tests.test_overtime
"""

import frappe
from frappe.tests import UnitTestCase

from slhrm.overtime import calculate_ot_amounts, calculate_ot_hours, calculate_ot_rates


def ctx(**kw):
    base = {
        "employee": "EMP-TEST",
        "date": "2026-11-02",
        "ot_eligible": 1,
        "shift": "Day",
        "shift_hours": 8,
        "in_time": "08:00:00",
        "out_time": "19:00:00",
        "worked_hours": 11,
        "is_holiday": False,
        "holiday_type": None,
    }
    base.update(kw)
    return base


SETTINGS = frappe._dict(overtime_threshold=0, default_ot_rate=150, default_double_ot_rate=300)


class TestOvertimeHours(UnitTestCase):
    def test_working_day_extra_hours_are_normal(self):
        self.assertEqual(calculate_ot_hours(ctx(), SETTINGS), {"normal": 3.0, "double": 0.0})

    def test_working_day_no_extra(self):
        self.assertEqual(calculate_ot_hours(ctx(worked_hours=7.5), SETTINGS), {"normal": 0.0, "double": 0.0})

    def test_not_eligible_is_zero(self):
        self.assertEqual(calculate_ot_hours(ctx(ot_eligible=0), SETTINGS), {"normal": 0.0, "double": 0.0})
        self.assertEqual(
            calculate_ot_hours(ctx(ot_eligible=0, is_holiday=True, holiday_type="holiday"), SETTINGS),
            {"normal": 0.0, "double": 0.0},
        )

    def test_holiday_all_hours_double(self):
        r = calculate_ot_hours(ctx(worked_hours=6, is_holiday=True, holiday_type="holiday"), SETTINGS)
        self.assertEqual(r, {"normal": 0.0, "double": 6.0})

    def test_weekly_off_counts_as_holiday(self):
        r = calculate_ot_hours(ctx(worked_hours=4, holiday_type="weekly_off"), SETTINGS)
        self.assertEqual(r, {"normal": 0.0, "double": 4.0})

    def test_threshold_from_settings(self):
        s = frappe._dict(SETTINGS, overtime_threshold=1)
        self.assertEqual(calculate_ot_hours(ctx(worked_hours=8.5), s), {"normal": 0.0, "double": 0.0})
        self.assertEqual(calculate_ot_hours(ctx(worked_hours=9), s), {"normal": 1.0, "double": 0.0})
        self.assertEqual(
            calculate_ot_hours(ctx(worked_hours=0.5, is_holiday=True), s), {"normal": 0.0, "double": 0.0}
        )

    def test_ctx_min_ot_hours_overrides_settings(self):
        s = frappe._dict(SETTINGS, overtime_threshold=5)
        self.assertEqual(calculate_ot_hours(ctx(min_ot_hours=0), s), {"normal": 3.0, "double": 0.0})

    def test_rounding_and_no_worked_hours(self):
        self.assertEqual(calculate_ot_hours(ctx(worked_hours=9.3333), SETTINGS)["normal"], 1.33)
        self.assertEqual(calculate_ot_hours(ctx(worked_hours=0), SETTINGS), {"normal": 0.0, "double": 0.0})
        self.assertEqual(calculate_ot_hours(ctx(worked_hours=-2), SETTINGS), {"normal": 0.0, "double": 0.0})

    def test_missing_settings_and_dict_settings(self):
        self.assertEqual(calculate_ot_hours(ctx()), {"normal": 3.0, "double": 0.0})
        self.assertEqual(calculate_ot_hours(ctx(), {"overtime_threshold": 4}), {"normal": 0.0, "double": 0.0})


class TestOvertimeRatesAndAmounts(UnitTestCase):
    def test_rates_from_settings(self):
        self.assertEqual(
            calculate_ot_rates("EMP-TEST", 50000, SETTINGS), {"normal_rate": 150.0, "double_rate": 300.0}
        )

    def test_rates_default_zero(self):
        self.assertEqual(calculate_ot_rates("EMP-TEST", 0, frappe._dict()), {"normal_rate": 0.0, "double_rate": 0.0})

    def test_amounts(self):
        rates = {"normal_rate": 150, "double_rate": 300}
        self.assertEqual(calculate_ot_amounts(2.5, 6, rates), {"normal": 375.0, "double": 1800.0})

    def test_amounts_round_and_clamp(self):
        rates = {"normal_rate": 123.456, "double_rate": 10}
        self.assertEqual(calculate_ot_amounts(1.333, -3, rates), {"normal": 164.57, "double": 0.0})
