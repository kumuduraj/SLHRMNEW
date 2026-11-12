"""Biometric device ingestion (SLHRM agent → Biometric Punch Log).

Every raw device record is stored exactly once:
- punch_key = "<device serial>|<device user id>|<YYYY-MM-DD HH:MM:SS device time>", unique DB index;
- per-record result: inserted / duplicate / unknown_employee (stored, status Unmatched) / error;
- one bad record never rolls back the others (savepoint per record);
- records before SLHRM Settings "Biometric Start Date" are not stored (result skipped_old);
- device user ids (v0.2.1): ONE number = ONE person on every device. (a) the Active employee whose ERPNext
  Employee.attendance_device_id ("Attendance Device ID (all devices)", unique company-wide by a DB index) equals
  the id, SITE-WIDE; an employee whose branch the device does not serve still matches, with match_reason
  "other_branch" (report "Device Users Other Branch"). Else (b) if SLHRM Settings "Match Device User by Employee
  Number" is on: the one Active employee of the device's SERVED BRANCHES whose employee_number equals the id and
  whose name contains the name on the device; (b) then writes attendance_device_id (classify_by_number).
  Unmatched records are re-matched when attendance_device_id is set (doc_events on_update). A branch transfer keeps
  the id. slhrm_biometric_device_id is legacy (hidden, copied by patch v0_2_1, never written).
- Blocked User IDs (v0.3.2, Biometric Device child table): a device user id blocked on a device is NEVER matched there —
  checked before (a) and (b) in ingest, rematch and map_device_user; its punches stay Unmatched with match_reason = the
  row's reason ("collision — re-enrol on device" / "HR check — do not match"). apply_blocks() runs on device save.
IN/OUT pairing and OT are NOT decided here (Attendance Marker / slhrm.overtime).

Whitelisted wrappers (API key, fail closed) live in slhrm.api: device_ingest, device_heartbeat.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_system_timezone, getdate, now_datetime

PUNCH = "Biometric Punch Log"
DEVICE = "Biometric Device"
DEVICE_USER = "Biometric Device User"
DEVICE_BRANCH = "Biometric Device Branch"
MAP_ROLES = ("HR Manager", "HR User", "System Manager")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BATCH = 500
FUTURE_TOLERANCE = timedelta(minutes=10)
SETTINGS = "SLHRM Settings"
NUMBER_SETTING = "match_device_user_by_employee_number"
ID_FIELD = "attendance_device_id"  # ERPNext Employee field, unique company-wide (v0.2.1)
OTHER_BRANCH = "other_branch"
BLOCKED = "Biometric Device Blocked User"
BLOCK_COLLISION = "collision — re-enrol on device"
BLOCK_HR_CHECK = "HR check — do not match"
BLOCK_REASONS = (BLOCK_COLLISION, BLOCK_HR_CHECK)

# ZKTeco punch state → Biometric Punch Log.punch_type (the raw state is kept in device_punch_state)
PUNCH_TYPES = {0: "IN", 1: "OUT", 2: "BREAK", 3: "RETURN", 4: "IN", 5: "OUT"}

HEARTBEAT_FIELDS = {
    "platform": cstr, "firmware": cstr, "mac": cstr, "device_reported_name": cstr,
    "last_pull_ok": cint, "clock_drift_seconds": flt,
    "user_count": cint, "user_capacity": cint, "record_count": cint, "record_capacity": cint,
    "queue_depth": cint, "last_error": cstr,
}

# ── connection status (v0.4.0) ──
ONLINE, DELAYED, OFFLINE, DISABLED = "Online", "Delayed", "Offline", "Disabled"
ONLINE_MINUTES, DELAYED_MINUTES = 10, 60
OFFLINE_ERROR_KINDS = ("connect", "auth")  # immediately Offline; timeout / read → Delayed until FAILS_FOR_OFFLINE
FAILS_FOR_OFFLINE = 3
SYNC_RATE_SECONDS = 60
SYNC_ROLES = ("HR Manager", "System Manager")
SYNC_EVENT = "slhrm_device_sync"
AGENT_ONCE_TIMEOUT = 600  # seconds for the whole `run --once` (lock wait 60 s + device timeout + push)


def punch_key(serial, device_user_id, device_time):
    return f"{serial}|{device_user_id}|{device_time.strftime(TIME_FORMAT)}"


def parse_device_time(value):
    return datetime.strptime(cstr(value).strip(), TIME_FORMAT)


def to_site_time(device_time, device_tz, site_tz=None):
    site_tz = site_tz or get_system_timezone()
    if not device_tz or device_tz == site_tz:
        return device_time
    return device_time.replace(tzinfo=ZoneInfo(device_tz)).astimezone(ZoneInfo(site_tz)).replace(tzinfo=None)


def as_branches(branches):
    """A branch name or a list of branch names → tuple of distinct names (order kept)."""
    if not branches:
        return ()
    if isinstance(branches, str):
        branches = [branches]
    return tuple(dict.fromkeys(cstr(b).strip() for b in branches if cstr(b).strip()))


def served_branches(serial, own_branch=None):
    """Branches whose employees a device serves: its own branch + the Served Branches table."""
    rows = frappe.get_all(DEVICE_BRANCH, filters={"parent": serial, "parenttype": DEVICE, "parentfield": "served_branches"},
                          pluck="branch", order_by="idx asc") if serial else []
    return as_branches(([own_branch] if own_branch else []) + rows)


def blocked_ids(serial):
    """{device user id: {reason, note}} blocked on this device (Blocked User IDs)."""
    if not serial:
        return {}
    return {cstr(r.device_user_id).strip(): r for r in frappe.get_all(
        BLOCKED, filters={"parent": serial, "parenttype": DEVICE, "parentfield": "blocked_user_ids"},
        fields=["device_user_id", "reason", "note"])}


def apply_blocks(serial, unblocked=()):
    """Device saved: Pending punches of blocked ids lose their employee (Unmatched + reason); Unmatched ones get the
    reason. Punches already Matched (used by a submitted marker) are left alone (counted). Ids removed from the
    list are re-matched normally. Returns counts."""
    out = {"unmatched": 0, "kept_matched": 0, "rematched": 0}
    for uid, b in blocked_ids(serial).items():
        for r in frappe.get_all(PUNCH, filters={"device_serial": serial, "device_user_id": uid},
                                fields=["name", "processing_status", "match_reason"]):
            if r.processing_status == "Matched":
                out["kept_matched"] += 1
            elif r.processing_status == "Pending":
                frappe.db.set_value(PUNCH, r.name, {"employee": None, "employee_name": None, "employee_number": None,
                                                    "processing_status": "Unmatched", "match_reason": b.reason})
                out["unmatched"] += 1
            elif r.processing_status == "Unmatched" and r.match_reason != b.reason:
                frappe.db.set_value(PUNCH, r.name, "match_reason", b.reason, update_modified=False)
    for uid in unblocked or ():
        frappe.db.set_value(PUNCH, {"device_serial": serial, "device_user_id": uid, "processing_status": "Unmatched",
                                    "match_reason": ["in", BLOCK_REASONS]}, "match_reason", None, update_modified=False)
        out["rematched"] += rematch(uid)
    return out


def devices_serving(branch):
    """[(serial, served branches)] of every device that serves `branch`."""
    out = []
    for d in frappe.get_all(DEVICE, fields=["name", "branch"]):
        served = served_branches(d.name, d.branch)
        if branch in served:
            out.append((d.name, served))
    return out


def resolve_employee(device_user_id, branches, cache=None):
    """Rule (a), SITE-WIDE: the Active employee whose attendance_device_id equals the id (unique index → at most
    one). `other_branch` is set when the device's served branches do not include the employee's branch (still a
    match; match_reason "other_branch"). Nobody → None (Unmatched)."""
    branches = as_branches(branches)
    key = (device_user_id, branches)
    if cache is not None and key in cache:
        return cache[key]
    rows = frappe.get_all(
        "Employee", filters={ID_FIELD: device_user_id, "status": "Active"},
        fields=["name", "employee_name", "employee_number", "branch"],
    ) if device_user_id else []
    emp = rows[0] if len(rows) == 1 else None
    if emp:
        emp.other_branch = emp.branch not in branches
    if cache is not None:
        cache[key] = emp
    return emp


def match_reason_for(emp):
    """match_reason stored on a MATCHED punch: "other_branch" when the employee's branch is not served."""
    return OTHER_BRANCH if emp and emp.get("other_branch") else None


