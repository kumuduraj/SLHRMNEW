# slhrm/attendance_calendar.py
"""Attendance Calendar (v0.4.4): month completion per branch + employee register. Read-only — uses existing data only
(Attendance Marker + rows, Biometric Punch Log, Holiday List Assignment); nothing is stored.

Day colour (branch + date):
  green  — submitted marker, 0 flagged rows (Missing punch / Long session / Two sessions, as in the Punch Overview) and
           0 Unmatched punches of the devices serving the branch on that date;
  orange — a draft marker exists (and no submitted one), or the submitted one has flagged rows / unmatched punches;
  red    — working day (up to today) without a marker;
  grey   — holiday for every active employee of the branch (Holiday List Assignment), or a future date.
Register: active employees of the branch × days, from SUBMITTED markers only: P / A / NP / L / SL, ⚠ = flagged row,
blank = no submitted marker row for that day. Totals P (Present + Short Leave), A, NP, OT hrs, Short hrs.
"""
import calendar
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

CODES = {"Present": "P", "Absent": "A", "No Pay": "NP", "Leave": "L", "Short Leave": "SL"}
FLAG_SET = ("Missing punch", "Long session", "Two sessions")
READ_ROLES = ("HR Manager", "HR User", "Attendance Supervisor", "System Manager")


def _check(branch):
    from slhrm.api import _check_branch_allowed

    frappe.only_for(READ_ROLES)
    frappe.has_permission("Attendance Marker", "read", throw=True)
    if not branch or not frappe.db.exists("Branch", branch):
        frappe.throw(_("Select a Branch."))
    _check_branch_allowed(branch)


def _month(month):
    """'YYYY-MM' → (first day, last day)."""
    try:
        y, m = [int(x) for x in str(month).split("-")[:2]]
        first = date(y, m, 1)
    except (ValueError, TypeError):
        frappe.throw(_("Month must be YYYY-MM."))
    return first, date(y, m, calendar.monthrange(y, m)[1])


def _holidays(employees, first, last):
    """{employee: set(holiday dates)} from each employee's Holiday List Assignment (as on the month's first and last day)."""
    from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

    lists, out = {}, {}
    for e in employees:
        names = {get_holiday_list_for_employee(e, raise_exception=False, as_on=d) for d in (first, last)} - {None, ""}
        days = set()
        for n in names:
            if n not in lists:
                lists[n] = {getdate(h) for h in frappe.get_all("Holiday", filters={"parent": n, "holiday_date": ["between", [first, last]]},
                                                                pluck="holiday_date")}
            days |= lists[n]
        out[e] = days
    return out


