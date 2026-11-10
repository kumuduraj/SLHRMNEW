"""Pure-function tests for slhrm.statutory.calc_apit (no DB).
CI=1 bench --site <site> run-tests --app slhrm --module slhrm.tests.test_apit --skip-before-tests"""
from frappe.tests import UnitTestCase

from slhrm.statutory import calc_apit

# SLHRM Settings slabs as loaded by salary_setup (monthly, effective 2025-04-01); top band: no limit
SLABS = [(0, 150000, 0), (150000, 233334, 6), (233334, 275001, 18), (275001, 316668, 24), (316668, 358335, 30), (358335, None, 36)]


class TestAPIT(UnitTestCase):
    def test_below_relief(self):
        self.assertEqual(calc_apit(150000, SLABS)[0], 0.0)
        self.assertEqual(calc_apit(0, SLABS)[0], 0.0)
        self.assertEqual(calc_apit(-5, SLABS)[0], 0.0)

    def test_first_band(self):
        amount, bands = calc_apit(220000, SLABS)
        self.assertEqual(amount, 4200.0)                         # 6% x 70,000
        self.assertEqual([b["rate"] for b in bands], [0, 6])          # the 0% relief band is reported too

    def test_second_band(self):
        self.assertEqual(calc_apit(250000, SLABS)[0], 7999.92)   # 6% x 83,334 + 18% x 16,666
        self.assertEqual(calc_apit(240000, SLABS)[0], 6199.92)   # 6% x 83,334 + 18% x 6,666

    def test_top_band(self):
        amount, bands = calc_apit(400000, SLABS)                 # 5,000.04 + 7,500.06 + 10,000.08 + 12,500.10 + 36% x 41,665
        self.assertEqual(amount, 49999.68)
        self.assertEqual([b["rate"] for b in bands], [0, 6, 18, 24, 30, 36])

    def test_band_edges_continuous(self):
        for edge in (233334, 275001, 316668, 358335):
            self.assertAlmostEqual(calc_apit(edge + 0.01, SLABS)[0] - calc_apit(edge, SLABS)[0], 0.0, delta=0.01)
