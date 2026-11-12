#!/usr/bin/env python3
"""SLHRM biometric agent — reads ZKTeco devices READ-ONLY and delivers every raw attendance record to
SLHRM exactly once (slhrm.api.device_ingest). See README.md.

Device rules (HARD, permanent): devices are READ-ONLY. Only the pyzk calls in ALLOWED_DEVICE_CALLS are ever
made — every device call goes through device_call(), which raises AgentError for anything else BEFORE the
connection is touched (FORBIDDEN_DEVICE_CALLS lists pyzk's write/control methods explicitly; ReadOnlyDevice
exposes no attribute of the connection). Never clear, set the time, change users/fingerprints, enable/disable,
restart/poweroff or change config — on any device, in any command or test. One connection per device at a time (a lock
file PER DEVICE: <lock_path>.<device name>), ommit_ping. Socket timeout per device (config timeout_seconds on the device,
default 60 s; probe / discovery uses the global 10 s). At most 2 connect attempts per device per command; never retried
in a loop. Devices are independent (v0.4.0): `run` reads every enabled device in its own thread with its own lock, queue
connection and timeout, so a slow read or timeout on one device never delays or fails another.

Zero loss / zero duplicates:
- every device record → local SQLite queue by punch_key "<serial>|<device user id>|<YYYY-MM-DD HH:MM:SS>"
  (INSERT OR IGNORE of the WHOLE device log on every pull: the overlap window is the full log, so clock
  corrections, same-second punches and late records can never be skipped);
- a record is "confirmed" only by the server's per-record result (inserted / duplicate /
  unknown_employee / skipped_old); errors stay queued and are retried on the next run; nothing is ever dropped.
- min_punch_date (config, default for all devices; a device may override it): records dated before it
  are never queued or sent — counted as skipped_old per pull (log, device_pull, status). Rows already
  in the queue are kept; unconfirmed old ones are set to state skipped_old instead of being sent.

Commands (all need --config, a chmod-600 JSON file):
  tcpcheck                         TCP connect test to every configured device (no device protocol)
  probe --ip IP [--port P]         find the comm password (0, then 111111; max 2 attempts) + read info
  info  --device NAME              device info, sizes and clock drift (configured password)
  users --device NAME [--csv F]    device users: user_id, name, privilege (no PINs/cards/templates)
  pull  --device NAME --dry-run    attendance statistics only; nothing stored or sent
  pull  [--device NAME]            read device(s) into the local queue
  push  [--retry-held]             send queued records to SLHRM
  backfill --device NAME [--resend] lock; read the whole device log, push it, report server results
                                   (--resend: send already-confirmed records again → all duplicate)
  run                              every enabled device in parallel (own lock each): pull + users + heartbeat + push
  run --once --device NAME         that device only (also when disabled in the config); waits up to 60 s for its lock,
                                   else {"busy": true}; prints a JSON result (Sync Now)
  status                           queue counts per device and state
"""
import argparse
import csv
import fcntl
import hashlib
import json
import logging
import logging.handlers
import os
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

AGENT_VERSION = "0.4.0"
DEFAULT_DEVICE_TIMEOUT = 60  # seconds, per device (config devices[].timeout_seconds)
ONCE_LOCK_WAIT = 60  # run --once: wait this long for the device lock (scheduled run in progress)
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ALLOWED_DEVICE_CALLS = frozenset({
    "connect", "get_serialnumber", "get_firmware_version", "get_device_name", "get_platform", "get_mac",
    "get_time", "read_sizes", "get_users", "get_attendance", "disconnect",
})
# pyzk methods that change or control a device — never callable (explicit, on top of the allowlist).
FORBIDDEN_DEVICE_CALLS = frozenset({
    "cancel_capture", "clear_attendance", "clear_data", "clear_lcd", "delete_user", "delete_user_template",
    "disable_device", "enable_device", "enroll_user", "free_data", "live_capture", "poweroff", "refresh_data",
    "reg_event", "restart", "save_user_template", "set_sdk_build_1", "set_time", "set_user", "test_voice",
    "unlock", "verify_user", "write_lcd",
})
DEFAULT_PASSWORDS = (0, 111111)
MAX_CONNECT_ATTEMPTS = 2
CONFIRMED_RESULTS = frozenset({"inserted", "duplicate", "unknown_employee", "skipped_old"})
MAX_ATTEMPTS = 20  # per record; then "held" (kept, reported; push --retry-held)
FUTURE_TOLERANCE = timedelta(minutes=10)

log = logging.getLogger("slhrm_agent")


class AgentError(Exception):
    pass


class AuthError(AgentError):
    pass