def id_holder(device_user_id, exclude=None):
    """The employee (any status, any branch) that holds this attendance_device_id."""
    uid = cstr(device_user_id).strip()
    if not uid:
        return None
    filters = {ID_FIELD: uid}
    if exclude:
        filters["name"] = ["!=", exclude]
    return frappe.db.get_value("Employee", filters, ["name", "employee_name", "branch", "status"], as_dict=True)


def start_datetime():
    """SLHRM Settings biometric_start_date as a datetime (00:00 site time), or None."""
    d = frappe.db.get_single_value(SETTINGS, "biometric_start_date")
    return datetime.combine(getdate(d), datetime.min.time()) if d else None


def get_device(serial):
    device = frappe.db.get_value(DEVICE, cstr(serial).strip(), ["name", "enabled", "branch", "timezone"], as_dict=True)
    if not device:
        frappe.throw(_("Unknown device serial {0}: register it in Biometric Device first.").format(serial))
    device.branches = served_branches(device.name, device.branch)
    device.blocked = blocked_ids(device.name)
    return device


def ingest(serial, punches, agent=None):
    """Store raw device records. punches: list of
    {device_user_id, timestamp: "YYYY-MM-DD HH:MM:SS" (device time), punch_state, verify_mode}.
    Returns {"results": [{key, result, name?, error?, warning?}], "counts": {...}} in input order."""
    device = get_device(serial)
    if not cint(device.enabled):
        frappe.throw(_("Biometric Device {0} is disabled.").format(device.name))
    if isinstance(punches, str):
        punches = json.loads(punches)
    if not isinstance(punches, list) or not punches:
        frappe.throw(_("punches must be a non-empty list."))
    if len(punches) > MAX_BATCH:
        frappe.throw(_("At most {0} punches per request.").format(MAX_BATCH))

    site_tz = get_system_timezone()
    cache = {"by_number": number_matching_enabled(), "start": start_datetime()}
    results = [_ingest_one(device, p, site_tz, cstr(agent)[:140], cache) for p in punches]
    counts = {}
    for r in results:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    return {"results": results, "counts": counts}


