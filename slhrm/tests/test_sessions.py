"""Unit tests for punch sessions (no shift) and missing punch — slhrm.attendance (pure, no DB). v0.4.1."""
from datetime import datetime

import frappe
from frappe.tests import UnitTestCase

from slhrm.attendance import compute_day_session, sessions_for_day, split_sessions

S = frappe._dict(standard_day_hours=9, ot_min_daily_hours=1, rest_gap_hours=6, max_session_hours=20)
NOHOL = (False, None)


def P(ts, dev="DEV1", state=None):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    return frappe._dict(doctype="Biometric Punch Log", name=f"p-{ts}", time=t, source="Biometric", device=dev, log_type="IN",
                        state=state)


def real(spec, d="2026-10"):
    """'01 00:08/1  01 14:39/0 …' (DUTCHPUB raw punches) → punches."""
    return [P(f"{d}-{x.split()[0]} {x.split()[1].split('/')[0]}:00", state=int(x.split('/')[1])) for x in spec.split("  ")]


def day(punches, d, eligible=1, holiday=NOHOL):
    return compute_day_session("E1", d, punches, eligible, holiday, S, {"DEV1": "DUTCHPUB"})


class TestSessions(UnitTestCase):
    def test_split_rules(self):
        # IN 08:00, break 12:00 / 12:30 (< 6 h), OUT 17:00, next IN after 15 h -> two sessions
        ps = [P("2026-10-02 08:00:00"), P("2026-10-02 12:00:00"), P("2026-10-02 12:30:00"), P("2026-10-02 17:00:00"),
              P("2026-10-03 08:00:00"), P("2026-10-03 17:00:00")]
        self.assertEqual([len(x) for x in split_sessions(ps, 6, 20)], [4, 2])
        # missing OUT: next IN 24 h later (> 20 h) -> the IN stays alone
        ps = [P("2026-10-01 14:39:00"), P("2026-10-02 14:49:00"), P("2026-10-03 00:25:00")]
        self.assertEqual([len(x) for x in split_sessions(ps, 6, 20)], [1, 2])
        # double tap at IN + triple tap at OUT (real DUTCHPUB pattern)
        ps = [P("2026-10-02 14:35:00"), P("2026-10-02 14:35:30"), P("2026-10-03 01:51:00"), P("2026-10-03 01:51:20"), P("2026-10-03 01:51:40")]
        self.assertEqual([len(x) for x in split_sessions(ps, 6, 20)], [5])

    def test_real_pattern_waruna(self):  # 01 14:39 IN, 02 00:00 OUT, 02 14:35 x2 IN, 03 00:27 OUT
        ps = [P("2026-10-01 14:39:00"), P("2026-10-02 00:00:14"), P("2026-10-02 14:35:00"), P("2026-10-02 14:35:40"), P("2026-10-03 00:27:00")]
        r = day(ps, "2026-10-02")
        self.assertEqual((r["in_time"], r["out_time"], r["out_next_day"], r["prev_punch"]), ("14:35:00", "00:27:00", 1, "2026-10-02 00:00:14"))

    def test_overnight_session_one_row_on_start_day(self):  # 15:00 D -> 01:00 D+1 = one row on D, 10 h, OUT +1, OT 1.0
        ps = [P("2026-10-02 15:00:00"), P("2026-10-03 01:00:00")]
        r = day(ps, "2026-10-02")
        self.assertEqual((r["in_time"], r["out_time"], r["out_next_day"], r["worked_hours"], r["calc_ot"], r["missing_punch"]),
                         ("15:00:00", "01:00:00", 1, 10.0, 1.0, 0))
        n = day(ps, "2026-10-03")  # D+1 does NOT start at 01:00
        self.assertEqual((n["in_time"], n["attendance_status"], n["punch_count"]), (None, "Absent", 0))

    def test_previous_days_out_after_midnight_is_not_todays_in(self):  # IN 15:30 D-1, OUT 00:00:14 D, then D 10:00-19:00
        ps = [P("2026-10-01 15:30:00"), P("2026-10-02 00:00:14"), P("2026-10-02 10:00:00"), P("2026-10-02 19:00:00")]
        d = day(ps, "2026-10-02")
        self.assertEqual((d["in_time"], d["out_time"], d["worked_hours"]), ("10:00:00", "19:00:00", 9.0))
        self.assertEqual(d["prev_punch"], "2026-10-02 00:00:14")
        prev = day(ps, "2026-10-01")
        self.assertEqual((prev["in_time"], prev["out_time"], prev["out_next_day"]), ("15:30:00", "00:00:14", 1))

    def test_single_punch_is_missing_punch(self):  # single IN 10:53 -> Missing punch, short 0, OT 0
        r = day([P("2026-10-02 10:53:04")], "2026-10-02")
        self.assertEqual((r["in_time"], r["out_time"], r["missing_punch"], r["short_hours"], r["calc_ot"], r["worked_hours"]),
                         ("10:53:04", None, 1, 0.0, 0.0, 0.0))
        self.assertIn("missing OUT", r["warning"])

    def test_ot_from_session(self):  # 10:07-23:06 = 12.98 h -> OT 3.98
        r = day([P("2026-10-02 10:07:19"), P("2026-10-02 23:06:05")], "2026-10-02")
        self.assertEqual((r["worked_hours"], r["calc_ot"]), (12.98, 3.98))
        self.assertEqual(day([P("2026-10-02 10:07:19"), P("2026-10-02 23:06:05")], "2026-10-02", eligible=0)["calc_ot"], 0.0)

    def test_long_session_and_second_session_warnings(self):
        ps = [P("2026-10-02 01:00:00"), P("2026-10-02 06:00:00"), P("2026-10-02 11:00:00"), P("2026-10-02 16:00:00"),
              P("2026-10-02 21:00:00"), P("2026-10-03 01:30:00")]  # 24.5 h, every gap < 6 h
        r = day(ps, "2026-10-02")
        self.assertEqual((r["long_session"], r["worked_hours"]), (1, 24.5))
        self.assertIn("Long session", r["warning"])
        # split day (device states IN/OUT/IN/OUT): 06:00-10:00, 6 h 30 rest, 16:30-22:00 -> first session used + warning
        two = day([P("2026-10-02 06:00:00", state=0), P("2026-10-02 10:00:00", state=1), P("2026-10-02 16:30:00", state=0),
                   P("2026-10-02 22:00:00", state=1)], "2026-10-02")
        self.assertEqual((two["in_time"], two["out_time"]), ("06:00:00", "10:00:00"))
        self.assertIn("Another session on this day starts 16:30", two["warning"])

    def test_context_fields(self):
        # IN 10:00, break out 12:00 / in 12:30, OUT 19:00 (6.5 h after the break-in)
        ps = [P("2026-10-01 15:30:00"), P("2026-10-02 00:00:14"), P("2026-10-02 10:00:00"), P("2026-10-02 12:00:00"),
              P("2026-10-02 12:30:00"), P("2026-10-02 19:00:00"), P("2026-10-03 08:00:00"), P("2026-10-03 17:00:00")]
        r = day(ps, "2026-10-02")
        self.assertEqual((r["prev_punch"], r["next_punch"], r["worked_hours"]), ("2026-10-02 00:00:14", "2026-10-03 08:00:00", 9.0))
        self.assertEqual(r["session_range"], "02-10-2026 10:00 → 02-10-2026 19:00")
        self.assertEqual(r["session_punches"].splitlines(), ["02-10 10:00:00  DUTCHPUB", "02-10 12:00:00  DUTCHPUB",
                                                             "02-10 12:30:00  DUTCHPUB", "02-10 19:00:00  DUTCHPUB"])
        self.assertEqual([x["used_as"] for x in r["refs"]], ["IN", "Intermediate", "Intermediate", "OUT"])

    def test_sessions_for_day(self):
        ps = [P("2026-10-01 22:00:00"), P("2026-10-02 06:00:00"), P("2026-10-02 18:00:00")]  # 22-06 is D-1's session
        self.assertEqual([[p.time.hour for p in x] for x in sessions_for_day(ps, "2026-10-02")], [[18]])

    def test_holiday_session(self):
        r = day([P("2026-10-24 08:00:00"), P("2026-10-24 14:00:00")], "2026-10-24", holiday=(True, "holiday"))
        self.assertEqual((r["calc_ot"], r["short_hours"], r["no_shift"]), (6.0, 0.0, 0))

    def test_real_dutchpub_patterns(self):  # raw DUTCHPUB punches 30-09 .. 03-10 → D = 2026-10-02
        cases = {
            "waruna": ("01 00:08/1  01 00:08/1  01 14:39/0  02 00:00/5  02 14:35/0  02 14:35/0  03 00:27/1", ("14:35:00", "00:27:00", 1)),
            "jayakody": ("01 00:07/1  01 00:08/1  01 08:04/0  01 08:04/0  01 17:24/1  02 08:48/0  02 17:24/1", ("08:48:00", "17:24:00", 0)),
            "lakpriya": ("01 00:10/1  01 10:03/0  02 00:03/1  02 10:31/0  02 17:01/1", ("10:31:00", "17:01:00", 0)),
            "maduranga": ("01 00:33/1  01 14:38/0  01 23:04/0  01 23:04/1  02 14:52/0  03 00:25/1  03 15:02/1  03 23:26/1",
                          ("14:52:00", "00:25:00", 1)),
            "amitha": ("01 00:08/1  01 00:08/1  01 14:02/0  01 23:42/5  02 14:02/0  03 01:51/5  03 01:51/5  03 01:51/5",
                       ("14:02:00", "01:51:00", 1)),
            "pramodya": ("01 13:53/0  02 00:04/1  02 00:04/1  02 12:26/0  03 00:44/1  03 00:44/1  03 14:11/0", ("12:26:00", "00:44:00", 1)),
            "manoj": ("01 12:00/0  02 12:35/0  03 09:23/1", ("12:35:00", None, 0)),
        }
        for who, (spec, want) in cases.items():
            r = day(real(spec), "2026-10-02")
            self.assertEqual((r["in_time"], r["out_time"], r["out_next_day"]), want, who)