class ConnectError(AgentError):
    """The connect step failed (network / auth) — nothing was read."""

    def __init__(self, message, kind="connect"):
        super().__init__(message)
        self.kind = kind


def error_kind(e):
    """timeout | auth | connect | read — sent in the heartbeat; the server maps it to Delayed / Offline
    (a timeout counts as Delayed until 3 consecutive failures; connect / auth failures are Offline)."""
    text = str(e).lower()
    if isinstance(e, ConnectError) and e.kind == "auth":
        return "auth"
    if "timed out" in text or "timeout" in text or isinstance(e, TimeoutError):
        return "timeout"
    return "connect" if isinstance(e, ConnectError) else "read"


# ── config ──────────────────────────────────────────────────────


def load_config(path):
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise AgentError(f"{path} must not be readable by group/others (chmod 600)")
    with open(path) as f:
        cfg = json.load(f)
    cfg.setdefault("agent_name", socket.gethostname())
    cfg.setdefault("batch_size", 200)
    cfg.setdefault("timeout_seconds", 10)
    cfg.setdefault("http_timeout_seconds", 60)
    cfg.setdefault("plausible_from", "2020-01-01")
    cfg.setdefault("min_punch_date", None)
    if cfg["min_punch_date"]:
        datetime.strptime(cfg["min_punch_date"], "%Y-%m-%d")  # fail early on a bad date
    base = os.path.dirname(os.path.abspath(path))
    cfg.setdefault("db_path", os.path.join(base, "queue.sqlite"))
    cfg.setdefault("lock_path", os.path.join(base, "agent.lock"))
    cfg.setdefault("devices", [])
    for d in cfg["devices"]:
        d.setdefault("port", 4370)
        d.setdefault("timezone", "Asia/Colombo")
        d.setdefault("transport", "tcp")
        d.setdefault("enabled", True)
        d.setdefault("min_punch_date", cfg["min_punch_date"])
        d.setdefault("timeout_seconds", DEFAULT_DEVICE_TIMEOUT)
    return cfg


def device_timeout(dev, cfg=None):
    return int(dev.get("timeout_seconds") or DEFAULT_DEVICE_TIMEOUT)


def device_lock_path(cfg, dev):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (dev.get("name") or dev.get("serial") or "device"))
    return f"{cfg['lock_path']}.{safe}"


class DeviceLock:
    """Exclusive lock for ONE device (no two reads of the same device at once). wait=0: try once."""

    def __init__(self, cfg, dev, wait=0):
        self.path, self.wait, self.f, self.acquired = device_lock_path(cfg, dev), wait, None, False

    def __enter__(self):
        self.f = open(self.path, "w")
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return self
                time.sleep(1)

    def __exit__(self, *exc):
        if self.acquired:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def min_ts(min_punch_date):
    """'YYYY-MM-DD' → the first allowed record timestamp ('YYYY-MM-DD 00:00:00'), or None."""
    return f"{min_punch_date} 00:00:00" if min_punch_date else None


def split_old(records, min_punch_date):
    """(records to keep, number skipped as older than min_punch_date). Device time is compared."""
    if not min_punch_date:
        return list(records), 0
    start = datetime.strptime(min_punch_date, "%Y-%m-%d")
    keep = [r for r in records if r["timestamp"] >= start]
    return keep, len(records) - len(keep)


def device_key(cfg):
    """SLHRM Settings device_api_key, copied into the config as device_key (never logged)."""
    return cfg.get("device_key") or cfg.get("api_key") or ""


def get_device_cfg(cfg, name):
    for d in cfg["devices"]:
        if d["name"] == name:
            return d
    raise AgentError(f"device {name!r} is not in the config")


def setup_logging(cfg=None, verbose=False):
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(fmt)
        log.addHandler(h)
    if cfg and cfg.get("log_file") and not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
        fh = logging.handlers.RotatingFileHandler(cfg["log_file"], maxBytes=5_000_000, backupCount=5)
        fh.setFormatter(fmt)
        log.addHandler(fh)


# ── device (read-only) ──────────────────────────────────────────


def device_call(obj, name, *args):
    """The ONLY place a pyzk method is invoked. Refuses (AgentError) before touching obj."""
    if name in FORBIDDEN_DEVICE_CALLS or name not in ALLOWED_DEVICE_CALLS:
        raise AgentError(f"forbidden device call: {name} (devices are read-only)")
    return getattr(obj, name)(*args)