def _ingest_one(device, p, site_tz, agent, cache):
    p = p if isinstance(p, dict) else {}
    uid = cstr(p.get("device_user_id")).strip()
    raw_ts = cstr(p.get("timestamp")).strip()
    out = {"key": f"{device.name}|{uid}|{raw_ts}"}
    try:
        if not uid or "|" in uid:
            raise ValueError("device_user_id missing or invalid")
        device_time = parse_device_time(raw_ts)
        key = punch_key(device.name, uid, device_time)
        out["key"] = key
        site_time = to_site_time(device_time, device.timezone, site_tz)
        if cache.get("start") and site_time < cache["start"]:
            return dict(out, result="skipped_old")
        existing = frappe.db.get_value(PUNCH, {"punch_key": key}, "name")
        if existing:
            return dict(out, result="duplicate", name=existing)

        block = (device.get("blocked") or {}).get(uid)
        if block:  # blocked on this device: never matched (no (a), no (b))
            emp, reason = None, block.reason
        else:
            emp, reason = resolve_employee(uid, device.branches, cache), None
            if not emp and cache.get("by_number"):
                emp, reason = match_by_number(device.name, device.branches, uid, cache)
        state = p.get("punch_state")
        state = None if state in (None, "") else cint(state)
        verify = p.get("verify_mode")
        drift = p.get("clock_drift_seconds")
        doc = frappe.get_doc({
            "doctype": PUNCH,
            "employee": emp.name if emp else None,
            "employee_name": emp.employee_name if emp else None,
            "employee_number": emp.employee_number if emp else None,
            "punch_time": site_time,
            "punch_type": PUNCH_TYPES.get(state, "IN"),
            "processing_status": "Pending" if emp else "Unmatched",
            "match_reason": match_reason_for(emp) if emp else reason,
            "source_device": device.name,
            "device_serial": device.name,
            "device_user_id": uid,
            "device_time": device_time.strftime(TIME_FORMAT),
            "device_timezone": device.timezone,
            "punch_key": key,
            "device_punch_state": state,
            "verify_mode": None if verify in (None, "") else cint(verify),
            "clock_drift_seconds": None if drift in (None, "") else flt(drift),
            "received_at": now_datetime(),
            "agent": agent,
            "raw_data": json.dumps(p, sort_keys=True, default=str)[:1000],
        })
        frappe.db.savepoint("slhrm_ingest")
        try:
            doc.insert(ignore_permissions=True)
        except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
            # a concurrent request stored the same record between the check and the insert
            frappe.db.rollback(save_point="slhrm_ingest")
            return dict(out, result="duplicate", name=frappe.db.get_value(PUNCH, {"punch_key": key}, "name"))
        except Exception:
            frappe.db.rollback(save_point="slhrm_ingest")
            raise
        res = dict(out, result="inserted" if emp else "unknown_employee", name=doc.name)
        if site_time > now_datetime() + FUTURE_TOLERANCE:
            res["warning"] = "future timestamp (device clock?)"
        return res
    except Exception as e:
        return dict(out, result="error", error=cstr(e)[:300])


def connection_status(enabled, last_success_at, last_pull_ok, error_kind=None, consecutive_failures=0, now=None):
    """Pure. Online ≤ 10 min since the last successful read, Delayed ≤ 60 min, else Offline. A failed last run is Offline
    when it could not connect (connect / auth) or failed FAILS_FOR_OFFLINE times in a row; a timeout / read error is
    Delayed (or Offline by age). Disabled device → Disabled."""
    if not cint(enabled):
        return DISABLED
    if not last_success_at:
        return OFFLINE
    now = now or now_datetime()
    age = (now - frappe.utils.get_datetime(last_success_at)).total_seconds() / 60
    if not cint(last_pull_ok):
        if cstr(error_kind) in OFFLINE_ERROR_KINDS or cint(consecutive_failures) >= FAILS_FOR_OFFLINE:
            return OFFLINE
        return OFFLINE if age > DELAYED_MINUTES else DELAYED
    if age <= ONLINE_MINUTES:
        return ONLINE
    return DELAYED if age <= DELAYED_MINUTES else OFFLINE


STATUS_FIELDS = ["name", "device_name", "enabled", "last_success_at", "last_pull_ok", "last_error_kind",
                 "consecutive_failures", "connection_status", "offline_notified", "last_error"]


def update_status(serial, now=None, notify=True):
    """Recompute and store connection_status; notify HR Manager once per Offline period. Returns the status."""
    d = frappe.db.get_value(DEVICE, serial, STATUS_FIELDS, as_dict=True)
    if not d:
        return None
    status = connection_status(d.enabled, d.last_success_at, d.last_pull_ok, d.last_error_kind, d.consecutive_failures, now)
    values = {}
    if status != d.connection_status:
        values["connection_status"] = status
    if status == OFFLINE and not cint(d.offline_notified):
        values["offline_notified"] = 1
        if notify:
            notify_offline(d)
    elif status in (ONLINE, DELAYED) and cint(d.offline_notified):
        values["offline_notified"] = 0  # the offline period is over; the next one notifies again
    if values:
        frappe.db.set_value(DEVICE, serial, values, update_modified=False)
    return status


def refresh_connection_status(notify=True):
    """Scheduler (every 5 min): age-based transitions (Online → Delayed → Offline) when heartbeats stop."""
    out = {d: update_status(d, notify=notify) for d in frappe.get_all(DEVICE, pluck="name")}
    frappe.db.commit()
    return out


def hr_managers():
    users = frappe.get_all("Has Role", filters={"role": "HR Manager", "parenttype": "User"}, pluck="parent", distinct=True)
    return [u for u in users if u not in ("Administrator", "Guest")
            and frappe.db.get_value("User", u, ["enabled", "user_type"], as_dict=True) == {"enabled": 1, "user_type": "System User"}]


