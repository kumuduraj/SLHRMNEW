"""Unit tests for slhrm.biometric.connection_status (pure; mocked timestamps). v0.4.0."""
from datetime import datetime, timedelta

from frappe.tests import UnitTestCase

from slhrm.biometric import connection_status as cs

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