class ReadOnlyDevice:
    """The only way the agent talks to a connected device: allowed pyzk calls only. Any other attribute
    (e.g. device.clear_attendance) raises AgentError immediately, without touching the connection."""

    __slots__ = ("_conn",)

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)

    def __getattr__(self, name):
        raise AgentError(f"forbidden device call: {name} (devices are read-only)")

    def __setattr__(self, name, value):
        raise AgentError(f"read-only device wrapper: cannot set {name}")

    def _call(self, name, *args):
        return device_call(self._conn, name, *args)

    def info(self):
        return {
            "serial": str(self._call("get_serialnumber") or "").strip(),
            "firmware": str(self._call("get_firmware_version") or "").strip(),
            "device_reported_name": str(self._call("get_device_name") or "").strip(),
            "platform": str(self._call("get_platform") or "").strip(),
            "mac": str(self._call("get_mac") or "").strip(),
        }

    def time(self):
        return self._call("get_time")

    def sizes(self):
        self._call("read_sizes")
        c = self._conn
        return {
            "user_count": int(getattr(c, "users", 0) or 0), "user_capacity": int(getattr(c, "users_cap", 0) or 0),
            "record_count": int(getattr(c, "records", 0) or 0), "record_capacity": int(getattr(c, "rec_cap", 0) or 0),
            "finger_count": int(getattr(c, "fingers", 0) or 0), "finger_capacity": int(getattr(c, "fingers_cap", 0) or 0),
        }

    def users(self):
        return [
            {"user_id": str(u.user_id).strip(), "name": str(u.name or "").strip(), "privilege": int(u.privilege or 0)}
            for u in self._call("get_users")
        ]

    def attendance(self):
        return [
            {"user_id": str(a.user_id).strip(), "timestamp": a.timestamp,
             "punch_state": getattr(a, "punch", None), "verify_mode": getattr(a, "status", None)}
            for a in self._call("get_attendance")
        ]

    def disconnect(self):
        try:
            self._call("disconnect")
        except Exception as e:  # the session ends anyway when the socket closes
            log.debug("disconnect: %s", e)


def _zk(ip, port, password, transport, timeout):
    from zk import ZK  # pyzk, imported lazily (tests run without it)

    return ZK(ip, port=int(port), timeout=int(timeout), password=int(password),
              force_udp=(transport == "udp"), ommit_ping=True)


def _is_auth_error(e):
    return "unauth" in str(e).lower()


def tcp_check(ip, port, timeout=10):
    """Plain TCP connect (no device protocol). Returns (ok, latency_ms, error)."""
    t0 = time.monotonic()
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True, round((time.monotonic() - t0) * 1000, 1), None
    except OSError as e:
        return False, None, f"{type(e).__name__}: {e}"


def connect_once(ip, port, password, transport, timeout, factory=_zk):
    """ONE connect attempt. Raises AuthError (wrong comm password) or AgentError (network/other)."""
    zk = factory(ip, port, password, transport, timeout)
    try:
        conn = device_call(zk, "connect")
    except Exception as e:
        if _is_auth_error(e):
            raise AuthError(str(e)) from e
        raise AgentError(f"{type(e).__name__}: {e}") from e
    return ReadOnlyDevice(conn)


def connect_configured(dev, cfg, factory=_zk):
    """Configured device: exactly one attempt with its known password and transport, the DEVICE's timeout.
    Failures are raised as ConnectError (kind auth / connect)."""
    try:
        return connect_once(dev["ip"], dev["port"], dev["password"], dev["transport"], device_timeout(dev, cfg), factory)
    except AuthError as e:
        raise ConnectError(str(e), kind="auth") from e
    except AgentError as e:
        raise ConnectError(str(e), kind="timeout" if "timed out" in str(e).lower() else "connect") from e


def connect_discover(ip, port, timeout=10, factory=_zk, tcp_ok=None):
    """Unknown comm password: at most MAX_CONNECT_ATTEMPTS connect attempts in total.
    Order: password 0 then 111111; transport TCP when the TCP port answers, else UDP. A network failure on
    TCP switches to UDP for the remaining attempt. Returns (device, password, transport, attempts)."""
    if tcp_ok is None:
        tcp_ok = tcp_check(ip, port, timeout)[0]
    transport = "tcp" if tcp_ok else "udp"
    passwords = list(DEFAULT_PASSWORDS)
    attempts = []
    while passwords and len(attempts) < MAX_CONNECT_ATTEMPTS:
        pw = passwords[0]
        try:
            device = connect_once(ip, port, pw, transport, timeout, factory)
            attempts.append({"password": pw, "transport": transport, "result": "ok"})
            return device, pw, transport, attempts
        except AuthError as e:
            attempts.append({"password": pw, "transport": transport, "result": f"auth: {e}"})
            passwords.pop(0)
        except AgentError as e:
            attempts.append({"password": pw, "transport": transport, "result": f"network: {e}"})
            if transport == "tcp":
                transport = "udp"  # same password over UDP (counts as the second attempt)
            else:
                break
    message = f"no connection after {len(attempts)} attempt(s): {attempts}"
    if attempts and all(a["result"].startswith("auth") for a in attempts):
        raise AuthError(message)
    raise AgentError(message)