def notify_offline(d):
    """One Notification Log (type Alert: bell only, never email) per HR Manager."""
    subject = _("Biometric device {0} is Offline").format(d.device_name or d.name)
    body = _("Last successful sync: {0}. Last error: {1}").format(
        frappe.format_value(d.last_success_at, {"fieldtype": "Datetime"}) if d.last_success_at else _("never"),
        frappe.utils.escape_html(cstr(d.last_error) or "-"))
    for user in hr_managers():
        frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject,
                        "email_content": body, "document_type": DEVICE, "document_name": d.name,
                        "from_user": "Administrator"}).insert(ignore_permissions=True)


def heartbeat(serial, info, agent=None):
    """Agent health report for one device: device info, sizes, clock drift, queue depth, read duration; result of the
    run (last_pull_ok + error_kind) → last_success_at / last_error_at / consecutive_failures → connection_status."""
    device = get_device(serial)
    if isinstance(info, str):
        info = json.loads(info or "{}")
    info = info if isinstance(info, dict) else {}
    values = {k: conv(info[k]) for k, conv in HEARTBEAT_FIELDS.items() if k in info}
    if "read_seconds" in info:
        values["last_read_seconds"] = flt(info["read_seconds"], 1)
    if "last_pull_ok" in info:
        if cint(info["last_pull_ok"]):
            values.update(last_success_at=now_datetime(), consecutive_failures=0, last_error_kind="")
        else:
            values.update(last_error_at=now_datetime(), last_error_kind=cstr(info.get("error_kind"))[:20] or "connect",
                          consecutive_failures=cint(frappe.db.get_value(DEVICE, device.name, "consecutive_failures")) + 1)
    if "last_error" in values:
        values["last_error"] = values["last_error"][:1000]
    if info.get("last_pull"):
        values["last_pull"] = to_site_time(parse_device_time(info["last_pull"]), cstr(info.get("last_pull_tz")) or device.timezone)
    values["last_heartbeat"] = now_datetime()
    values["agent"] = cstr(agent)[:140]
    frappe.db.set_value(DEVICE, device.name, values, update_modified=False)
    return {"ok": True, "status": update_status(device.name)}


# ── Sync Now (v0.4.0) ───────────────────────────────────────────


def agent_command():
    """[python, script, --config, file] of the local agent, from site_config (slhrm_agent_python, slhrm_agent_config,
    optional slhrm_agent_script; default script = the app's SLHRM-AGENT/slhrm_agent.py). None → the agent does not run
    on this server: Sync Now only sets the sync_requested flag (a LAN agent would pick it up)."""
    py, cfg = frappe.conf.get("slhrm_agent_python"), frappe.conf.get("slhrm_agent_config")
    if not (py and cfg):
        return None
    script = frappe.conf.get("slhrm_agent_script") or os.path.abspath(
        os.path.join(frappe.get_app_path("slhrm"), "..", "SLHRM-AGENT", "slhrm_agent.py"))
    return [py, script, "--config", cfg]


@frappe.whitelist(methods=["POST"])
def sync_now(devices):
    """Desk "Sync Now" (form button / list action). HR Manager / System Manager. At most once per device per
    SYNC_RATE_SECONDS (atomic, Redis). Queues run_sync_now per device; the result arrives as realtime SYNC_EVENT.
    Returns {"queued": [serial], "refused": [{device, message}]}."""
    frappe.only_for(SYNC_ROLES)
    if isinstance(devices, str):
        devices = json.loads(devices) if devices.strip().startswith("[") else [devices]
    out = {"queued": [], "refused": []}
    for serial in devices or []:
        d = frappe.get_doc(DEVICE, serial)
        d.check_permission("read")
        if not cint(d.enabled):
            out["refused"].append({"device": d.name, "message": _("{0} is disabled.").format(d.device_name)})
            continue
        key = frappe.cache.make_key(f"slhrm:sync_now:{d.name}")
        if not frappe.cache.set(key, frappe.session.user, ex=SYNC_RATE_SECONDS, nx=True):
            wait = frappe.cache.ttl(key)
            out["refused"].append({"device": d.name, "message": _("Sync Now for {0} was used less than {1} s ago — try again in {2} s.")
                                   .format(d.device_name, SYNC_RATE_SECONDS, max(1, cint(wait)))})
            continue
        frappe.db.set_value(DEVICE, d.name, {"sync_requested": 1, "sync_requested_by": frappe.session.user,
                                             "sync_requested_at": now_datetime()}, update_modified=False)
        frappe.enqueue("slhrm.biometric.run_sync_now", queue="long", timeout=AGENT_ONCE_TIMEOUT + 120, serial=d.name,
                       user=frappe.session.user, enqueue_after_commit=True)
        out["queued"].append(d.name)
    return out


