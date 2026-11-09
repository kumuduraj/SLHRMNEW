#!/usr/bin/env python3
"""SLHRM biometric agent — reads ZKTeco devices READ-ONLY and delivers every raw attendance record to
SLHRM exactly once (slhrm.api.device_ingest). See README.md.

Device rules (hard): only the pyzk calls in ALLOWED_DEVICE_CALLS are ever made (ReadOnlyDevice enforces
it). Never clear, write, disable, set the time, restart. One connection per device at a time (run lock),
timeout 10 s, ommit_ping. At most 2 connect attempts per device per command; never retried in a loop.

Zero loss / zero duplicates:
- every device record → local SQLite queue by punch_key "<serial>|<device user id>|<YYYY-MM-DD HH:MM:SS>"
  (INSERT OR IGNORE of the WHOLE device log on every pull: the overlap window is the full log, so clock
  corrections, same-second punches and late records can never be skipped);
- a record is "confirmed" only by the server's per-record result (inserted / duplicate /
  unknown_employee); errors stay queued and are retried on the next run; nothing is ever dropped.

Commands (all need --config, a chmod-600 JSON file):
  tcpcheck                         TCP connect test to every configured device (no device protocol)
  probe --ip IP [--port P]         find the comm password (0, then 111111; max 2 attempts) + read info
  info  --device NAME              device info, sizes and clock drift (configured password)
  users --device NAME [--csv F]    device users: user_id, name, privilege (no PINs/cards/templates)
  pull  --device NAME --dry-run    attendance statistics only; nothing stored or sent
  pull  [--device NAME]            read device(s) into the local queue
  push  [--retry-held]             send queued records to SLHRM
  run                              lock; every enabled device: pull + heartbeat; then push
  status                           queue counts per device and state
"""
import argparse
import csv
import fcntl
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

AGENT_VERSION = "0.1.0"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ALLOWED_DEVICE_CALLS = frozenset({
    "connect", "get_serialnumber", "get_firmware_version", "get_device_name", "get_platform", "get_mac",
    "get_time", "read_sizes", "get_users", "get_attendance", "disconnect",
})
DEFAULT_PASSWORDS = (0, 111111)
MAX_CONNECT_ATTEMPTS = 2
CONFIRMED_RESULTS = frozenset({"inserted", "duplicate", "unknown_employee"})
MAX_ATTEMPTS = 20  # per record; then "held" (kept, reported; push --retry-held)
FUTURE_TOLERANCE = timedelta(minutes=10)

log = logging.getLogger("slhrm_agent")


class AgentError(Exception):
    pass


class AuthError(AgentError):
    pass


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
    base = os.path.dirname(os.path.abspath(path))
    cfg.setdefault("db_path", os.path.join(base, "queue.sqlite"))
    cfg.setdefault("lock_path", os.path.join(base, "agent.lock"))
    cfg.setdefault("devices", [])
    for d in cfg["devices"]:
        d.setdefault("port", 4370)
        d.setdefault("timezone", "Asia/Colombo")
        d.setdefault("transport", "tcp")
        d.setdefault("enabled", True)
    return cfg


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


class ReadOnlyDevice:
    """The only way the agent talks to a device: allowed pyzk calls only."""

    def __init__(self, conn):
        self._conn = conn

    def _call(self, name, *args):
        if name not in ALLOWED_DEVICE_CALLS:
            raise AgentError(f"forbidden device call: {name}")
        return getattr(self._conn, name)(*args)

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
        conn = zk.connect()  # allowed call
    except Exception as e:
        if _is_auth_error(e):
            raise AuthError(str(e)) from e
        raise AgentError(f"{type(e).__name__}: {e}") from e
    return ReadOnlyDevice(conn)


