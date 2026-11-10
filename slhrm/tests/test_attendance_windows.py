"""Pure-function tests for overnight times and one-punch-one-day windows (no DB).
CI=1 bench --site <site> run-tests --app slhrm --module slhrm.tests.test_attendance_windows --skip-before-tests"""
from datetime import datetime, timedelta

import frappe
from frappe.tests import UnitTestCase

from slhrm.attendance import clip_windows, combine, out_is_next_day, span_hours


def info(shift, start, end, before=120, after=360):
    return frappe._dict(shift=shift, start=start, end=end, window_start=start - timedelta(minutes=before),
                        window_end=end + timedelta(minutes=after))


D = datetime(2026, 11, 5)


class TestAttendanceWindows(UnitTestCase):
    def test_span_and_next_day(self):
        self.assertEqual(span_hours("2026-11-05", "22:00:00", "06:00:00", 1), 8.0)
        self.assertEqual(span_hours("2026-11-05", "08:00:00", "17:00:00", 0), 9.0)
        self.assertEqual(span_hours("2026-11-05", "22:00:00", "06:00:00", 0), 0.0)  # impossible without the box
        self.assertEqual(span_hours("2026-11-05", "08:00:00", None, 0), 0.0)
        self.assertTrue(out_is_next_day("22:00:00", "06:00:00"))
        self.assertFalse(out_is_next_day("08:00:00", "17:00:00"))
        self.assertFalse(out_is_next_day(None, "06:00:00"))
        self.assertEqual(combine("2026-11-05", "06:10:00", 1), datetime(2026, 11, 6, 6, 10))

    def test_night_then_day_split_at_midpoint(self):
        night = info("Midnight Short Shift", D + timedelta(hours=21), D + timedelta(hours=30))      # 21:00 -> 06:00 (+1)
        day1 = info("Day Shift", D + timedelta(hours=32), D + timedelta(hours=41))                  # 08:00 -> 17:00 (+1)
        clip_windows(night, None, day1)
        self.assertEqual(night.overlap, "")
        self.assertLess(night.window_end, D + timedelta(hours=31))      # 07:00 belongs to the Day Shift
        self.assertGreaterEqual(night.window_end, D + timedelta(hours=30, minutes=59))
        prev = info("Midnight Short Shift", D + timedelta(hours=21), D + timedelta(hours=30))
        clip_windows(day1, prev, None)
        self.assertEqual(day1.window_start, D + timedelta(hours=31))    # 06:00 punch -> previous night

    def test_same_shift_every_day_unchanged(self):
        today = info("Day Shift", D + timedelta(hours=8), D + timedelta(hours=17))
        ws, we = today.window_start, today.window_end
        clip_windows(today, info("Day Shift", D - timedelta(hours=16), D - timedelta(hours=7)),
                     info("Day Shift", D + timedelta(hours=32), D + timedelta(hours=41)))
        self.assertEqual((today.window_start, today.window_end, today.overlap), (ws, we, ""))

    def test_overlapping_shifts_flagged(self):
        night = info("Midnight Short Shift", D + timedelta(hours=21), D + timedelta(hours=30))      # ends 06:00 (+1)
        early = info("Night Morning Shift", D + timedelta(hours=27), D + timedelta(hours=36))       # starts 03:00 (+1)
        clip_windows(night, None, early)
        self.assertIn("Night Morning Shift", night.overlap)

    def test_no_shift_untouched(self):
        free = frappe._dict(shift="", start=None, end=None, window_start=D, window_end=D + timedelta(hours=23, minutes=59))
        clip_windows(free, None, info("Day Shift", D + timedelta(hours=32), D + timedelta(hours=41)))
        self.assertEqual((free.overlap, free.window_end), ("", D + timedelta(hours=23, minutes=59)))