def run_sync_now(serial, user):
    """Background job: the agent once for THIS device (`run --once --device <device_name>`: read-only allowlist, the
    device's own lock — waits up to 60 s, else "busy"). Publishes the result to the requesting user."""
    import time

    d = frappe.db.get_value(DEVICE, serial, ["name", "device_name"], as_dict=True)
    cmd = agent_command()
    t0 = time.monotonic()
    if not cmd:
        result = {"device": d.device_name, "requested": True,
                  "error": _("The agent does not run on this server; it will pick up the request on its next run.")}
    else:
        try:
            proc = subprocess.run(cmd + ["run", "--once", "--device", d.device_name], capture_output=True, text=True,
                                  timeout=AGENT_ONCE_TIMEOUT)
            try:
                result = json.loads(proc.stdout) if proc.stdout.strip() else None
            except ValueError:
                result = None
            if result is None:
                tail = (proc.stderr or "").strip().splitlines()[-1:] or [f"agent exit code {proc.returncode}"]
                result = {"device": d.device_name, "connected": False, "error": tail[0][-500:]}
        except subprocess.TimeoutExpired:
            result = {"device": d.device_name, "connected": False, "error": _("agent did not finish within {0} s").format(AGENT_ONCE_TIMEOUT)}
    result.setdefault("duration_seconds", round(time.monotonic() - t0, 1))
    frappe.db.commit()  # end this job's snapshot: the agent's heartbeat was committed by another request
    values = {"last_sync_result": json.dumps(result, indent=1, default=str)[:5000]}
    if not result.get("requested"):
        values["sync_requested"] = 0
    frappe.db.set_value(DEVICE, serial, values, update_modified=False)
    result["status"] = update_status(serial)
    frappe.db.commit()
    frappe.publish_realtime(SYNC_EVENT, {"serial": serial, "device_name": d.device_name, "result": result}, user=user)
    return result


def rematch(device_user_id=None, by_number=None):
    """Match Unmatched device records (optionally one device user id) to employees: (a) attendance_device_id
    (site-wide), else (b) employee number (setting; by_number overrides it). Records left
    Unmatched get match_reason. Returns the number of records matched."""
    filters = {"processing_status": "Unmatched", "device_user_id": ["is", "set"]}
    if device_user_id:
        filters["device_user_id"] = device_user_id
    by_number = number_matching_enabled() if by_number is None else cint(by_number)
    devices = frappe.get_all(DEVICE, fields=["name", "branch"])
    branches = {d.name: served_branches(d.name, d.branch) for d in devices}
    blocked = {d.name: blocked_ids(d.name) for d in devices}
    groups = {}
    for r in frappe.get_all(PUNCH, filters=filters, fields=["name", "device_serial", "device_user_id", "match_reason"]):
        groups.setdefault((r.device_serial, r.device_user_id), []).append(r)
    cache, matched = {}, 0
    for (serial, uid), rows in groups.items():
        block = blocked.get(serial, {}).get(uid)
        if block:  # never matched on this device
            for r in rows:
                if cstr(r.match_reason) != block.reason:
                    frappe.db.set_value(PUNCH, r.name, "match_reason", block.reason, update_modified=False)
            continue
        emp, reason = resolve_employee(uid, branches.get(serial), cache), None
        if not emp and by_number:
            emp, reason = match_by_number(serial, branches.get(serial), uid, cache)
            if emp:  # the id is now on the Employee; its on_update re-matched these records
                matched += sum(1 for r in rows if frappe.db.get_value(PUNCH, r.name, "employee") == emp.name)
                continue
        for r in rows:
            if emp:
                frappe.db.set_value(PUNCH, r.name, {
                    "employee": emp.name, "employee_name": emp.employee_name, "match_reason": match_reason_for(emp),
                    "employee_number": emp.employee_number, "processing_status": "Pending",
                })
                matched += 1
            elif cstr(r.match_reason) != cstr(reason):
                frappe.db.set_value(PUNCH, r.name, "match_reason", reason, update_modified=False)
    return matched


def on_employee_update(doc, method=None):
    """doc_events Employee.on_update: a new/changed attendance_device_id picks up its Unmatched records
    (explicit id only — never links another employee from inside this save)."""
    if doc.get(ID_FIELD) and doc.has_value_changed(ID_FIELD):
        rematch(cstr(doc.get(ID_FIELD)).strip(), by_number=0)


def on_employee_validate(doc, method=None):
    """doc_events Employee.validate (v0.2.1): attendance_device_id is trimmed (empty → NULL, so the unique index
    allows many employees without one) and must not be held by another employee — one number = one person,
    company-wide. A branch transfer keeps the id."""
    uid = cstr(doc.get(ID_FIELD)).strip()
    doc.set(ID_FIELD, uid or None)
    if not uid or not (doc.is_new() or doc.has_value_changed(ID_FIELD)):
        return
    other = id_holder(uid, exclude=None if doc.is_new() else doc.name)
    if other:
        frappe.throw(_("Attendance Device ID {0} is already used by {1} ({2}, branch {3}, {4}). One number = one person on "
                       "every device: re-enrol one of them on the device with a free number.").format(
                           uid, other.name, other.employee_name, other.branch or "-", other.status),
                     title=_("Attendance Device ID in use"))


# ── (b) match by Employee Number ────────────────────────────────


def number_matching_enabled():
    return cint(frappe.db.get_single_value(SETTINGS, NUMBER_SETTING))


def _norm_name(text):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", cstr(text).lower()).split())


def name_sanity(device_name, employee_name):
    """The name stored on the device appears (whole words, case/punctuation-insensitive) in the
    employee's name. No name on the device → False."""
    dn = _norm_name(device_name)
    return bool(dn) and f" {dn} " in f" {_norm_name(employee_name)} "