def connect_configured(dev, cfg, factory=_zk):
    """Configured device: exactly one attempt with its known password and transport."""
    return connect_once(dev["ip"], dev["port"], dev["password"], dev["transport"], cfg["timeout_seconds"], factory)


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
CREATE TABLE IF NOT EXISTS device_pull (
    serial TEXT NOT NULL,
    pulled_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    record_count INTEGER,
    new_records INTEGER,
    drift_seconds REAL,
    error TEXT
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
    return db


def make_key(serial, user_id, ts):
    return f"{serial}|{user_id}|{ts.strftime(TIME_FORMAT)}"


def enqueue(db, serial, records):
    """INSERT OR IGNORE every record. Returns the number of NEW records."""
    now = utcnow()
    rows = [(make_key(serial, r["user_id"], r["timestamp"]), serial, r["user_id"], r["timestamp"].strftime(TIME_FORMAT),
             r.get("punch_state"), r.get("verify_mode"), now) for r in records]
    before = db.total_changes
    with db:
        db.executemany(
            "INSERT OR IGNORE INTO punch (punch_key, serial, device_user_id, ts, punch_state, verify_mode, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
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
                 "X-Device-Key": cfg.get("api_key") or "", "User-Agent": f"slhrm-agent/{AGENT_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=cfg["http_timeout_seconds"]) as r:
            return json.loads(r.read().decode()).get("message")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise AgentError(f"HTTP {e.code} {method}: {body}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AgentError(f"{method}: {type(e).__name__}: {e}") from e


def push(db, cfg, retry_held=False, post=http_post):
    """Send pending records; confirm each only from its server result. Each record at most once per call."""
    if not cfg.get("api_key"):
        log.warning("push: api_key not configured — nothing sent (records stay queued)")
        return {"sent": 0, "confirmed": 0, "failed": 0, "skipped": "no api_key"}
    if retry_held:
        with db:
            db.execute("UPDATE punch SET state = 'failed', attempts = 0 WHERE state = 'held'")
    pending = db.execute(
        "SELECT punch_key, serial, device_user_id, ts, punch_state, verify_mode, attempts FROM punch"
        " WHERE state IN ('queued', 'failed') ORDER BY serial, ts").fetchall()
    by_serial = {}
    for r in pending:
        by_serial.setdefault(r["serial"], []).append(r)
    totals = Counter()
    for serial, rows in by_serial.items():
        for i in range(0, len(rows), int(cfg["batch_size"])):
            batch = rows[i:i + int(cfg["batch_size"])]
            payload = {"serial": serial, "agent": cfg["agent_name"], "punches": [
                {"device_user_id": r["device_user_id"], "timestamp": r["ts"],
                 "punch_state": r["punch_state"], "verify_mode": r["verify_mode"]} for r in batch]}
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
            "users": users, "records": records}


def pull_device(db, dev, cfg, factory=_zk):
    serial = dev.get("serial")
    if not serial:
        raise AgentError(f"device {dev['name']}: serial missing in config (run info first)")
    data = read_device(dev, cfg, factory)
    new = enqueue(db, serial, data["records"])
    with db:
        db.execute("INSERT INTO device_pull (serial, pulled_at, ok, record_count, new_records, drift_seconds)"
                   " VALUES (?, ?, 1, ?, ?, ?)", (serial, utcnow(), len(data["records"]), new, data["drift"]))
    log.info("pull %s (%s): %d records on device, %d new, drift %+.1fs", dev["name"], serial,
             len(data["records"]), new, data["drift"])
    if abs(data["drift"]) > cfg.get("drift_alert_seconds", 120):
        log.warning("pull %s: device clock drift %+.1fs", dev["name"], data["drift"])
    return data, new


def send_heartbeat(cfg, dev, payload, post=http_post):
    if not cfg.get("api_key"):
        return
    try:
        post(cfg, "slhrm.api.device_heartbeat", {"serial": dev["serial"], "agent": cfg["agent_name"], "info": payload})
    except AgentError as e:
        log.error("heartbeat %s: %s", dev["name"], e)


def cmd_run(cfg, factory=_zk, post=http_post):
    with open(cfg["lock_path"], "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("run: another run is in progress — exiting")
            return 0
        return _run_locked(cfg, factory, post)


def _run_locked(cfg, factory, post):
    errors = 0
    db = db_open(cfg["db_path"])
    for dev in cfg["devices"]:
        if not dev.get("enabled", True):
            continue
        hb = {"last_pull": utcnow(), "last_pull_tz": "UTC"}
        try:
            data, _new = pull_device(db, dev, cfg, factory)
            hb.update(data["info"])
            hb.update({k: v for k, v in data["sizes"].items() if k in ("user_count", "user_capacity", "record_count", "record_capacity")})
            hb.update({"last_pull_ok": 1, "clock_drift_seconds": data["drift"], "last_error": ""})
        except Exception as e:
            errors += 1
            log.error("pull %s: %s", dev["name"], e)
            with db:
                db.execute("INSERT INTO device_pull (serial, pulled_at, ok, error) VALUES (?, ?, 0, ?)",
                           (dev.get("serial") or dev["name"], utcnow(), str(e)[:500]))
            hb.update({"last_pull_ok": 0, "last_error": str(e)[:500]})
        hb["queue_depth"] = queue_depth(db, dev.get("serial"))
        if dev.get("serial"):
            send_heartbeat(cfg, dev, hb, post)
    result = push(db, cfg, post=post)
    if result.get("stopped"):
        errors += 1
    db.close()
    return 1 if errors else 0


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
    sub.add_parser("run")
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
            out[dev["name"]] = {"new": new, "queue_depth": queue_depth(db, dev["serial"])}
    elif a.cmd == "push":
        out = push(db_open(cfg["db_path"]), cfg, retry_held=a.retry_held)
    elif a.cmd == "run":
        return cmd_run(cfg)
    elif a.cmd == "status":
        db = db_open(cfg["db_path"])
        out = [dict(r) for r in db.execute("SELECT serial, state, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last"
                                           " FROM punch GROUP BY serial, state ORDER BY serial, state")]
    print(json.dumps(out, indent=1, default=_jsonable, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AgentError as e:
        log.error("%s", e)
        sys.exit(2)
