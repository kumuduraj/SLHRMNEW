"""SLHRM agent tests — fake device + fake server, no pyzk / network needed.
Run: python3 -m unittest discover -s SLHRM-AGENT/tests -v"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import slhrm_agent as A  # noqa: E402

T0 = datetime(2026, 10, 1, 8, 0, 0)


def rec(uid, ts, punch=0):
    return SimpleNamespace(user_id=uid, timestamp=ts, punch=punch, status=1)


class FakeConn:
    """Records every call; anything not in ALLOWED_DEVICE_CALLS fails the test."""

    def __init__(self, records=(), serial="SER1", now=None, users=()):
        self.calls = []
        self._records = list(records)
        self.serial = serial
        self.now = now
        self._users = list(users)
        self.users = len(self._users)
        self.users_cap = 1000
        self.records = len(self._records)
        self.rec_cap = 100000
        self.fingers = 0
        self.fingers_cap = 3000

    def __getattr__(self, name):
        raise AssertionError(f"unexpected device call {name}")

    def _log(self, name):
        assert name in A.ALLOWED_DEVICE_CALLS, name
        self.calls.append(name)

    def connect(self):
        self._log("connect")
        return self

    def disconnect(self):
        self._log("disconnect")

    def get_serialnumber(self):
        self._log("get_serialnumber")
        return self.serial

    def get_firmware_version(self):
        self._log("get_firmware_version")
        return "Ver 6.60"

    def get_device_name(self):
        self._log("get_device_name")
        return "K40"

    def get_platform(self):
        self._log("get_platform")
        return "ZLM60_TFT"

    def get_mac(self):
        self._log("get_mac")
        return "00:17:61:00:00:01"

    def get_time(self):
        self._log("get_time")
        return self.now or datetime.now().replace(microsecond=0)

    def read_sizes(self):
        self._log("read_sizes")

    def get_users(self):
        self._log("get_users")
        return self._users

    def get_attendance(self):
        self._log("get_attendance")
        return self._records


class FakeServer:
    """Mimics slhrm.api.device_ingest: unique by key; user '999' unknown; user 'bad' errors."""

    def __init__(self):
        self.stored = {}
        self.calls = 0
        self.down = False
        self.crash_after_store = False
        self.payloads = []
        self.users_calls = 0
        self.start = None  # SLHRM Settings biometric_start_date ("YYYY-MM-DD 00:00:00")

    def post(self, cfg, method, payload):
        self.calls += 1
        if self.down:
            raise A.AgentError("HTTP 502 device_ingest: Bad Gateway")
        if method == "slhrm.api.device_users":
            self.users_calls += 1
            return {"users": len(payload["users"])}
        if method != "slhrm.api.device_ingest":
            return {"ok": True}
        self.payloads.append(payload)
        results = []
        for p in payload["punches"]:
            key = f"{payload['serial']}|{p['device_user_id']}|{p['timestamp']}"
            if self.start and p["timestamp"] < self.start:
                results.append({"key": key, "result": "skipped_old"})
            elif p["device_user_id"] == "bad":
                results.append({"key": key, "result": "error", "error": "boom"})
            elif key in self.stored:
                results.append({"key": key, "result": "duplicate", "name": self.stored[key]})
            else:
                self.stored[key] = f"BPL-{len(self.stored) + 1}"
                results.append({"key": key, "result": "unknown_employee" if p["device_user_id"] == "999" else "inserted",
                                "name": self.stored[key]})
        if self.crash_after_store:
            self.crash_after_store = False
            raise A.AgentError("connection reset after the server committed")
        return {"results": results, "counts": {}}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = {"server_url": "https://example.invalid", "api_key": "k", "agent_name": "test", "batch_size": 2,
                    "timeout_seconds": 10, "http_timeout_seconds": 5, "plausible_from": "2020-01-01",
                    "db_path": os.path.join(self.dir, "q.sqlite"), "lock_path": os.path.join(self.dir, "lock"),
                    "devices": [{"name": "D1", "serial": "SER1", "ip": "10.0.0.1", "port": 4370, "password": 0,
                                 "transport": "tcp", "timezone": "Asia/Colombo", "enabled": True}]}
        self.db = A.db_open(self.cfg["db_path"])

    def states(self):
        return dict(self.db.execute("SELECT state, COUNT(*) FROM punch GROUP BY state").fetchall())


class TestReadOnly(Base):
    def test_forbidden_calls_are_refused(self):
        """Every forbidden pyzk method raises on the wrapper (attribute AND _call) and never reaches the
        connection: SpyConn records any attribute access at all."""

        class SpyConn:
            def __init__(self):
                object.__setattr__(self, "touched", [])

            def __getattr__(self, name):
                self.touched.append(name)
                return lambda *a, **k: self.touched.append(f"called {name}")

        self.assertTrue(A.FORBIDDEN_DEVICE_CALLS)
        self.assertFalse(A.FORBIDDEN_DEVICE_CALLS & A.ALLOWED_DEVICE_CALLS)
        for name in sorted(A.FORBIDDEN_DEVICE_CALLS):
            with self.subTest(name=name):
                conn = SpyConn()
                dev = A.ReadOnlyDevice(conn)
                with self.assertRaises(A.AgentError):
                    getattr(dev, name)()
                with self.assertRaises(A.AgentError):
                    dev._call(name)
                with self.assertRaises(A.AgentError):
                    A.device_call(conn, name)
                self.assertEqual(conn.touched, [])

    def test_unknown_calls_refused_and_wrapper_immutable(self):
        conn = FakeConn()
        dev = A.ReadOnlyDevice(conn)
        for name in ("get_templates", "get_user_template", "read_with_buffer", "anything"):
            with self.assertRaises(A.AgentError):
                dev._call(name)
        with self.assertRaises(A.AgentError):
            dev._conn = object()
        self.assertEqual(conn.calls, [])

    def test_connect_goes_through_the_guard(self):
        conn = FakeConn()
        dev = A.connect_once("ip", 4370, 0, "tcp", 10, factory=lambda *a: conn)
        self.assertIsInstance(dev, A.ReadOnlyDevice)
        self.assertEqual(conn.calls, ["connect"])

    def test_every_pyzk_method_is_classified(self):
        """With pyzk installed (agent venv): each public ZK method is either allowed or forbidden."""
        try:
            from zk import ZK
        except ImportError:
            self.skipTest("pyzk not installed")
        public = {n for n in dir(ZK) if not n.startswith("_") and callable(getattr(ZK, n))}
        reads_not_used = {"get_compat_old_firmware", "get_extend_fmt", "get_face_fun_on", "get_face_version",
                          "get_fp_version", "get_network_params", "get_pin_width", "get_templates",
                          "get_user_extend_fmt", "get_user_template", "read_with_buffer"}
        self.assertEqual(public - A.ALLOWED_DEVICE_CALLS - A.FORBIDDEN_DEVICE_CALLS - reads_not_used, set())
        self.assertTrue(A.ALLOWED_DEVICE_CALLS <= public)

    def test_read_device_uses_only_allowed_calls(self):
        conn = FakeConn([rec("1", T0)], users=[SimpleNamespace(user_id="1", name="A", privilege=0)])
        data = A.read_device(self.cfg["devices"][0], self.cfg, factory=lambda *a: conn, with_users=True)
        self.assertEqual(len(data["records"]), 1)
        self.assertTrue(set(conn.calls) <= A.ALLOWED_DEVICE_CALLS)
        self.assertEqual(conn.calls[0], "connect")
        self.assertEqual(conn.calls[-1], "disconnect")

    def test_serial_mismatch_refuses_and_disconnects(self):
        conn = FakeConn([rec("1", T0)], serial="OTHER")
        with self.assertRaises(A.AgentError):
            A.read_device(self.cfg["devices"][0], self.cfg, factory=lambda *a: conn)
        self.assertNotIn("get_attendance", conn.calls)
        self.assertEqual(conn.calls[-1], "disconnect")


class TestConnectPlan(Base):
    def factory(self, outcomes, seen):
        def make(ip, port, password, transport, timeout):
            seen.append((password, transport))
            outcome = outcomes.pop(0)

            class Z:
                def connect(self):
                    if outcome == "ok":
                        return FakeConn()
                    raise Exception("Unauthenticated" if outcome == "auth" else "timed out")
            return Z()
        return make

    def test_password_0_then_111111(self):
        seen = []
        _dev, pw, transport, attempts = A.connect_discover("ip", 4370, factory=self.factory(["auth", "ok"], seen), tcp_ok=True)
        self.assertEqual((pw, transport), (111111, "tcp"))
        self.assertEqual(seen, [(0, "tcp"), (111111, "tcp")])

    def test_never_more_than_two_attempts(self):
        seen = []
        with self.assertRaises(A.AuthError):
            A.connect_discover("ip", 4370, factory=self.factory(["auth", "auth", "ok"], seen), tcp_ok=True)
        self.assertEqual(len(seen), 2)

    def test_tcp_network_failure_falls_back_to_udp_once(self):
        seen = []
        with self.assertRaises(A.AgentError):
            A.connect_discover("ip", 4370, factory=self.factory(["net", "net", "ok"], seen), tcp_ok=True)
        self.assertEqual(seen, [(0, "tcp"), (0, "udp")])

    def test_udp_when_tcp_port_closed(self):
        seen = []
        A.connect_discover("ip", 4370, factory=self.factory(["ok"], seen), tcp_ok=False)
        self.assertEqual(seen, [(0, "udp")])


class TestQueue(Base):
    def test_enqueue_is_idempotent(self):
        recs = [{"user_id": "1", "timestamp": T0}, {"user_id": "2", "timestamp": T0}]
        self.assertEqual(A.enqueue(self.db, "SER1", recs), 2)
        self.assertEqual(A.enqueue(self.db, "SER1", recs), 0)

    def test_clock_going_backwards_is_not_skipped(self):
        A.enqueue(self.db, "SER1", [{"user_id": "1", "timestamp": T0 + timedelta(days=300)}])  # wrong clock, ahead
        new = A.enqueue(self.db, "SER1", [{"user_id": "1", "timestamp": T0 + timedelta(days=300)},
                                          {"user_id": "1", "timestamp": T0}])  # corrected clock
        self.assertEqual(new, 1)

    def test_same_second_different_users_both_kept(self):
        self.assertEqual(A.enqueue(self.db, "SER1", [{"user_id": "1", "timestamp": T0}, {"user_id": "2", "timestamp": T0}]), 2)


class TestPush(Base):
    def fill(self, uids):
        A.enqueue(self.db, "SER1", [{"user_id": u, "timestamp": T0 + timedelta(minutes=i)} for i, u in enumerate(uids)])

    def test_confirms_per_record_and_keeps_errors(self):
        self.fill(["1", "2", "999", "bad", "3"])
        srv = FakeServer()
        res = A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(res["confirmed"], 4)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(self.states(), {"confirmed": 4, "failed": 1})
        # next run: only the failed one is resent, still kept
        res = A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(res["sent"], 1)
        self.assertEqual(self.states(), {"confirmed": 4, "failed": 1})

    def test_server_down_confirms_nothing_and_stops(self):
        self.fill(["1", "2", "3"])
        srv = FakeServer()
        srv.down = True
        res = A.push(self.db, self.cfg, post=srv.post)
        self.assertIn("stopped", res)
        self.assertEqual(srv.calls, 1)  # no retry loop
        self.assertEqual(self.states(), {"failed": 2, "queued": 1})
        srv.down = False
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(self.states(), {"confirmed": 3})
        self.assertEqual(len(srv.stored), 3)

    def test_crash_after_server_commit_resends_as_duplicate(self):
        self.fill(["1", "2"])
        srv = FakeServer()
        srv.crash_after_store = True
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(self.states(), {"failed": 2})
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(self.states(), {"confirmed": 2})
        self.assertEqual(len(srv.stored), 2)  # no duplicates on the server
        results = {r[0] for r in self.db.execute("SELECT server_result FROM punch")}
        self.assertEqual(results, {"duplicate"})

    def test_no_api_key_sends_nothing(self):
        self.fill(["1"])
        self.cfg["api_key"] = ""
        srv = FakeServer()
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(srv.calls, 0)
        self.assertEqual(self.states(), {"queued": 1})

    def test_held_after_max_attempts(self):
        self.fill(["bad"])
        srv = FakeServer()
        for _ in range(A.MAX_ATTEMPTS):
            A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(self.states(), {"held": 1})
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(self.states(), {"held": 1})  # held rows are not resent automatically
        A.push(self.db, self.cfg, retry_held=True, post=srv.post)
        self.assertEqual(self.states(), {"failed": 1})


class TestRunAndStats(Base):
    def test_run_pull_push_and_lock(self):
        conn = FakeConn([rec("1", T0), rec("1", T0), rec("2", T0 + timedelta(hours=9))])
        srv = FakeServer()
        rc = A.cmd_run(self.cfg, factory=lambda *a: conn, post=srv.post)
        self.assertEqual(rc, 0)
        self.assertEqual(self.states(), {"confirmed": 2})  # the device's exact duplicate collapses to one key
        # second run: nothing new, nothing sent
        calls = srv.calls
        A.cmd_run(self.cfg, factory=lambda *a: FakeConn(conn._records), post=srv.post)
        self.assertEqual(srv.calls, calls + 1)  # heartbeat only

    def test_run_skips_device_whose_lock_is_held(self):
        import fcntl
        with open(A.device_lock_path(self.cfg, self.cfg["devices"][0]), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            srv = FakeServer()
            self.assertEqual(A.cmd_run(self.cfg, factory=lambda *a: FakeConn(), post=srv.post), 0)
            self.assertEqual(srv.calls, 0)

    def test_stats(self):
        now = datetime.now().replace(microsecond=0)
        recs = [{"user_id": "1", "timestamp": T0, "punch_state": 0}, {"user_id": "1", "timestamp": T0, "punch_state": 0},
                {"user_id": "2", "timestamp": now + timedelta(days=30), "punch_state": 1},
                {"user_id": "3", "timestamp": datetime(2000, 1, 1), "punch_state": 0}]
        s = A.attendance_stats(recs, "UTC", since="2026-09-01", device_users=[{"user_id": "1"}])
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["same_second_extra_records"], 1)
        self.assertEqual(s["future_dated"], 1)
        self.assertEqual(s["past_dated"], 1)
        self.assertEqual(s["records_since"], 3)
        self.assertEqual(s["records_of_user_ids_not_on_device"], 2)


class TestPerUser(Base):
    def test_per_user_activity(self):
        recs = [{"user_id": "1", "timestamp": T0}, {"user_id": "1", "timestamp": T0 + timedelta(days=40)},
                {"user_id": "2", "timestamp": T0 - timedelta(days=400)}]
        a = A.per_user_activity(recs, since="2026-10-15")
        self.assertEqual(a["1"]["records"], 2)
        self.assertEqual(a["1"]["since"], 1)
        self.assertEqual(a["1"]["last"], T0 + timedelta(days=40))
        self.assertEqual(a["2"]["since"], 0)


class TestPhase21(Base):
    def test_drift_stored_on_new_rows_and_sent(self):
        A.enqueue(self.db, "SER1", [{"user_id": "1", "timestamp": T0}], drift=-670.2)
        A.enqueue(self.db, "SER1", [{"user_id": "1", "timestamp": T0}], drift=5.0)  # existing row keeps its first drift
        self.assertEqual(self.db.execute("SELECT drift_seconds FROM punch").fetchone()[0], -670.2)
        srv = FakeServer()
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(srv.payloads[0]["punches"][0]["clock_drift_seconds"], -670.2)

    def test_backfill_then_resend_is_all_duplicate(self):
        conn = FakeConn([rec("1", T0), rec("2", T0), rec("3", T0 + timedelta(days=1))],
                        users=[SimpleNamespace(user_id="1", name="A", privilege=0)])
        srv = FakeServer()
        r1 = A.cmd_backfill(self.cfg, "D1", factory=lambda *a: conn, post=srv.post)
        self.assertEqual(r1["push"]["inserted"], 3)
        r2 = A.cmd_backfill(self.cfg, "D1", factory=lambda *a: conn, post=srv.post)
        self.assertEqual((r2["new_in_queue"], r2["push"].get("sent", 0)), (0, 0))
        r3 = A.cmd_backfill(self.cfg, "D1", resend=True, factory=lambda *a: conn, post=srv.post)
        self.assertEqual(r3["push"].get("inserted", 0), 0)
        self.assertEqual(r3["push"]["duplicate"], 3)
        self.assertEqual(srv.users_calls, 1)  # user list unchanged after the first sync

    def test_device_key_preferred_and_api_key_fallback(self):
        self.assertEqual(A.device_key({"device_key": "a", "api_key": "b"}), "a")
        self.assertEqual(A.device_key({"api_key": "b"}), "b")
        self.assertEqual(A.device_key({}), "")

    def test_old_queue_schema_is_migrated(self):
        import sqlite3
        p = os.path.join(self.dir, "old.sqlite")
        old = sqlite3.connect(p)
        old.executescript(A.SCHEMA.replace("    drift_seconds REAL,                         -- device clock drift measured at the pull that first read it\n", ""))
        old.close()
        db = A.db_open(p)
        self.assertIn("drift_seconds", {r[1] for r in db.execute("PRAGMA table_info(punch)")})


class TestMinPunchDate(Base):
    CUT = "2026-10-02"

    def conn(self):
        return FakeConn([rec("1", T0), rec("2", T0 + timedelta(hours=10)), rec("1", T0 + timedelta(days=1)),
                         rec("2", T0 + timedelta(days=1, hours=9))])

    def test_split_old(self):
        recs = [{"user_id": "1", "timestamp": T0}, {"user_id": "1", "timestamp": T0 + timedelta(days=1)}]
        self.assertEqual(A.split_old(recs, None), (recs, 0))
        keep, skipped = A.split_old(recs, self.CUT)
        self.assertEqual((len(keep), skipped), (1, 1))
        self.assertEqual(A.split_old(recs, "2026-10-01")[1], 0)  # 00:00 boundary is inclusive

    def test_old_records_never_queued_or_sent_and_counted(self):
        self.cfg["devices"][0]["min_punch_date"] = self.CUT
        srv = FakeServer()
        self.assertEqual(A.cmd_run(self.cfg, factory=lambda *a: self.conn(), post=srv.post), 0)
        self.assertEqual(self.states(), {"confirmed": 2})
        sent = [p["timestamp"] for pl in srv.payloads for p in pl["punches"]]
        self.assertTrue(all(t >= self.CUT for t in sent), sent)
        row = self.db.execute("SELECT record_count, new_records, skipped_old FROM device_pull ORDER BY rowid DESC").fetchone()
        self.assertEqual(tuple(row), (4, 2, 2))

    def test_existing_confirmed_kept_unconfirmed_old_not_sent(self):
        A.enqueue(self.db, "SER1", [{"user_id": "1", "timestamp": T0}, {"user_id": "2", "timestamp": T0}])
        with self.db:
            self.db.execute("UPDATE punch SET state = 'confirmed' WHERE device_user_id = '1'")
        self.cfg["devices"][0]["min_punch_date"] = self.CUT
        srv = FakeServer()
        A.push(self.db, self.cfg, post=srv.post)
        self.assertEqual(srv.calls, 0)
        self.assertEqual(self.states(), {"confirmed": 1, "skipped_old": 1})

    def test_server_skipped_old_is_confirmed(self):
        srv = FakeServer()
        srv.start = self.CUT + " 00:00:00"
        A.cmd_run(self.cfg, factory=lambda *a: self.conn(), post=srv.post)  # agent without min date
        self.assertEqual(self.states(), {"confirmed": 4})
        res = dict(self.db.execute("SELECT server_result, COUNT(*) FROM punch GROUP BY server_result").fetchall())
        self.assertEqual(res, {"skipped_old": 2, "inserted": 2})

    def test_resend_only_from_min_date(self):
        srv = FakeServer()
        A.cmd_backfill(self.cfg, "D1", factory=lambda *a: self.conn(), post=srv.post)
        self.cfg["devices"][0]["min_punch_date"] = self.CUT
        r = A.cmd_backfill(self.cfg, "D1", resend=True, factory=lambda *a: self.conn(), post=srv.post)
        self.assertEqual((r["skipped_old"], r["push"]["duplicate"]), (2, 2))
        self.assertEqual(self.states(), {"confirmed": 4})  # old confirmed keys stay

    def test_device_pull_schema_is_migrated(self):
        import sqlite3
        p = os.path.join(self.dir, "old2.sqlite")
        old = sqlite3.connect(p)
        old.executescript(A.SCHEMA.replace(",\n    skipped_old INTEGER", ""))
        old.close()
        self.assertIn("skipped_old", {r[1] for r in A.db_open(p).execute("PRAGMA table_info(device_pull)")})

    def test_config_default_applies_to_devices(self):
        p = os.path.join(self.dir, "c2.json")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"server_url": "x", "min_punch_date": "2026-11-01",
                       "devices": [{"name": "A"}, {"name": "B", "min_punch_date": "2026-12-01"}]}, f)
        cfg = A.load_config(p)
        self.assertEqual([d["min_punch_date"] for d in cfg["devices"]], ["2026-11-01", "2026-12-01"])


class TestConfig(Base):
    def test_world_readable_config_is_refused(self):
        p = os.path.join(self.dir, "c.json")
        with open(p, "w") as f:
            json.dump({"server_url": "x"}, f)
        os.chmod(p, 0o644)
        with self.assertRaises(A.AgentError):
            A.load_config(p)
        os.chmod(p, 0o600)
        self.assertEqual(A.load_config(p)["batch_size"], 200)


if __name__ == "__main__":
    unittest.main()



class TestIndependentDevices(Base):
    """v0.4.0: per-device timeout, per-device lock, devices in parallel, Sync Now (run --once)."""

    def setUp(self):
        super().setUp()
        self.cfg["devices"].append({"name": "D2", "serial": "SER2", "ip": "10.0.0.2", "port": 4370, "password": 0,
                                    "transport": "tcp", "timezone": "Asia/Colombo", "enabled": True, "timeout_seconds": 240})
        self.cfg["devices"][0]["timeout_seconds"] = 180

    def test_per_device_timeout_passed_to_the_connection(self):
        seen = {}

        def factory(ip, port, password, transport, timeout):
            seen[ip] = timeout
            return FakeConn(serial="SER1" if ip == "10.0.0.1" else "SER2")
        A.cmd_run(self.cfg, factory=factory, post=FakeServer().post)
        self.assertEqual(seen, {"10.0.0.1": 180, "10.0.0.2": 240})

    def test_default_device_timeout_is_60(self):
        path = os.path.join(self.dir, "c.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"devices": [{"name": "X", "ip": "1.2.3.4"}]}, f)
        self.assertEqual(A.load_config(path)["devices"][0]["timeout_seconds"], 60)

    def test_timeout_on_one_device_does_not_fail_the_other(self):
        srv = FakeServer()

        def factory(ip, *a):
            if ip == "10.0.0.1":
                raise TimeoutError("timed out")
            return FakeConn([rec("7", T0)], serial="SER2")
        rc = A.cmd_run(self.cfg, factory=factory, post=srv.post)
        self.assertEqual(rc, 1)
        self.assertEqual(len(srv.stored), 1)  # D2 delivered its record
        rows = self.db.execute("SELECT serial, ok, error FROM device_pull ORDER BY rowid").fetchall()
        self.assertEqual({(r["serial"], r["ok"]) for r in rows}, {("SER1", 0), ("SER2", 1)})

    def test_slow_device_does_not_delay_the_other(self):
        import threading
        d2_done = threading.Event()

        class SlowConn(FakeConn):
            def get_attendance(self):
                self._log("get_attendance")
                self.waited = d2_done.wait(5)  # only returns early if D2 finished meanwhile (parallel)
                return self._records

        class FastConn(FakeConn):
            def get_attendance(self):
                self._log("get_attendance")
                d2_done.set()
                return self._records
        slow = SlowConn(serial="SER1")
        A.cmd_run(self.cfg, factory=lambda ip, *a: slow if ip == "10.0.0.1" else FastConn(serial="SER2"), post=FakeServer().post)
        self.assertTrue(slow.waited)

    def test_once_reports_counts_and_works_for_a_disabled_device(self):
        self.cfg["devices"][1]["enabled"] = False
        srv = FakeServer()
        r = A.cmd_once(self.cfg, "D2", factory=lambda *a: FakeConn([rec("1", T0), rec("999", T0)], serial="SER2"), post=srv.post)
        self.assertEqual((r["connected"], r["new_in_queue"], r["inserted"], r["unmatched"], r["duplicate"]), (True, 2, 1, 1, 0))
        self.assertIsNotNone(r["read_seconds"])
        r = A.cmd_once(self.cfg, "D2", factory=lambda *a: FakeConn([rec("1", T0), rec("999", T0)], serial="SER2"), post=srv.post)
        self.assertEqual((r["new_in_queue"], r["inserted"]), (0, 0))

    def test_once_busy_when_the_device_lock_is_held(self):
        import fcntl
        with open(A.device_lock_path(self.cfg, self.cfg["devices"][0]), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = A.cmd_once(self.cfg, "D1", factory=lambda *a: self.fail("must not connect"), post=FakeServer().post, wait=1)
        self.assertTrue(r["busy"])

    def test_error_kinds_and_heartbeat_payload(self):
        beats = []

        class Srv(FakeServer):
            def post(self, cfg, method, payload):
                if method == "slhrm.api.device_heartbeat":
                    beats.append(payload["info"])
                return super().post(cfg, method, payload)

        class Refused(FakeConn):
            def connect(self):
                raise ConnectionRefusedError("[Errno 111] Connection refused")

        class Unauth(FakeConn):
            def connect(self):
                raise Exception("Unauthenticated")
        r = A.cmd_once(self.cfg, "D1", factory=lambda *a: Refused(), post=Srv().post)
        self.assertEqual((r["connected"], r["error_kind"]), (False, "connect"))
        r = A.cmd_once(self.cfg, "D1", factory=lambda *a: Unauth(), post=Srv().post)
        self.assertEqual(r["error_kind"], "auth")

        class SlowRead(FakeConn):
            def get_attendance(self):
                raise TimeoutError("timed out")
        r = A.cmd_once(self.cfg, "D1", factory=lambda *a: SlowRead(serial="SER1"), post=Srv().post)
        self.assertEqual((r["connected"], r["error_kind"]), (True, "timeout"))
        self.assertEqual([b["error_kind"] for b in beats], ["connect", "auth", "timeout"])
        self.assertTrue(all("read_seconds" in b and b["last_pull_ok"] == 0 for b in beats))