def _number_index(cache):
    if cache is not None and "_number_index" in cache:
        return cache["_number_index"]
    by_number, by_id = {}, {}  # by_number keyed (branch, number); by_id keyed id (site-wide, any status)
    for e in frappe.get_all("Employee", fields=["name", "employee_name", "employee_number", "branch", "status", ID_FIELD]):
        did = cstr(e.get(ID_FIELD)).strip()
        if did:
            by_id.setdefault(did, []).append(e)
        if e.status != "Active":
            continue
        num = cstr(e.employee_number).strip().lower()
        if num and e.branch:
            by_number.setdefault((e.branch, num), []).append(e)
    idx = (by_number, by_id)
    if cache is not None:
        cache["_number_index"] = idx
    return idx


def device_user_name(serial, device_user_id):
    return frappe.db.get_value(DEVICE_USER, {"device": serial, "device_user_id": device_user_id}, "user_name")


def classify_by_number(device_user_id, branches, device_name, cache=None):
    """Rule (b) without writing. Returns {result: match|ambiguous|conflict|none, employee (row or None),
    sane (name check), detail}. Hit = Active employee of one of the device's served branches, employee_number ==
    device user id (trimmed, case-insensitive). Conflict: the id is already held by another employee (anywhere,
    any status), or the hit already has a different attendance_device_id (explicit mapping wins)."""
    uid = cstr(device_user_id).strip()
    branches = as_branches(branches)
    by_number, by_id = _number_index(cache)
    hits = [h for b in branches for h in by_number.get((b, uid.lower()), [])] if uid else []
    if not hits:
        return frappe._dict(result="none", employee=None, sane=False, detail="")
    if len(hits) > 1:
        return frappe._dict(result="ambiguous", employee=None, sane=False,
                            detail=", ".join(h.name for h in hits))
    e = hits[0]
    sane = name_sanity(device_name, e.employee_name)
    others = [o for o in by_id.get(uid, []) if o.name != e.name]
    if others:
        return frappe._dict(result="conflict", employee=e, sane=sane,
                            detail=f"id {uid} used by {others[0].name} ({others[0].employee_name})")
    current = cstr(e.get(ID_FIELD)).strip()
    if current and current != uid:
        return frappe._dict(result="conflict", employee=e, sane=sane, detail=f"{e.name} already has device id {current}")
    return frappe._dict(result="match", employee=e, sane=sane, detail="")


def outcome(c):
    """What (b) does with a classification: (link employee?, match_reason for the punches)."""
    if c.result == "match":
        return (True, None) if c.sane else (False, "name_mismatch")
    return False, (c.result if c.result in ("ambiguous", "conflict") else None)


def link_by_number(employee, device_user_id, cache=None):
    """Save attendance_device_id on the Employee (Version + normal hooks; on_update re-matches its records)."""
    emp = frappe.get_doc("Employee", employee)
    emp.set(ID_FIELD, device_user_id)
    emp.flags.ignore_permissions = True
    emp.save(ignore_permissions=True)
    if cache is not None:  # the index / resolve cache now know a different state
        for k in [k for k in cache if isinstance(k, tuple) and k[0] == device_user_id] + ["_number_index"]:
            cache.pop(k, None)
    return frappe._dict(name=emp.name, employee_name=emp.employee_name, employee_number=emp.employee_number,
                        branch=emp.branch)


def match_by_number(serial, branches, device_user_id, cache=None):
    """Rule (b) with writes: (employee row, None) when linked, else (None, match_reason)."""
    c = classify_by_number(device_user_id, branches, device_user_name(serial, device_user_id), cache)
    link, reason = outcome(c)
    if not link:
        return None, reason
    frappe.db.savepoint("slhrm_link")
    try:
        return link_by_number(c.employee.name, cstr(device_user_id).strip(), cache), None
    except Exception:
        frappe.db.rollback(save_point="slhrm_link")
        frappe.log_error(title=f"SLHRM: link device user {device_user_id} to {c.employee.name}")
        return None, None


def employee_number_matching(device=None, dry_run=1, since="2026-10-01"):
    """Bench execute only (review, then apply): every Unmatched device user, classified by rule (b).
    dry_run=1 writes nothing. dry_run=0 links matches whose name check passes (re-matching their punches)
    and stores match_reason on the rest. Returns {"rows": [...], "totals": {...}, "matched": {emp: n}}."""
    cond, values = "", {"since": since}
    if device:
        values["serial"] = frappe.db.get_value(DEVICE, {"device_name": device}, "name") or device
        cond = "and device_serial = %(serial)s"
    groups = frappe.db.sql(f"""
        select device_serial, device_user_id, count(*) as punches,
               sum(case when punch_time >= %(since)s then 1 else 0 end) as recent
        from `tab{PUNCH}`
        where processing_status = 'Unmatched' and ifnull(device_user_id, '') != '' {cond}
        group by device_serial, device_user_id
        order by device_serial, cast(device_user_id as unsigned), device_user_id""", values, as_dict=True)
    devices = {d.name: d for d in frappe.get_all(DEVICE, fields=["name", "device_name", "branch"])}
    for d in devices.values():
        d.branches = served_branches(d.name, d.branch)
    cache, rows, totals, matched = {}, [], {}, {}
    for g in groups:
        d = devices.get(g.device_serial) or frappe._dict()
        dn = device_user_name(g.device_serial, g.device_user_id)
        c = classify_by_number(g.device_user_id, d.get("branches"), dn, cache)
        link, reason = outcome(c)
        key = c.result if c.result != "match" else ("match" if c.sane else "match, name check no")
        totals[key] = totals.get(key, 0) + 1
        row = frappe._dict(device=d.device_name, device_user_id=g.device_user_id, device_name=dn,
                           employee=c.employee.name if c.employee else None,
                           employee_name=c.employee.employee_name if c.employee else None,
                           branch=c.employee.branch if c.employee else d.branch,
                           punches=cint(g.punches), recent=cint(g.recent), result=c.result,
                           name_sanity="yes" if c.sane else "no", detail=c.detail, applied=False)
        rows.append(row)
        if cint(dry_run):
            continue
        if link:
            emp, _r = match_by_number(g.device_serial, d.get("branches"), g.device_user_id, cache)
            if emp:
                row.applied = True
                matched[emp.name] = frappe.db.count(PUNCH, {"device_user_id": g.device_user_id, "employee": emp.name})
                continue
        frappe.db.set_value(PUNCH, {"device_serial": g.device_serial, "device_user_id": g.device_user_id,
                                    "processing_status": "Unmatched"}, "match_reason", reason, update_modified=False)
    if not cint(dry_run):
        frappe.db.commit()
    return {"rows": rows, "totals": totals, "matched": matched}


