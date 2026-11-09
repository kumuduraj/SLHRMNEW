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
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_system_timezone, now_datetime

PUNCH = "Biometric Punch Log"
DEVICE = "Biometric Device"
DEVICE_USER = "Biometric Device User"
MAP_ROLES = ("HR Manager", "HR User", "System Manager")
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
        drift = p.get("clock_drift_seconds")
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
    """Active employees without a device id, with name tokens (for suggest_employee)."""
    rows = frappe.get_all("Employee", filters={"status": "Active", "slhrm_biometric_device_id": ["in", ["", None]]},
                          fields=["name", "employee_name", "first_name", "middle_name", "last_name", "branch"])
    for e in rows:
        e.tokens = set(_tokens(e.employee_name)) | set(_tokens(e.first_name)) | set(_tokens(e.middle_name)) | set(_tokens(e.last_name))
        e.full = " ".join(_tokens(e.employee_name))
    return rows


def suggest_employee(device_name, branch, employees):
    """(employee, confidence) for a name stored on a device — same rules as the review CSV:
    exact full name / all name tokens (high), first-name only (medium) within the device's branch;
    other branch, similar spelling or several candidates → low / ambiguous; else (None, "none")."""
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
    in_branch = [c for c in cands if branch and c[0].branch == branch]
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
    """Desk "Map to Employee": set Employee.slhrm_biometric_device_id; its Unmatched punches re-match
    (Employee on_update). Refused when another active employee already uses the id. If the employee
    already has a different id, returns {"confirm": ...} unless replace=1."""
    frappe.only_for(MAP_ROLES)
    device_user_id = cstr(device_user_id).strip()
    device = get_device(device_serial)
    if not device_user_id or not frappe.db.exists(PUNCH, {"device_serial": device.name, "device_user_id": device_user_id}):
        frappe.throw(_("No punches of device user {0} on {1}.").format(device_user_id, device.name))
    emp = frappe.get_doc("Employee", employee)
    emp.check_permission("write")
    if emp.status != "Active":
        frappe.throw(_("Employee {0} is not active.").format(emp.name))
    other = frappe.db.get_value("Employee", {"slhrm_biometric_device_id": device_user_id, "status": "Active",
                                             "name": ["!=", emp.name]}, ["name", "employee_name"], as_dict=True)
    if other:
        frappe.throw(_("Device user id {0} is already used by {1} ({2}).").format(device_user_id, other.name, other.employee_name))
    current = cstr(emp.slhrm_biometric_device_id).strip()
    if current == device_user_id:
        return {"matched": rematch(device_user_id), "employee": emp.name, "unchanged": True}
    if current and not cint(replace):
        return {"confirm": _("{0} already has device user id {1}. Replace it with {2}? Punches already matched to {1} stay matched.")
                .format(emp.employee_name, current, device_user_id)}
    emp.slhrm_biometric_device_id = device_user_id
    emp.save()  # on_update → rematch(device_user_id)
    matched = frappe.db.count(PUNCH, {"device_user_id": device_user_id, "employee": emp.name})
    return {"matched": matched, "employee": emp.name}
