"""Pure-function tests for slhrm.biometric (no DB).
CI=1 bench --site <site> run-tests --app slhrm --module slhrm.tests.test_biometric --skip-before-tests"""
from datetime import datetime

from frappe.tests import UnitTestCase

from slhrm.biometric import PUNCH_TYPES, parse_device_time, punch_key, to_site_time


class TestBiometric(UnitTestCase):
    def test_punch_key_is_canonical(self):
        t = parse_device_time("2026-11-09 07:05:09")
        self.assertEqual(punch_key("ABC123", "42", t), "ABC123|42|2026-11-09 07:05:09")
        # a non-padded input still yields the canonical (zero-padded) key
        self.assertEqual(punch_key("ABC123", "42", parse_device_time("2026-11-9 7:05:09")), "ABC123|42|2026-11-09 07:05:09")

    def test_parse_rejects_other_formats(self):
        for bad in ("2026-11-09T07:05:09", "2026-11-09 07:05", "", "09/11/2026 07:05:09"):
            with self.assertRaises(ValueError):
                parse_device_time(bad)

    def test_same_timezone_is_identity(self):
        t = datetime(2026, 11, 9, 7, 5, 9)
        self.assertEqual(to_site_time(t, "Asia/Colombo", "Asia/Colombo"), t)
        self.assertEqual(to_site_time(t, "", "Asia/Colombo"), t)

    def test_timezone_conversion(self):
        # 07:05:09 UTC = 12:35:09 in Colombo (+05:30)
        self.assertEqual(to_site_time(datetime(2026, 11, 9, 7, 5, 9), "UTC", "Asia/Colombo"), datetime(2026, 11, 9, 12, 35, 9))

    def test_punch_states(self):
        self.assertEqual(PUNCH_TYPES[0], "IN")
        self.assertEqual(PUNCH_TYPES[1], "OUT")
        self.assertEqual(PUNCH_TYPES.get(99, "IN"), "IN")
