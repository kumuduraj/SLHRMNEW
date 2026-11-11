"""Pure parsing tests for slhrm.salary_import (no DB records)."""
from datetime import date, datetime

from frappe.tests import UnitTestCase

from slhrm.salary_import import _amount, _date, _yes_no


class TestParsing(UnitTestCase):
    def test_amount(self):
        self.assertIsNone(_amount(None))
        self.assertIsNone(_amount(""))
        self.assertEqual(_amount(150000), 150000.0)
        self.assertEqual(_amount("150,000.50"), 150000.5)
        self.assertEqual(_amount(-5), -5.0)  # negative is reported by run(), not here
        with self.assertRaises(ValueError):
            _amount("abc")

    def test_date(self):
        self.assertEqual(_date(datetime(2026, 10, 1, 0, 0)), date(2026, 10, 1))
        self.assertEqual(_date(date(2026, 11, 1)), date(2026, 11, 1))
        self.assertEqual(_date("2026-10-01"), date(2026, 10, 1))
        self.assertIsNone(_date(""))
        with self.assertRaises(ValueError):
            _date("next month")

    def test_yes_no(self):
        self.assertEqual(_yes_no("Yes"), 1)
        self.assertEqual(_yes_no("no"), 0)
        self.assertIsNone(_yes_no(""))
        with self.assertRaises(ValueError):
            _yes_no("maybe")
