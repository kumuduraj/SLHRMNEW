# slhrm/payroll_table.py
"""Payroll Worksheet table layout: ONE definition for the print format (jinja method
`worksheet_table`) and the Excel download. The form JS mirrors it (payroll_worksheet.js,
build_table) — keep them in step; Phase 1.3b verification compares both.

Values come only from the stored HRMS preview breakdown (row.components_json) and the row's
OT/total fields — no pay math here, only layout + column sums.

Layout (left -> right):
  # | Employee | Working Days | Payment Days | LWP |
  EARNINGS: base component first, then the fixed columns (components_json.fixed_columns: Basic Salary,
            Base Allowance, Vehicle Allowance, Other Allowance — shown even when empty), then any other
            earning component in a row. Additional Salary lines go to their OWN component column (v0.1.0).
            The OT component's structure line (Overtime, 0 in the preview — the worksheet adds OT itself) gets
            no column while it is 0 in every row (v0.2.2); a non-zero line (manual Additional Salary) is shown. |
  OT: Hrs, Rate, Amount | GROSS |
  DEDUCTIONS: fixed columns (Death Donation, No Pay, Other Deduction, Salary Advance, Personal Loan,
            Staff Bill, EPF Employee 8%, APIT), then other deduction components (+ Loan if > 0). The APIT cell is the
            row's apit_amount (APIT incl. worksheet OT), not the preview value. |
  TOTAL DED | NET PAY |
  EMPLOYER (statistical components, e.g. employer EPF 12% / ETF 3%; collapsible in the form)
Missing values are None (shown as "-"). Totals sum money and hours only (not rates or day counts).
"""
import json

from frappe.utils import flt

NO_TOTAL = {"ot_rate", "total_working_days", "payment_days", "lwp_days"}  # money + hours only


def _get(row, key):
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def _breakdown(row):
    raw = _get(row, "components_json")
    if not raw:
        return {"earnings": [], "deductions": [], "employer": [], "base_component": None}
    data = json.loads(raw) if isinstance(raw, str) else raw
    data.setdefault("employer", [])
    data.setdefault("fixed_columns", {})
    return data


