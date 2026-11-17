"""Unit tests for slhrm.biometric.connection_status (pure; mocked timestamps). v0.4.0."""
from datetime import datetime, timedelta

from frappe.tests import UnitTestCase

from slhrm.biometric import connection_status as cs, parse_quiet_windows, quiet_minutes, quiet_until

NOW = datetime(2026, 11, 12, 10, 0, 0)


def ago(minutes):
    return NOW - timedelta(minutes=minutes)


class TestConnectionStatus(UnitTestCase):
    def test_age_thresholds_after_a_good_run(self):
        self.assertEqual(cs(1, ago(0), 1, now=NOW), "Online")
        self.assertEqual(cs(1, ago(10), 1, now=NOW), "Online")       # <= 10 min
        self.assertEqual(cs(1, ago(10.5), 1, now=NOW), "Delayed")
        self.assertEqual(cs(1, ago(60), 1, now=NOW), "Delayed")      # 10–60 min
        self.assertEqual(cs(1, ago(61), 1, now=NOW), "Offline")      # > 60 min

    def test_never_synced_or_disabled(self):
        self.assertEqual(cs(1, None, 1, now=NOW), "Offline")
        self.assertEqual(cs(0, ago(1), 1, now=NOW), "Disabled")

    def test_timeout_is_delayed_until_three_failures(self):
        self.assertEqual(cs(1, ago(5), 0, "timeout", 1, now=NOW), "Delayed")
        self.assertEqual(cs(1, ago(10), 0, "timeout", 2, now=NOW), "Delayed")
        self.assertEqual(cs(1, ago(15), 0, "timeout", 3, now=NOW), "Offline")
        self.assertEqual(cs(1, ago(5), 0, "read", 1, now=NOW), "Delayed")
        self.assertEqual(cs(1, ago(70), 0, "timeout", 1, now=NOW), "Offline")  # by age

    def test_connect_or_auth_failure_is_offline(self):
        self.assertEqual(cs(1, ago(5), 0, "connect", 1, now=NOW), "Offline")
        self.assertEqual(cs(1, ago(5), 0, "auth", 1, now=NOW), "Offline")

    def test_interval_60_and_quiet_windows(self):  # v0.4.3: BRITISHPUB read hourly
        self.assertEqual(cs(1, ago(55), 1, now=NOW, interval_minutes=60), "Online")    # <= 65
        self.assertEqual(cs(1, ago(70), 1, now=NOW, interval_minutes=60), "Delayed")   # <= 120
        self.assertEqual(cs(1, ago(121), 1, now=NOW, interval_minutes=60), "Offline")
        q = parse_quiet_windows("09:00-09:30")  # NOW = 10:00; a 30 min quiet window lies inside the last 70 min
        self.assertEqual(quiet_minutes(q, ago(70), NOW), 30)
        self.assertEqual(cs(1, ago(70), 1, now=NOW, interval_minutes=60, quiet=q), "Online")  # 70 <= 65 + 30
        self.assertEqual(cs(1, ago(9), 1, now=NOW, interval_minutes=5), "Online")
        self.assertEqual(cs(1, ago(11), 1, now=NOW, interval_minutes=5), "Delayed")   # DUTCHPUB unchanged


class TestQuietWindows(UnitTestCase):
    def test_parse_and_until(self):
        self.assertEqual(parse_quiet_windows("07:30-09:00\n14:30-15:30, 21:00-22:00", as_text=True),
                         ["07:30-09:00", "14:30-15:30", "21:00-22:00"])
        q = parse_quiet_windows(["07:30-09:00", "21:00-22:00"])
        self.assertEqual(quiet_until(q, datetime(2026, 11, 17, 8, 59)), "09:00")
        self.assertIsNone(quiet_until(q, datetime(2026, 11, 17, 9, 0)))
        self.assertEqual(quiet_until(parse_quiet_windows("23:00-01:00"), datetime(2026, 11, 17, 0, 30)), "01:00")
        for bad in ("7.30-9", "07:30", "08:00-08:00"):
            with self.assertRaises(ValueError):
                parse_quiet_windows(bad)

    def test_quiet_minutes_across_midnight(self):
        q = parse_quiet_windows("23:00-01:00")
        self.assertEqual(quiet_minutes(q, datetime(2026, 11, 16, 22, 0), datetime(2026, 11, 17, 2, 0)), 120)