# ── device users (names for the mapping screen) ─────────────────


def sync_users(serial, users):
    """Upsert the device's user list (user_id, name, privilege). Users missing from the list are kept
    with on_device = 0. Returns counts."""
    device = get_device(serial)
    if isinstance(users, str):
        users = json.loads(users)
    if not isinstance(users, list):
        frappe.throw(_("users must be a list."))
    now = now_datetime()
    seen, created, updated = set(), 0, 0
    existing = {r.device_user_id: r for r in frappe.get_all(
        DEVICE_USER, filters={"device": device.name}, fields=["name", "device_user_id", "user_name", "privilege", "on_device"])}
    for u in users:
        uid = cstr((u or {}).get("user_id")).strip()
        if not uid or "|" in uid:
            continue
        seen.add(uid)
        name, priv = cstr(u.get("name")).strip()[:140], cint(u.get("privilege"))
        row = existing.get(uid)
        if not row:
            frappe.get_doc({"doctype": DEVICE_USER, "user_key": f"{device.name}|{uid}", "device": device.name,
                            "device_user_id": uid, "user_name": name, "privilege": priv, "on_device": 1,
                            "last_synced": now}).insert(ignore_permissions=True)
            created += 1
        elif (row.user_name, cint(row.privilege), cint(row.on_device)) != (name, priv, 1):
            frappe.db.set_value(DEVICE_USER, row.name, {"user_name": name, "privilege": priv, "on_device": 1, "last_synced": now})
            updated += 1
    gone = [r.name for uid, r in existing.items() if uid not in seen and cint(r.on_device)]
    for n in gone:
        frappe.db.set_value(DEVICE_USER, n, {"on_device": 0, "last_synced": now})
    return {"users": len(seen), "created": created, "updated": updated, "no_longer_on_device": len(gone)}


# ── mapping suggestions + Map to Employee ───────────────────────


def _tokens(text):
    return re.sub(r"[^a-z ]", " ", cstr(text).lower()).split()


def mapping_candidates():
    """Active employees without an attendance_device_id, with name tokens (for suggest_employee)."""
    rows = frappe.get_all("Employee", filters={"status": "Active", ID_FIELD: ["in", ["", None]]},
                          fields=["name", "employee_name", "first_name", "middle_name", "last_name", "branch"])
    for e in rows:
        e.tokens = set(_tokens(e.employee_name)) | set(_tokens(e.first_name)) | set(_tokens(e.middle_name)) | set(_tokens(e.last_name))
        e.full = " ".join(_tokens(e.employee_name))
    return rows


def suggest_employee(device_name, branches, employees):
    """(employee, confidence) for a name stored on a device — same rules as the review CSV:
    exact full name / all name tokens (high), first-name only (medium) within the device's served branches;
    other branch, similar spelling or several candidates → low / ambiguous; else (None, "none")."""
    branches = as_branches(branches)
    dn = " ".join(_tokens(device_name))
    dtok = set(dn.split())
    if not dn:
        return None, "none"
    cands = [(e, "exact") if dn == e.full else (e, "tokens") for e in employees if dn == e.full or dtok <= e.tokens]
    if not cands:
        scored = []
        for e in employees:
            r = max([SequenceMatcher(None, dn, t).ratio() for t in e.tokens] + [SequenceMatcher(None, dn, e.full).ratio()])
            if r >= 0.85:
                scored.append((r, e))
        cands = [(e, "similar") for r, e in sorted(scored, key=lambda x: -x[0])]
    in_branch = [c for c in cands if c[0].branch in branches]
    if len(in_branch) == 1:
        e, how = in_branch[0]
        if how == "similar":
            return e, "low (similar name)"
        if how == "exact" or len(dtok) > 1:
            return e, "high"
        return e, "medium (first name)"
    if len(in_branch) > 1:
        return in_branch[0][0], f"ambiguous ({len(in_branch)} in branch)"
    if len(cands) == 1:
        return cands[0][0], f"low (other branch: {cands[0][0].branch})"
    if len(cands) > 1:
        return cands[0][0], f"ambiguous ({len(cands)} candidates)"
    return None, "none"


