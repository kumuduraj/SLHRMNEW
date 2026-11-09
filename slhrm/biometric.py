"""Biometric device ingestion (SLHRM agent → Biometric Punch Log).

Every raw device record is stored exactly once:
- punch_key = "<device serial>|<device user id>|<YYYY-MM-DD HH:MM:SS device time>", unique DB index;
- per-record result: inserted / duplicate / unknown_employee (stored, status Unmatched) / error;
- one bad record never rolls back the others (savepoint per record);
- device user ids are matched to Employee.slhrm_biometric_device_id (preferring the device's branch);
  unmatched records are re-matched when the mapping is set on the Employee (doc_events on_update).
IN/OUT pairing and OT are NOT decided here (Attendance Marker / slhrm.overtime).

Whitelisted wrappers (API key, fail closed) live in slhrm.api: device_ingest, device_heartbeat.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_system_timezone, now_datetime

PUNCH = "Biometric Punch Log"
DEVICE = "Biometric Device"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BATCH = 500
FUTURE_TOLERANCE = timedelta(minutes=10)

# ZKTeco punch state → Biometric Punch Log.punch_type (the raw state is kept in device_punch_state)
PUNCH_TYPES = {0: "IN", 1: "OUT", 2: "BREAK", 3: "RETURN", 4: "IN", 5: "OUT"}

HEARTBEAT_FIELDS = {
    "platform": cstr, "firmware": cstr, "mac": cstr, "device_reported_name": cstr,
    "last_pull_ok": cint, "clock_drift_seconds": flt,
    "user_count": cint, "user_capacity": cint, "record_count": cint, "record_capacity": cint,
    "queue_depth": cint, "last_error": cstr,
}


def punch_key(serial, device_user_id, device_time):
    return f"{serial}|{device_user_id}|{device_time.strftime(TIME_FORMAT)}"


def parse_device_time(value):
    return datetime.strptime(cstr(value).strip(), TIME_FORMAT)


def to_site_time(device_time, device_tz, site_tz=None):
    site_tz = site_tz or get_system_timezone()
    if not device_tz or device_tz == site_tz:
        return device_time
    return device_time.replace(tzinfo=ZoneInfo(device_tz)).astimezone(ZoneInfo(site_tz)).replace(tzinfo=None)


def resolve_employee(device_user_id, branch, cache=None):
    """Employee for a device user id: the one in the device's branch, else the only one anywhere.
    Ambiguous (several, none in the branch / several in the branch) → None (stored Unmatched)."""
    if cache is not None and (device_user_id, branch) in cache:
        return cache[(device_user_id, branch)]
    rows = frappe.get_all(
        "Employee",
        filters={"slhrm_biometric_device_id": device_user_id},
        fields=["name", "employee_name", "employee_number", "branch"],
    )
    in_branch = [r for r in rows if branch and r.branch == branch]
    emp = in_branch[0] if len(in_branch) == 1 else (rows[0] if len(rows) == 1 and not in_branch else None)
    if cache is not None:
        cache[(device_user_id, branch)] = emp
    return emp


def get_device(serial):
    device = frappe.db.get_value(DEVICE, cstr(serial).strip(), ["name", "enabled", "branch", "timezone"], as_dict=True)
    if not device:
        frappe.throw(_("Unknown device serial {0}: register it in Biometric Device first.").format(serial))
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
    cache = {}
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
        existing = frappe.db.get_value(PUNCH, {"punch_key": key}, "name")
        if existing:
            return dict(out, result="duplicate", name=existing)

        site_time = to_site_time(device_time, device.timezone, site_tz)
        emp = resolve_employee(uid, device.branch, cache)
        state = p.get("punch_state")
        state = None if state in (None, "") else cint(state)
        verify = p.get("verify_mode")
        doc = frappe.get_doc({
            "doctype": PUNCH,
            "employee": emp.name if emp else None,
            "employee_name": emp.employee_name if emp else None,
            "employee_number": emp.employee_number if emp else None,
            "punch_time": site_time,
            "punch_type": PUNCH_TYPES.get(state, "IN"),
            "processing_status": "Pending" if emp else "Unmatched",
            "source_device": device.name,
            "device_serial": device.name,
            "device_user_id": uid,
            "device_time": device_time.strftime(TIME_FORMAT),
            "device_timezone": device.timezone,
            "punch_key": key,
            "device_punch_state": state,
            "verify_mode": None if verify in (None, "") else cint(verify),
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


def heartbeat(serial, info, agent=None):
    """Agent health report for one device: device info, sizes, clock drift, queue depth."""
    device = get_device(serial)
    if isinstance(info, str):
        info = json.loads(info or "{}")
    info = info if isinstance(info, dict) else {}
    values = {k: conv(info[k]) for k, conv in HEARTBEAT_FIELDS.items() if k in info}
    if "last_error" in values:
        values["last_error"] = values["last_error"][:1000]
    if info.get("last_pull"):
        values["last_pull"] = to_site_time(parse_device_time(info["last_pull"]), cstr(info.get("last_pull_tz")) or device.timezone)
    values["last_heartbeat"] = now_datetime()
    values["agent"] = cstr(agent)[:140]
    frappe.db.set_value(DEVICE, device.name, values, update_modified=False)
    return {"ok": True}


def rematch(device_user_id=None):
    """Match Unmatched device records (optionally one device user id) to employees. Returns the count."""
    filters = {"processing_status": "Unmatched", "device_user_id": ["is", "set"]}
    if device_user_id:
        filters["device_user_id"] = device_user_id
    branches = {d.name: d.branch for d in frappe.get_all(DEVICE, fields=["name", "branch"])}
    cache, matched = {}, 0
    for r in frappe.get_all(PUNCH, filters=filters, fields=["name", "device_serial", "device_user_id"]):
        emp = resolve_employee(r.device_user_id, branches.get(r.device_serial), cache)
        if emp:
            frappe.db.set_value(PUNCH, r.name, {
                "employee": emp.name, "employee_name": emp.employee_name,
                "employee_number": emp.employee_number, "processing_status": "Pending",
            })
            matched += 1
    return matched


def on_employee_update(doc, method=None):
    """doc_events Employee.on_update: a new/changed device user id picks up its Unmatched records."""
    if doc.get("slhrm_biometric_device_id") and doc.has_value_changed("slhrm_biometric_device_id"):
        rematch(cstr(doc.slhrm_biometric_device_id).strip())