def clock_drift(device_time, tz):
    host_now = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    return round((device_time - host_now).total_seconds(), 1), host_now


# ── statistics (dry run) ────────────────────────────────────────


def per_user_activity(records, since=None):
    """{user_id: {records, first, last, since}} — for mapping review (dry run only)."""
    s = datetime.strptime(since, "%Y-%m-%d") if since else None
    out = {}
    for r in records:
        a = out.setdefault(r["user_id"], {"records": 0, "first": r["timestamp"], "last": r["timestamp"], "since": 0})
        a["records"] += 1
        a["first"] = min(a["first"], r["timestamp"])
        a["last"] = max(a["last"], r["timestamp"])
        if s and r["timestamp"] >= s:
            a["since"] += 1
    return out


def attendance_stats(records, tz, since=None, plausible_from="2020-01-01", device_users=None):
    now = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    plausible = datetime.strptime(plausible_from, "%Y-%m-%d")
    ts = [r["timestamp"] for r in records]
    keys = Counter((r["user_id"], r["timestamp"]) for r in records)
    dup_groups = {k: n for k, n in keys.items() if n > 1}
    future = sorted(r["timestamp"] for r in records if r["timestamp"] > now + FUTURE_TOLERANCE)
    past = sorted(r["timestamp"] for r in records if r["timestamp"] < plausible)
    out = {
        "total": len(records),
        "earliest": min(ts).strftime(TIME_FORMAT) if ts else None,
        "latest": max(ts).strftime(TIME_FORMAT) if ts else None,
        "distinct_user_ids": len({r["user_id"] for r in records}),
        "same_second_duplicate_groups": len(dup_groups),
        "same_second_extra_records": sum(n - 1 for n in dup_groups.values()),
        "same_second_examples": [f"{u} @ {t.strftime(TIME_FORMAT)} x{n}" for (u, t), n in list(dup_groups.items())[:5]],
        "future_dated": len(future),
        "future_examples": [t.strftime(TIME_FORMAT) for t in future[:5]],
        "past_dated_before": plausible_from,
        "past_dated": len(past),
        "past_examples": [t.strftime(TIME_FORMAT) for t in past[:5]],
        "punch_states": dict(Counter(str(r["punch_state"]) for r in records)),
    }
    if since:
        s = datetime.strptime(since, "%Y-%m-%d")
        out["since"] = since
        out["records_since"] = sum(1 for t in ts if t >= s)
    if device_users is not None:
        known = {u["user_id"] for u in device_users}
        out["records_of_user_ids_not_on_device"] = sum(1 for r in records if r["user_id"] not in known)
    return out