@frappe.whitelist(methods=["POST"])
def map_device_user(device_serial, device_user_id, employee, replace=0):
    """Desk "Map to Employee": set Employee.attendance_device_id; its Unmatched punches re-match (Employee
    on_update). One number = one person: refused ({"refused": message}, no exception) when another employee holds
    the id, the employee is not active, or the device user has no punches. An employee of a branch the device does
    not serve is allowed (other_branch in the result; punches carry match_reason "other_branch").
    If the employee already has a different id, returns {"confirm": ...} unless replace=1.
    Role / permission failures still raise."""
    frappe.only_for(MAP_ROLES)
    device_user_id = cstr(device_user_id).strip()
    device = get_device(device_serial)
    if not device_user_id or not frappe.db.exists(PUNCH, {"device_serial": device.name, "device_user_id": device_user_id}):
        return {"refused": _("No punches of device user {0} on {1}.").format(device_user_id, device.name)}
    if device_user_id in (device.blocked or {}):
        b = device.blocked[device_user_id]
        return {"refused": _("Device user {0} is blocked on {1} ({2}). Remove it from Blocked User IDs first.").format(
            device_user_id, device.name, b.reason)}
    emp = frappe.get_doc("Employee", employee)
    emp.check_permission("write")
    if emp.status != "Active":
        return {"refused": _("Employee {0} is not active.").format(emp.name)}
    other = id_holder(device_user_id, exclude=emp.name)
    if other:
        return {"refused": _("Attendance Device ID {0} is already used by {1} ({2}, branch {3}). One number = one person: "
                             "re-enrol one of them on the device with a free number.").format(
                                 device_user_id, other.name, other.employee_name, other.branch or "-")}
    other_branch = emp.branch not in (device.branches or ())
    current = cstr(emp.get(ID_FIELD)).strip()
    if current == device_user_id:
        return {"matched": rematch(device_user_id), "employee": emp.name, "unchanged": True, "other_branch": other_branch}
    if current and not cint(replace):
        return {"confirm": _("{0} already has Attendance Device ID {1}. Replace it with {2}? Punches already matched to {1} stay matched.")
                .format(emp.employee_name, current, device_user_id)}
    emp.set(ID_FIELD, device_user_id)
    emp.save()  # on_update → rematch(device_user_id)
    matched = frappe.db.count(PUNCH, {"device_user_id": device_user_id, "employee": emp.name})
    return {"matched": matched, "employee": emp.name, "other_branch": other_branch, "branch": emp.branch}


# ── reports / checks (read-only) ────────────────────────────────


def other_branch_rows(device=None):
    """Matched punches whose employee's branch the device does not serve (match_reason other_branch)."""
    rows = frappe.db.sql(f"""
        select device_serial, device_user_id, employee, employee_name, count(*) as punches,
               min(punch_time) as first_punch, max(punch_time) as last_punch
        from `tab{PUNCH}`
        where match_reason = %(reason)s and ifnull(employee, '') != '' {"and device_serial = %(device)s" if device else ""}
        group by device_serial, device_user_id, employee, employee_name
        order by device_serial, employee""", {"reason": OTHER_BRANCH, "device": device}, as_dict=True)
    devices = {d.name: d for d in frappe.get_all(DEVICE, fields=["name", "device_name", "branch"])}
    for r in rows:
        d = devices.get(r.device_serial) or frappe._dict()
        r.device_name = d.device_name or r.device_serial
        r.served_branches = ", ".join(served_branches(r.device_serial, d.branch))
        r.employee_branch = frappe.db.get_value("Employee", r.employee, "branch")
        r.user_name = device_user_name(r.device_serial, r.device_user_id)
    return rows


def device_id_collisions(serial):
    """Before a device goes live (bench execute, read-only): its device users (synced by the agent) whose id is
    already the attendance_device_id of another employee. Each hit is classed by the name on the device:
    same_person (name check passes), similar (spelling variant, ratio >= 0.6 on a name token — HR checks),
    no_name (empty / "NN-…" placeholder — HR checks), collisions (name clearly differs → re-enrol that device user
    with a free number). Returns {"device", "served", "users", "collisions", "similar", "no_name", "same_person"}."""
    device = get_device(serial)
    users = frappe.get_all(DEVICE_USER, filters={"device": device.name, "on_device": 1}, fields=["device_user_id", "user_name"])
    holders = {cstr(e.get(ID_FIELD)).strip(): e for e in frappe.get_all(
        "Employee", filters={ID_FIELD: ["is", "set"]}, fields=["name", "employee_name", "branch", "status", ID_FIELD])}
    out = {"device": device.name, "served": device.branches, "users": len(users),
           "collisions": [], "similar": [], "no_name": [], "same_person": [], "blocked": sorted(device.blocked)}
    for u in users:
        h = holders.get(cstr(u.device_user_id).strip())
        if not h:
            continue
        row = {"device_user_id": u.device_user_id, "name_on_device": u.user_name, "holder": h.name,
               "holder_name": h.employee_name, "holder_branch": h.branch, "holder_status": h.status,
               "blocked": (device.blocked.get(cstr(u.device_user_id).strip()) or {}).get("reason")}
        dn = cstr(u.user_name).strip()
        if name_sanity(dn, h.employee_name):
            out["same_person"].append(row)
        elif not dn or re.fullmatch(r"(?i)nn-?\d*", dn):
            out["no_name"].append(row)
        elif any(SequenceMatcher(None, a, b).ratio() >= 0.6 for a in _tokens(dn) for b in _tokens(h.employee_name)):
            out["similar"].append(row)
        else:
            out["collisions"].append(row)
    print(json.dumps(out, indent=1, default=str))
    return out
