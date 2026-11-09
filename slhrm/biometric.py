"""Biometric device ingestion (SLHRM agent → Biometric Punch Log).

Every raw device record is stored exactly once:
- punch_key = "<device serial>|<device user id>|<YYYY-MM-DD HH:MM:SS device time>", unique DB index;
- per-record result: inserted / duplicate / unknown_employee (stored, status Unmatched) / error;
- one bad record never rolls back the others (savepoint per record);
- records before SLHRM Settings "Biometric Start Date" are not stored (result skipped_old);
- device user ids are matched (a) to the one Active employee of the device's branch whose
  slhrm_biometric_device_id equals the id (branch-scoped: ids are unique per branch, not globally), else (b) if SLHRM Settings "Match Device User by Employee Number" is on: to the one Active employee of the
  device's branch whose employee_number equals the id and whose name contains the name on the device; (b)
  then saves the id on the Employee, so the link is explicit from then on (classify_by_number);
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
from frappe.utils import cint, cstr, flt, get_system_timezone, getdate, now_datetime

PUNCH = "Biometric Punch Log"
DEVICE = "Biometric Device"
DEVICE_USER = "Biometric Device User"
MAP_ROLES = ("HR Manager", "HR User", "System Manager")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BATCH = 500
FUTURE_TOLERANCE = timedelta(minutes=10)
SETTINGS = "SLHRM Settings"
NUMBER_SETTING = "match_device_user_by_employee_number"

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
    """Rule (a), branch-scoped: the ONE Active employee of the device's branch whose slhrm_biometric_device_id
    equals the id. No branch on the device, nobody, or several (data error) → None (stored Unmatched)."""
    if cache is not None and (device_user_id, branch) in cache:
        return cache[(device_user_id, branch)]
    rows = frappe.get_all(
        "Employee",
        filters={"slhrm_biometric_device_id": device_user_id, "branch": branch, "status": "Active"},
        fields=["name", "employee_name", "employee_number", "branch"],
    ) if branch and device_user_id else []
    emp = rows[0] if len(rows) == 1 else None
    if cache is not None:
        cache[(device_user_id, branch)] = emp
    return emp


def id_holder(device_user_id, branch, exclude=None):
    """Another Active employee of the branch that already holds this device user id (ids are per branch)."""
    filters = {"slhrm_biometric_device_id": cstr(device_user_id).strip(), "branch": branch, "status": "Active"}
    if exclude:
        filters["name"] = ["!=", exclude]
    return frappe.db.get_value("Employee", filters, ["name", "employee_name"], as_dict=True) if branch else None


def start_datetime():
    """SLHRM Settings biometric_start_date as a datetime (00:00 site time), or None."""
    d = frappe.db.get_single_value(SETTINGS, "biometric_start_date")
    return datetime.combine(getdate(d), datetime.min.time()) if d else None


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

        emp, reason = resolve_employee(uid, device.branch, cache), None
        if not emp and cache.get("by_number"):
            emp, reason = match_by_number(device.name, device.branch, uid, cache)
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
            "match_reason": None if emp else reason,
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


def rematch(device_user_id=None, by_number=None):
    """Match Unmatched device records (optionally one device user id) to employees: (a) explicit
    slhrm_biometric_device_id, else (b) employee number (setting; by_number overrides it). Records left
    Unmatched get match_reason. Returns the number of records matched."""
    filters = {"processing_status": "Unmatched", "device_user_id": ["is", "set"]}
    if device_user_id:
        filters["device_user_id"] = device_user_id
    by_number = number_matching_enabled() if by_number is None else cint(by_number)
    branches = {d.name: d.branch for d in frappe.get_all(DEVICE, fields=["name", "branch"])}
    groups = {}
    for r in frappe.get_all(PUNCH, filters=filters, fields=["name", "device_serial", "device_user_id", "match_reason"]):
        groups.setdefault((r.device_serial, r.device_user_id), []).append(r)
    cache, matched = {}, 0
    for (serial, uid), rows in groups.items():
        emp, reason = resolve_employee(uid, branches.get(serial), cache), None
        if not emp and by_number:
            emp, reason = match_by_number(serial, branches.get(serial), uid, cache)
            if emp:  # the id is now on the Employee; its on_update re-matched these records
                matched += sum(1 for r in rows if frappe.db.get_value(PUNCH, r.name, "employee") == emp.name)
                continue
        for r in rows:
            if emp:
                frappe.db.set_value(PUNCH, r.name, {
                    "employee": emp.name, "employee_name": emp.employee_name, "match_reason": None,
                    "employee_number": emp.employee_number, "processing_status": "Pending",
                })
                matched += 1
            elif cstr(r.match_reason) != cstr(reason):
                frappe.db.set_value(PUNCH, r.name, "match_reason", reason, update_modified=False)
    return matched


def on_employee_update(doc, method=None):
    """doc_events Employee.on_update: a new/changed device user id picks up its Unmatched records
    (explicit id only — never links another employee from inside this save)."""
    if doc.get("slhrm_biometric_device_id") and doc.has_value_changed("slhrm_biometric_device_id"):
        rematch(cstr(doc.slhrm_biometric_device_id).strip(), by_number=0)


def on_employee_validate(doc, method=None):
    """doc_events Employee.validate: device user ids are per branch, so a branch transfer clears the id
    (unless the same save sets a new one). Punches already matched keep their link."""
    if doc.is_new() or not doc.has_value_changed("branch"):
        return
    before = doc.get_doc_before_save()
    old_id = cstr(before.get("slhrm_biometric_device_id") if before else "").strip()
    if old_id and cstr(doc.get("slhrm_biometric_device_id")).strip() == old_id:
        doc.slhrm_biometric_device_id = None
        frappe.msgprint(_("{0} moved from branch {1} to {2}: device user id {3} was cleared (ids are per branch). "
                          "Map the employee again in Unmatched Device Users once they punch on the new branch's device. "
                          "Punches already matched keep their link.").format(
                              doc.employee_name or doc.name, before.branch or "-", doc.branch or "-", old_id),
                        title=_("Device user id cleared"), indicator="orange")


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
    by_number, by_id = {}, {}
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "employee_number", "branch", "slhrm_biometric_device_id"]):
        num = cstr(e.employee_number).strip().lower()
        if num and e.branch:
            by_number.setdefault((e.branch, num), []).append(e)
        did = cstr(e.slhrm_biometric_device_id).strip()
        if did and e.branch:
            by_id.setdefault((e.branch, did), []).append(e)
    idx = (by_number, by_id)
    if cache is not None:
        cache["_number_index"] = idx
    return idx


def device_user_name(serial, device_user_id):
    return frappe.db.get_value(DEVICE_USER, {"device": serial, "device_user_id": device_user_id}, "user_name")


def classify_by_number(device_user_id, branch, device_name, cache=None):
    """Rule (b) without writing. Returns {result: match|ambiguous|conflict|none, employee (row or None),
    sane (name check), detail}. Hit = Active employee, same branch as the device, employee_number ==
    device user id (trimmed, case-insensitive). Conflict: the id is already used by another active
    employee of the same branch, or the hit already has a different device id (explicit mapping wins)."""
    uid = cstr(device_user_id).strip()
    by_number, by_id = _number_index(cache)
    hits = by_number.get((branch, uid.lower()), []) if branch and uid else []
    if not hits:
        return frappe._dict(result="none", employee=None, sane=False, detail="")
    if len(hits) > 1:
        return frappe._dict(result="ambiguous", employee=None, sane=False,
                            detail=", ".join(h.name for h in hits))
    e = hits[0]
    sane = name_sanity(device_name, e.employee_name)
    others = [o for o in by_id.get((branch, uid), []) if o.name != e.name]
    if others:
        return frappe._dict(result="conflict", employee=e, sane=sane,
                            detail=f"id {uid} used by {others[0].name} ({others[0].employee_name})")
    current = cstr(e.slhrm_biometric_device_id).strip()
    if current and current != uid:
        return frappe._dict(result="conflict", employee=e, sane=sane, detail=f"{e.name} already has device id {current}")
    return frappe._dict(result="match", employee=e, sane=sane, detail="")


def outcome(c):
    """What (b) does with a classification: (link employee?, match_reason for the punches)."""
    if c.result == "match":
        return (True, None) if c.sane else (False, "name_mismatch")
    return False, (c.result if c.result in ("ambiguous", "conflict") else None)


def link_by_number(employee, device_user_id, cache=None):
    """Save the device id on the Employee (Version + normal hooks; on_update re-matches its records)."""
    emp = frappe.get_doc("Employee", employee)
    emp.slhrm_biometric_device_id = device_user_id
    emp.flags.ignore_permissions = True
    emp.save(ignore_permissions=True)
    if cache is not None:  # the index / resolve cache now know a different state
        for k in [k for k in cache if isinstance(k, tuple) and k[0] == device_user_id] + ["_number_index"]:
            cache.pop(k, None)
    return frappe._dict(name=emp.name, employee_name=emp.employee_name, employee_number=emp.employee_number,
                        branch=emp.branch)


def match_by_number(serial, branch, device_user_id, cache=None):
    """Rule (b) with writes: (employee row, None) when linked, else (None, match_reason)."""
    c = classify_by_number(device_user_id, branch, device_user_name(serial, device_user_id), cache)
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
    cache, rows, totals, matched = {}, [], {}, {}
    for g in groups:
        d = devices.get(g.device_serial) or frappe._dict()
        dn = device_user_name(g.device_serial, g.device_user_id)
        c = classify_by_number(g.device_user_id, d.branch, dn, cache)
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
            emp, _r = match_by_number(g.device_serial, d.branch, g.device_user_id, cache)
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
    (Employee on_update). Business refusals (employee not in the device's branch, id used by another
    active employee of that branch, inactive employee, no punches) return {"refused": message} — no exception, so the browser shows a message, not a 417.
    If the employee already has a different id, returns {"confirm": ...} unless replace=1.
    Role / permission failures still raise."""
    frappe.only_for(MAP_ROLES)
    device_user_id = cstr(device_user_id).strip()
    device = get_device(device_serial)
    if not device_user_id or not frappe.db.exists(PUNCH, {"device_serial": device.name, "device_user_id": device_user_id}):
        return {"refused": _("No punches of device user {0} on {1}.").format(device_user_id, device.name)}
    emp = frappe.get_doc("Employee", employee)
    emp.check_permission("write")
    if emp.status != "Active":
        return {"refused": _("Employee {0} is not active.").format(emp.name)}
    if not device.branch or emp.branch != device.branch:
        return {"refused": _("{0} is in branch {1}, but device {2} is in branch {3}. Device user ids are per branch: "
                             "change the employee's branch first.").format(emp.name, emp.branch or "-", device.name, device.branch or "-")}
    other = id_holder(device_user_id, device.branch, exclude=emp.name)
    if other:
        return {"refused": _("Device user id {0} is already used by {1} ({2}) in branch {3}.").format(
            device_user_id, other.name, other.employee_name, device.branch)}
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