def build_table(rows):
    rows = list(rows or [])
    parsed = [_breakdown(r) for r in rows]

    apit_comps = list(dict.fromkeys(b.get("apit_component") for b in parsed if b.get("apit_component")))
    ot_comps = {b.get("ot_component") for b in parsed if b.get("ot_component")}
    zero_ot = {c for c in ot_comps
               if not any(flt(line["amount"]) for b in parsed for line in b.get("earnings", []) if line["component"] == c)}

    def union(kind):
        seen, base_first, fixed = [], [], []
        for b in parsed:
            for c in (b.get("fixed_columns") or {}).get(kind, []):
                if c not in fixed:
                    fixed.append(c)
            for line in b.get(kind, []):
                c = line["component"]
                if c not in seen:
                    seen.append(c)
            if kind == "earnings" and b.get("base_component"):
                base_first.append(b["base_component"])
        if kind == "deductions":
            for c in apit_comps:  # APIT may appear only through worksheet OT
                if c not in seen and c not in fixed and any(flt(_get(r, "apit_amount")) for r in rows):
                    seen.append(c)
        bases = [c for c in dict.fromkeys(base_first) if c in seen or c in fixed]
        head = bases + [c for c in fixed if c not in bases]
        cols = head + [c for c in seen if c not in head]
        return [c for c in cols if not (kind == "earnings" and c in zero_ot)]

    earn_comps = union("earnings")
    ded_comps = union("deductions")
    emp_comps = []
    for b in parsed:
        for line in b.get("employer", []):
            if line["component"] not in emp_comps:
                emp_comps.append(line["component"])
    has_loan = any(flt(_get(r, "loan_deduction")) > 0 for r in rows)

    tip = lambda c: f"{c} — Salary Structure / Additional Salary"
    groups = [
        {"key": "info", "label": "", "columns": [
            {"key": "idx", "label": "#", "type": "int"},
            {"key": "employee_name", "label": "Employee", "type": "text"},
            {"key": "total_working_days", "label": "Working Days", "type": "float"},
            {"key": "payment_days", "label": "Payment Days", "type": "float"},
            {"key": "lwp_days", "label": "LWP", "type": "float"},
        ]},
        {"key": "earnings", "label": "EARNINGS",
         "columns": [{"key": f"E::{c}", "label": c, "type": "currency", "tooltip": tip(c)} for c in earn_comps]},
        {"key": "ot", "label": "OT", "columns": [
            {"key": "ot_hours", "label": "Hrs", "type": "float"},
            {"key": "ot_rate", "label": "Rate", "type": "currency"},
            {"key": "ot_amount", "label": "Amount", "type": "currency"}]},
        {"key": "gross", "label": "", "columns": [{"key": "total_earning", "label": "GROSS", "type": "currency"}]},
        {"key": "deductions", "label": "DEDUCTIONS",
         "columns": [{"key": f"D::{c}", "label": c, "type": "currency", "tooltip": tip(c)} for c in ded_comps]
         + ([{"key": "loan_deduction", "label": "Loan", "type": "currency"}] if has_loan else [])},
        {"key": "total_ded", "label": "", "columns": [{"key": "total_deduction", "label": "TOTAL DED", "type": "currency"}]},
        {"key": "net", "label": "", "columns": [{"key": "net_pay", "label": "NET PAY", "type": "currency"}]},
        {"key": "employer", "label": "EMPLOYER", "collapsible": 1,
         "columns": [{"key": f"ER::{c}", "label": c, "type": "currency",
                      "tooltip": f"{c} — employer contribution (statistical, not in net pay)"} for c in emp_comps]},
    ]
    groups = [g for g in groups if g["columns"]]
    columns = [dict(c, group=g["key"]) for g in groups for c in g["columns"]]

    out_rows = []
    for i, (r, b) in enumerate(zip(rows, parsed), 1):
        cells = {
            "idx": i, "employee_name": _get(r, "employee_name") or _get(r, "employee"),
            "employee": _get(r, "employee"), "row_error": _get(r, "row_error") or "",
        }
        for key in ("total_working_days", "payment_days", "lwp_days", "ot_hours", "ot_rate", "ot_amount",
                    "total_earning", "total_deduction", "net_pay", "loan_deduction"):
            cells[key] = flt(_get(r, key))
        for prefix, kind in (("E", "earnings"), ("D", "deductions")):
            for line in b.get(kind, []):
                key = f"{prefix}::{line['component']}"
                cells[key] = flt(cells.get(key) or 0) + flt(line["amount"])
        apit_amount = _get(r, "apit_amount")
        if b.get("apit_component") and apit_amount is not None and (flt(apit_amount) or f"D::{b['apit_component']}" in cells):
            cells[f"D::{b['apit_component']}"] = flt(apit_amount)  # APIT incl. worksheet OT
        for line in b.get("employer", []):
            key = f"ER::{line['component']}"
            cells[key] = flt(cells.get(key) or 0) + flt(line["amount"])
        out_rows.append(cells)

    totals = {}
    for c in columns:
        if c["type"] in ("currency", "float") and c["key"] not in NO_TOTAL:
            totals[c["key"]] = flt(sum(flt(r.get(c["key"]) or 0) for r in out_rows), 2)
    return {"groups": groups, "columns": columns, "rows": out_rows, "totals": totals}


def worksheet_table(doc):
    """Jinja method for the "Payroll Worksheet" print format."""
    return build_table(doc.get("employees") or [])


def format_cell(value, column):
    """Excel / print text for one cell ("-" when missing)."""
    if value is None or value == "":
        return "-" if column["type"] in ("currency", "float") else ""
    return value


def sheet_rows(title, table):
    """List of rows for Excel: title, group header, column labels, data rows, totals."""
    cols = table["columns"]
    group_labels = {g["key"]: g["label"] for g in table["groups"]}
    group_row, last = [], None
    for c in cols:
        group_row.append(group_labels.get(c["group"], "") if c["group"] != last else "")
        last = c["group"]
    out = [[title], group_row, [c["label"] for c in cols]]
    for r in table["rows"]:
        out.append([format_cell(r.get(c["key"]), c) for c in cols])
    totals = []
    for c in cols:
        if c["key"] == "employee_name":
            totals.append("TOTAL")
        else:
            totals.append(table["totals"].get(c["key"], ""))
    out.append(totals)
    return out
