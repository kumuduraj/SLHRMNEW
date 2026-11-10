"""Pure-function tests for slhrm.biometric (no DB).
CI=1 bench --site <site> run-tests --app slhrm --module slhrm.tests.test_biometric --skip-before-tests"""
from datetime import datetime

from frappe.tests import UnitTestCase

import frappe

from slhrm.biometric import PUNCH_TYPES, as_branches, name_sanity, outcome, parse_device_time, punch_key, to_site_time


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

    def test_name_sanity(self):
        self.assertTrue(name_sanity("Vimukthi", "Vimukthi Perera Vimukthi Perera"))
        self.assertTrue(name_sanity("K. PERERA", "Kamal K Perera"))
        self.assertFalse(name_sanity("Ann", "Joanne Silva"))  # whole words only
        self.assertFalse(name_sanity("NN-575", "Nimal Silva"))
        self.assertFalse(name_sanity("", "Nimal Silva"))
        self.assertFalse(name_sanity(None, "Nimal Silva"))

    def test_outcome(self):
        c = frappe._dict
        self.assertEqual(outcome(c(result="match", sane=True)), (True, None))
        self.assertEqual(outcome(c(result="match", sane=False)), (False, "name_mismatch"))
        self.assertEqual(outcome(c(result="ambiguous", sane=False)), (False, "ambiguous"))
        self.assertEqual(outcome(c(result="conflict", sane=True)), (False, "conflict"))
        self.assertEqual(outcome(c(result="none", sane=False)), (False, None))

    def test_as_branches(self):
        self.assertEqual(as_branches("DUTCHPUB"), ("DUTCHPUB",))
        self.assertEqual(as_branches(["DUTCHPUB", "FORTFUSION", "DUTCHPUB", " ", None]), ("DUTCHPUB", "FORTFUSION"))
        self.assertEqual(as_branches(None), ())
        self.assertEqual(as_branches(""), ())