# ── local queue (SQLite) ────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS punch (
    punch_key TEXT PRIMARY KEY,
    serial TEXT NOT NULL,
    device_user_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    punch_state INTEGER,
    verify_mode INTEGER,
    drift_seconds REAL,                         -- device clock drift measured at the pull that first read it
    fetched_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',      -- queued | failed | held | confirmed
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    server_result TEXT,
    server_name TEXT,
    last_sent_at TEXT,
    confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS punch_state ON punch(state, serial, ts);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS device_pull (
    serial TEXT NOT NULL,
    pulled_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    record_count INTEGER,
    new_records INTEGER,
    drift_seconds REAL,
    error TEXT,
    skipped_old INTEGER
);
"""


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime(TIME_FORMAT)


def db_open(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("PRAGMA table_info(punch)")}
    if "drift_seconds" not in cols:  # queue created by agent 0.1.0
        with db:
            db.execute("ALTER TABLE punch ADD COLUMN drift_seconds REAL")
    if "skipped_old" not in {r[1] for r in db.execute("PRAGMA table_info(device_pull)")}:  # agent <= 0.2.0
        with db:
            db.execute("ALTER TABLE device_pull ADD COLUMN skipped_old INTEGER")
    return db


def make_key(serial, user_id, ts):
    return f"{serial}|{user_id}|{ts.strftime(TIME_FORMAT)}"


def enqueue(db, serial, records, drift=None):
    """INSERT OR IGNORE every record. Returns the number of NEW records. drift is stored on new rows only."""
    now = utcnow()
    rows = [(make_key(serial, r["user_id"], r["timestamp"]), serial, r["user_id"], r["timestamp"].strftime(TIME_FORMAT),
             r.get("punch_state"), r.get("verify_mode"), drift, now) for r in records]
    before = db.total_changes
    with db:
        db.executemany(
            "INSERT OR IGNORE INTO punch (punch_key, serial, device_user_id, ts, punch_state, verify_mode, drift_seconds,"
            " fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return db.total_changes - before


def queue_depth(db, serial=None):
    q = "SELECT COUNT(*) FROM punch WHERE state != 'confirmed'" + (" AND serial = ?" if serial else "")
    return db.execute(q, (serial,) if serial else ()).fetchone()[0]


# ── server ──────────────────────────────────────────────────────


def http_post(cfg, method, payload):
    url = cfg["server_url"].rstrip("/") + "/api/method/" + method
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "X-Device-Key": device_key(cfg), "User-Agent": f"slhrm-agent/{AGENT_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=cfg["http_timeout_seconds"]) as r:
            return json.loads(r.read().decode()).get("message")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise AgentError(f"HTTP {e.code} {method}: {body}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AgentError(f"{method}: {type(e).__name__}: {e}") from e


def push(db, cfg, retry_held=False, post=http_post, serial=None):
    """Send pending records; confirm each only from its server result. Each record at most once per call."""
    if not device_key(cfg):
        log.warning("push: device_key not configured — nothing sent (records stay queued)")
        return {"sent": 0, "confirmed": 0, "failed": 0, "skipped": "no device_key"}
    if retry_held:
        with db:
            db.execute("UPDATE punch SET state = 'failed', attempts = 0 WHERE state = 'held'")
    for dev in cfg["devices"]:  # unconfirmed rows older than min_punch_date are never sent
        if serial and dev.get("serial") != serial:
            continue  # per-device push touches only its own rows
        if dev.get("serial") and min_ts(dev.get("min_punch_date")):
            with db:
                db.execute("UPDATE punch SET state = 'skipped_old' WHERE serial = ? AND ts < ? AND state IN"
                           " ('queued', 'failed', 'held')", (dev["serial"], min_ts(dev["min_punch_date"])))
    pending = db.execute(
        "SELECT punch_key, serial, device_user_id, ts, punch_state, verify_mode, drift_seconds, attempts FROM punch"
        " WHERE state IN ('queued', 'failed')" + (" AND serial = ?" if serial else "") + " ORDER BY serial, ts",
        (serial,) if serial else ()).fetchall()
    by_serial = {}
    for r in pending:
        by_serial.setdefault(r["serial"], []).append(r)
    totals = Counter()
    for serial, rows in by_serial.items():
        for i in range(0, len(rows), int(cfg["batch_size"])):
            batch = rows[i:i + int(cfg["batch_size"])]
            payload = {"serial": serial, "agent": cfg["agent_name"], "punches": [
                {"device_user_id": r["device_user_id"], "timestamp": r["ts"], "punch_state": r["punch_state"],
                 "verify_mode": r["verify_mode"], "clock_drift_seconds": r["drift_seconds"]} for r in batch]}
            now = utcnow()
            try:
                resp = post(cfg, "slhrm.api.device_ingest", payload)
            except AgentError as e:
                _fail(db, batch, str(e), now)
                totals["failed"] += len(batch)
                log.error("push %s: batch of %d not delivered: %s (stays queued)", serial, len(batch), e)
                return dict(totals, stopped=str(e))  # server unreachable/refusing: stop this run
            results = {r.get("key"): r for r in (resp or {}).get("results", [])}
            with db:
                for r in batch:
                    res = results.get(r["punch_key"])
                    if res and res.get("result") in CONFIRMED_RESULTS:
                        db.execute("UPDATE punch SET state = 'confirmed', server_result = ?, server_name = ?,"
                                   " last_sent_at = ?, confirmed_at = ?, last_error = NULL WHERE punch_key = ?",
                                   (res["result"], res.get("name"), now, now, r["punch_key"]))
                        totals[res["result"]] += 1
                        totals["confirmed"] += 1
                    else:
                        err = (res or {}).get("error") or "no result for this record"
                        _fail_one(db, r, err, now)
                        totals["failed"] += 1
            totals["sent"] += len(batch)
            log.info("push %s: %d sent, results %s", serial, len(batch), (resp or {}).get("counts"))
    return dict(totals)


def _fail_one(db, r, err, now):
    attempts = r["attempts"] + 1
    db.execute("UPDATE punch SET state = ?, attempts = ?, last_error = ?, last_sent_at = ? WHERE punch_key = ?",
               ("held" if attempts >= MAX_ATTEMPTS else "failed", attempts, err[:500], now, r["punch_key"]))


def _fail(db, batch, err, now):
    with db:
        for r in batch:
            _fail_one(db, r, err, now)


# ── commands ────────────────────────────────────────────────────


def read_device(dev, cfg, factory=_zk, with_records=True, with_users=False):
    """Connect (one attempt), read, disconnect. Serial must match the configured serial."""
    t0 = time.monotonic()
    device = connect_configured(dev, cfg, factory)
    try:
        info = device.info()
        if dev.get("serial") and info["serial"] != dev["serial"]:
            raise AgentError(f"serial mismatch on {dev['ip']}: device reports {info['serial']!r}, "
                             f"config expects {dev['serial']!r} — refusing to read")
        dev_time = device.time()
        drift, host_now = clock_drift(dev_time, dev["timezone"])
        sizes = device.sizes()
        users = device.users() if with_users else None
        records = device.attendance() if with_records else None
    finally:
        device.disconnect()
    return {"info": info, "device_time": dev_time, "host_time": host_now, "drift": drift, "sizes": sizes,
            "users": users, "records": records, "read_seconds": round(time.monotonic() - t0, 1)}


def pull_device(db, dev, cfg, factory=_zk):
    serial = dev.get("serial")
    if not serial:
        raise AgentError(f"device {dev['name']}: serial missing in config (run info first)")
    data = read_device(dev, cfg, factory, with_users=True)
    keep, skipped = split_old(data["records"], dev.get("min_punch_date"))
    new = enqueue(db, serial, keep, data["drift"])
    data["skipped_old"] = skipped
    with db:
        db.execute("INSERT INTO device_pull (serial, pulled_at, ok, record_count, new_records, drift_seconds, skipped_old)"
                   " VALUES (?, ?, 1, ?, ?, ?, ?)", (serial, utcnow(), len(data["records"]), new, data["drift"], skipped))
    log.info("pull %s (%s): %d records on device, %d new, %d skipped_old (< %s), drift %+.1fs", dev["name"], serial,
             len(data["records"]), new, skipped, dev.get("min_punch_date") or "-", data["drift"])
    if abs(data["drift"]) > cfg.get("drift_alert_seconds", 120):
        log.warning("pull %s: device clock drift %+.1fs", dev["name"], data["drift"])
    return data, new


def sync_users(db, cfg, dev, users, post=http_post):
    """Send the device user list (id, name, privilege) when it changed since the last successful sync."""
    if users is None or not device_key(cfg):
        return None
    digest = hashlib.sha256(json.dumps(sorted((u["user_id"], u["name"], u["privilege"]) for u in users)).encode()).hexdigest()
    k = f"users_hash:{dev['serial']}"
    row = db.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
    if row and row[0] == digest:
        return "unchanged"
    try:
        res = post(cfg, "slhrm.api.device_users", {"serial": dev["serial"], "agent": cfg["agent_name"], "users": users})
    except AgentError as e:
        log.error("users %s: %s", dev["name"], e)
        return None
    with db:
        db.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, digest))
    log.info("users %s: %s", dev["name"], res)
    return res


def send_heartbeat(cfg, dev, payload, post=http_post):
    if not device_key(cfg):
        return
    try:
        post(cfg, "slhrm.api.device_heartbeat", {"serial": dev["serial"], "agent": cfg["agent_name"], "info": payload})
    except AgentError as e:
        log.error("heartbeat %s: %s", dev["name"], e)


def sync_device(cfg, dev, factory=_zk, post=http_post):
    """ONE device, caller holds its lock: pull → users → heartbeat → push (that serial only). Own queue connection,
    own timeout. Never raises; returns a result dict (also printed by run --once)."""
    t0 = time.monotonic()
    out = {"device": dev["name"], "serial": dev.get("serial"), "connected": False, "error": None, "error_kind": None,
           "new_in_queue": 0, "inserted": 0, "duplicate": 0, "unmatched": 0, "drift_seconds": None,
           "read_seconds": None, "record_count": None}
    db = db_open(cfg["db_path"])
    hb = {"last_pull": utcnow(), "last_pull_tz": "UTC"}
    try:
        try:
            data, new = pull_device(db, dev, cfg, factory)
            out.update(connected=True, new_in_queue=new, drift_seconds=data["drift"], read_seconds=data["read_seconds"],
                       record_count=len(data["records"]))
            out["users"] = sync_users(db, cfg, dev, data["users"], post)
            hb.update(data["info"])
            hb.update({k: v for k, v in data["sizes"].items() if k in ("user_count", "user_capacity", "record_count", "record_capacity")})
            hb.update({"last_pull_ok": 1, "clock_drift_seconds": data["drift"], "last_error": "", "error_kind": "",
                       "read_seconds": data["read_seconds"]})
        except Exception as e:
            out.update(error=str(e)[:500] or type(e).__name__, error_kind=error_kind(e), connected=not isinstance(e, ConnectError))
            log.error("pull %s: %s", dev["name"], e)
            with db:
                db.execute("INSERT INTO device_pull (serial, pulled_at, ok, error) VALUES (?, ?, 0, ?)",
                           (dev.get("serial") or dev["name"], utcnow(), out["error"]))
            hb.update({"last_pull_ok": 0, "last_error": out["error"], "error_kind": out["error_kind"],
                       "read_seconds": round(time.monotonic() - t0, 1)})
        hb["queue_depth"] = queue_depth(db, dev.get("serial"))
        if dev.get("serial"):
            send_heartbeat(cfg, dev, hb, post)
            res = push(db, cfg, post=post, serial=dev["serial"])
            out.update(inserted=res.get("inserted", 0), duplicate=res.get("duplicate", 0),
                       unmatched=res.get("unknown_employee", 0), push_failed=res.get("failed", 0))
            if res.get("stopped"):
                out["push_error"] = res["stopped"]
    finally:
        db.close()
    out["duration_seconds"] = round(time.monotonic() - t0, 1)
    return out


def cmd_run(cfg, factory=_zk, post=http_post):
    """Every enabled device in its own thread with its own lock: a device whose lock is held (its previous read is
    still running) is skipped this time; others are not affected. Returns 1 if any device failed."""
    import threading

    results = {}

    def one(dev):
        with DeviceLock(cfg, dev) as lock:
            if not lock.acquired:
                log.info("run %s: previous read still in progress — skipped", dev["name"])
                results[dev["name"]] = {"busy": True}
                return
            results[dev["name"]] = sync_device(cfg, dev, factory, post)

    threads = [threading.Thread(target=one, args=(d,), name=f"dev-{d['name']}") for d in cfg["devices"] if d.get("enabled", True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bad = [n for n, r in results.items() if r.get("error") or r.get("push_error")]
    return 1 if bad else 0


def cmd_once(cfg, name, factory=_zk, post=http_post, wait=ONCE_LOCK_WAIT):
    """Sync Now: one device (even if disabled in the config), waits up to `wait` s for its lock."""
    dev = get_device_cfg(cfg, name)
    with DeviceLock(cfg, dev, wait=wait) as lock:
        if not lock.acquired:
            return {"device": dev["name"], "busy": True, "error": f"busy: a read of {dev['name']} is in progress — try again"}
        return sync_device(cfg, dev, factory, post)


def cmd_backfill(cfg, name, resend=False, factory=_zk, post=http_post):
    """Whole device log → queue → server, under the run lock. Returns counts by server result."""
    dev = get_device_cfg(cfg, name)
    with DeviceLock(cfg, dev) as lock:
        if not lock.acquired:
            raise AgentError(f"a read of {dev['name']} is in progress — try again")
        db = db_open(cfg["db_path"])
        data, new = pull_device(db, dev, cfg, factory)
        users = sync_users(db, cfg, dev, data["users"], post)
        if resend:
            with db:
                db.execute("UPDATE punch SET state = 'queued', attempts = 0 WHERE serial = ? AND state = 'confirmed'"
                           " AND ts >= ?", (dev["serial"], min_ts(dev.get("min_punch_date")) or ""))
        result = push(db, cfg, post=post, serial=dev["serial"])
        hb = dict(data["info"], last_pull=utcnow(), last_pull_tz="UTC", last_pull_ok=1, clock_drift_seconds=data["drift"],
                  last_error="", error_kind="", read_seconds=data["read_seconds"], queue_depth=queue_depth(db, dev["serial"]),
                  **{k: v for k, v in data["sizes"].items() if k in ("user_count", "user_capacity", "record_count", "record_capacity")})
        send_heartbeat(cfg, dev, hb, post)
        states = dict(db.execute("SELECT state, COUNT(*) FROM punch WHERE serial = ? GROUP BY state", (dev["serial"],)).fetchall())
        db.close()
    return {"device": dev["name"], "records_on_device": len(data["records"]), "new_in_queue": new,
            "skipped_old": data["skipped_old"],
            "drift_seconds": data["drift"], "users": users, "push": result, "queue_states": states}


def _jsonable(o):
    if isinstance(o, datetime):
        return o.strftime(TIME_FORMAT)
    raise TypeError(type(o))


def main(argv=None):
    ap = argparse.ArgumentParser(description="SLHRM biometric agent (read-only device access)")
    ap.add_argument("--config", default=os.path.expanduser("~/slhrm-agent/config.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tcpcheck")
    p = sub.add_parser("probe")
    p.add_argument("--ip", required=True)
    p.add_argument("--port", type=int, default=4370)
    p.add_argument("--timezone", default="Asia/Colombo")
    p = sub.add_parser("info")
    p.add_argument("--device", required=True)
    p = sub.add_parser("users")
    p.add_argument("--device", required=True)
    p.add_argument("--csv")
    p = sub.add_parser("pull")
    p.add_argument("--device")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--since")
    p.add_argument("--per-user", help="dry run: write per-user activity JSON here (chmod 600)")
    p = sub.add_parser("push")
    p.add_argument("--retry-held", action="store_true")
    p = sub.add_parser("backfill")
    p.add_argument("--device", required=True)
    p.add_argument("--resend", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("--once", action="store_true", help="one device only (needs --device); prints a JSON result")
    p.add_argument("--device")
    sub.add_parser("status")
    a = ap.parse_args(argv)

    setup_logging(verbose=a.verbose)
    cfg = load_config(a.config)
    setup_logging(cfg, a.verbose)
    out = None

    if a.cmd == "tcpcheck":
        out = []
        for d in cfg["devices"]:
            ok, ms, err = tcp_check(d["ip"], d["port"], cfg["timeout_seconds"])
            out.append({"device": d["name"], "ip": d["ip"], "port": d["port"], "reachable": ok, "latency_ms": ms, "error": err})
    elif a.cmd == "probe":
        device, pw, transport, attempts = connect_discover(a.ip, a.port, cfg["timeout_seconds"])
        try:
            info = device.info()
            dev_time = device.time()
            drift, host_now = clock_drift(dev_time, a.timezone)
            sizes = device.sizes()
        finally:
            device.disconnect()
        out = {"ip": a.ip, "port": a.port, "password": pw, "transport": transport, "attempts": attempts,
               "info": info, "device_time": dev_time, "host_time": host_now, "drift_seconds": drift, "sizes": sizes}
    elif a.cmd in ("info", "users"):
        dev = get_device_cfg(cfg, a.device)
        data = read_device(dev, cfg, with_records=False, with_users=(a.cmd == "users"))
        if a.cmd == "info":
            out = {"device": dev["name"], "info": data["info"], "device_time": data["device_time"],
                   "host_time": data["host_time"], "drift_seconds": data["drift"], "sizes": data["sizes"]}
        else:
            out = {"device": dev["name"], "serial": data["info"]["serial"], "count": len(data["users"]), "users": data["users"]}
            if a.csv:
                with open(a.csv, "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=["user_id", "name", "privilege"])
                    w.writeheader()
                    w.writerows(data["users"])
    elif a.cmd == "pull" and a.dry_run:
        if not a.device:
            ap.error("pull --dry-run needs --device")
        dev = get_device_cfg(cfg, a.device)
        data = read_device(dev, cfg, with_users=True)
        out = {"device": dev["name"], "serial": data["info"]["serial"], "dry_run": True,
               "device_time": data["device_time"], "drift_seconds": data["drift"], "sizes": data["sizes"],
               "stats": attendance_stats(data["records"], dev["timezone"], a.since, cfg["plausible_from"], data["users"])}
        if a.per_user:
            fd = os.open(a.per_user, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(per_user_activity(data["records"], a.since), f, default=_jsonable, indent=0)
    elif a.cmd == "pull":
        db = db_open(cfg["db_path"])
        devs = [get_device_cfg(cfg, a.device)] if a.device else [d for d in cfg["devices"] if d.get("enabled", True)]
        out = {}
        for dev in devs:
            _data, new = pull_device(db, dev, cfg)
            out[dev["name"]] = {"new": new, "skipped_old": _data["skipped_old"], "queue_depth": queue_depth(db, dev["serial"])}
    elif a.cmd == "push":
        out = push(db_open(cfg["db_path"]), cfg, retry_held=a.retry_held)
    elif a.cmd == "backfill":
        out = cmd_backfill(cfg, a.device, a.resend)
    elif a.cmd == "run" and a.once:
        if not a.device:
            ap.error("run --once needs --device")
        out = cmd_once(cfg, a.device)
    elif a.cmd == "run":
        return cmd_run(cfg)
    elif a.cmd == "status":
        db = db_open(cfg["db_path"])
        out = {"queue": [dict(r) for r in db.execute("SELECT serial, state, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last"
                                                     " FROM punch GROUP BY serial, state ORDER BY serial, state")],
               "min_punch_date": {d["name"]: d.get("min_punch_date") for d in cfg["devices"]},
               "last_pull": [dict(r) for r in db.execute(
                   "SELECT p.serial, p.pulled_at, p.ok, p.record_count, p.new_records, p.skipped_old, p.drift_seconds"
                   " FROM device_pull p JOIN (SELECT serial, MAX(rowid) AS id FROM device_pull GROUP BY serial) m"
                   " ON p.rowid = m.id ORDER BY p.serial")]}
    print(json.dumps(out, indent=1, default=_jsonable, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AgentError as e:
        log.error("%s", e)
        sys.exit(2)