def build(branch, month):
    """The whole page payload: {days: [...], header, register} (see module docstring)."""
    from slhrm.biometric import served_branches
    from slhrm.punch_overview import build as overview

    first, last = _month(month)
    today = getdate(nowdate())
    emps = frappe.get_all("Employee", filters={"branch": branch, "status": "Active"},
                          fields=["name", "employee_name", "employee_number"], order_by="employee_name asc")
    hol = _holidays([e.name for e in emps], first, last)
    branch_holidays = set.intersection(*hol.values()) if hol else set()
    markers = frappe.get_all("Attendance Marker", filters={"branch": branch, "date": ["between", [first, last]], "docstatus": ["<", 2]},
                             fields=["name", "date", "docstatus"], order_by="docstatus desc, modified desc")
    by_date = {}
    for m in markers:
        by_date.setdefault(getdate(m.date), []).append(m)
    serving = [d.name for d in frappe.get_all("Biometric Device", fields=["name", "branch"]) if branch in served_branches(d.name, d.branch)]
    unmatched = {}
    if serving:
        for d, n in frappe.db.sql("""select date(punch_time), count(*) from `tabBiometric Punch Log` where processing_status = 'Unmatched'
                                     and device_serial in %s and punch_time between %s and %s group by 1""",
                                  (tuple(serving), first, last + timedelta(days=1))):
            unmatched[getdate(d)] = cint(n)

    days, register = [], {e.name: {} for e in emps}
    d = first
    while d <= last:
        ms = by_date.get(d, [])
        sub = next((m for m in ms if m.docstatus == 1), None)
        draft = next((m for m in ms if m.docstatus == 0), None)
        mk = sub or draft
        info = {"date": str(d), "day": d.day, "weekday": d.weekday(), "marker": mk.name if mk else None,
                "marker_status": ("Submitted" if sub else "Draft") if mk else None, "draft": draft.name if draft else None,
                "P": 0, "A": 0, "NP": 0, "L": 0, "flagged": 0, "unmatched": unmatched.get(d, 0),
                "holiday": d in branch_holidays, "future": d > today}
        if mk:
            rows = frappe.get_all("Attendance Marker Detail", filters={"parent": mk.name, "parenttype": "Attendance Marker"},
                                  fields=["name", "idx", "employee", "employee_name", "shift", "attendance_status", "in_time", "out_time",
                                          "out_next_day", "worked_hours", "missing_punch", "long_session", "no_shift", "ot_hours",
                                          "short_hours"])
            flags = {r["employee"]: [f for f in r["flags"] if f in FLAG_SET] for r in overview(str(d), branch, rows)["rows"]}
            for r in rows:
                code = CODES.get(r.attendance_status)
                if code in ("P", "SL"):
                    info["P"] += 1
                elif code in info:
                    info[code] += 1
                if flags.get(r.employee):
                    info["flagged"] += 1
                if sub and r.employee in register:
                    register[r.employee][str(d)] = {"code": code or "", "flags": flags.get(r.employee) or [],
                                                    "ot": flt(r.ot_hours), "short": flt(r.short_hours)}
        if sub:
            info["color"] = "green" if not info["flagged"] and not info["unmatched"] else "orange"
        elif draft:
            info["color"] = "orange"
        elif info["holiday"] or info["future"]:
            info["color"] = "grey"
        else:
            info["color"] = "red"
        info["reason"] = {"green": "", "grey": "", "red": _("no marker"),
                          "orange": _("draft") if not sub else ", ".join(
                              x for x in (_("{0} flagged").format(info["flagged"]) if info["flagged"] else "",
                                          _("{0} unmatched punches").format(info["unmatched"]) if info["unmatched"] else "") if x)}[info["color"]]
        days.append(info)
        d += timedelta(days=1)

    working = [x for x in days if not x["holiday"] and not x["future"]]
    completed = [x for x in working if x["color"] == "green"]
    reg_rows = []
    for e in emps:
        cells, t = {}, {"P": 0, "A": 0, "NP": 0, "ot": 0.0, "short": 0.0, "pending": 0, "flagged": 0}
        for x in days:
            c = register[e.name].get(x["date"])
            own_holiday = getdate(x["date"]) in hol.get(e.name, set())
            if c:
                text = "⚠" if c["flags"] else c["code"]
                cells[x["date"]] = {"text": text, "code": c["code"], "flags": c["flags"]}
                if c["code"] in ("P", "SL"):
                    t["P"] += 1
                elif c["code"] in ("A", "NP"):
                    t[c["code"]] += 1
                t["ot"] += c["ot"]
                t["short"] += c["short"]
                t["flagged"] += 1 if c["flags"] else 0
            else:
                cells[x["date"]] = {"text": "", "code": "", "flags": [], "holiday": own_holiday}
                if not own_holiday and not x["future"]:
                    t["pending"] += 1
        t["ot"], t["short"] = round(t["ot"], 2), round(t["short"], 2)
        reg_rows.append({"employee": e.name, "employee_name": e.employee_name, "employee_number": e.employee_number or "",
                         "cells": cells, "totals": t, "attention": bool(t["pending"] or t["flagged"])})
    return {"branch": branch, "month": f"{first:%Y-%m}", "label": f"{first:%B %Y}", "first": str(first), "last": str(last),
            "today": str(today), "days": days,
            "header": {"completed": len(completed), "working": len(working),
                       "pending": [{"date": x["date"], "color": x["color"], "reason": x["reason"], "marker": x["marker"]}
                                   for x in working if x["color"] != "green"]},
            "register": reg_rows}


@frappe.whitelist()
def get_calendar(branch, month):
    _check(branch)
    return build(branch, month)


@frappe.whitelist()
def export_register(branch, month, only_attention=0):
    """Excel of the employee register (same cells + totals as the page)."""
    from frappe.utils.xlsxutils import make_xlsx

    _check(branch)
    data = build(branch, month)
    days = data["days"]
    head = ["Employee", "Emp No."] + [f"{x['day']:02d}" for x in days] + ["P", "A", "NP", "OT hrs", "Short hrs"]
    rows = [[f"Attendance register — {branch} — {data['label']}"],
            [f"Completed {data['header']['completed']} / {data['header']['working']} working days"], head]
    for r in data["register"]:
        if cint(only_attention) and not r["attention"]:
            continue
        rows.append([r["employee_name"], r["employee_number"]] + [r["cells"][x["date"]]["text"] for x in days]
                    + [r["totals"][k] for k in ("P", "A", "NP", "ot", "short")])
    xlsx = make_xlsx(rows, "Register")
    frappe.response["filename"] = f"attendance_register_{branch}_{data['month']}.xlsx".replace(" ", "_")
    frappe.response["filecontent"] = xlsx.getvalue()
    frappe.response["type"] = "binary"
