# slhrm/payroll_table.py
"""Payroll Worksheet table layout: ONE definition for the print format (jinja method
`worksheet_table`) and the Excel download. The form JS mirrors it (payroll_worksheet.js,
build_table) — keep them in step; Phase 1.3b verification compares both.

Values come only from the stored HRMS preview breakdown (row.components_json) and the row's
OT/total fields — no pay math here, only layout + column sums.

Layout (left -> right):
  # | Employee | Working Days | Payment Days | LWP |
  EARNINGS: one column per earning component in any row (base component first, then structure
            order) + "Additional" (Additional Salary earnings) |
  NORMAL OT: Hrs, Rate, Amount | DOUBLE OT: Hrs, Rate, Amount | GROSS |
  DEDUCTIONS: one column per deduction component in any row (+ "Additional", + Loan if > 0) |
  TOTAL DED | NET PAY |
  EMPLOYER (statistical components, e.g. employer EPF 12% / ETF 3%; collapsible in the form)
Missing values are None (shown as "-"). Totals sum every value column except rates.
"""
import json

from frappe.utils import flt

ADDITIONAL = "__additional__"
NO_TOTAL = {"normal_ot_rate", "double_ot_rate"}


def _get(row, key):
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def _breakdown(row):
    raw = _get(row, "components_json")
    if not raw:
        return {"earnings": [], "deductions": [], "employer": [], "base_component": None}
    data = json.loads(raw) if isinstance(raw, str) else raw
    data.setdefault("employer", [])
    return data


def build_table(rows):
    rows = list(rows or [])
    parsed = [_breakdown(r) for r in rows]

    def union(kind):
        seen, base_first = [], []
        for b in parsed:
            for line in b.get(kind, []):
                if line.get("additional_salary"):
                    continue
                c = line["component"]
                if c not in seen:
                    seen.append(c)
            if kind == "earnings" and b.get("base_component"):
                base_first.append(b["base_component"])
        bases = [c for c in dict.fromkeys(base_first) if c in seen]
        return bases + [c for c in seen if c not in bases]

    earn_comps = union("earnings")
    ded_comps = union("deductions")
    emp_comps = []
    for b in parsed:
        for line in b.get("employer", []):
            if line["component"] not in emp_comps:
                emp_comps.append(line["component"])
    has_add_earn = any(line.get("additional_salary") for b in parsed for line in b.get("earnings", []))
    has_add_ded = any(line.get("additional_salary") for b in parsed for line in b.get("deductions", []))
    has_loan = any(flt(_get(r, "loan_deduction")) > 0 for r in rows)

    tip = lambda c: f"{c} — from Salary Structure"
    groups = [
        {"key": "info", "label": "", "columns": [
            {"key": "idx", "label": "#", "type": "int"},
            {"key": "employee_name", "label": "Employee", "type": "text"},
            {"key": "total_working_days", "label": "Working Days", "type": "float"},
            {"key": "payment_days", "label": "Payment Days", "type": "float"},
            {"key": "lwp_days", "label": "LWP", "type": "float"},
        ]},
        {"key": "earnings", "label": "EARNINGS",
         "columns": [{"key": f"E::{c}", "label": c, "type": "currency", "tooltip": tip(c)} for c in earn_comps]
         + ([{"key": f"E::{ADDITIONAL}", "label": "Additional", "type": "currency",
              "tooltip": "Additional Salary earnings (submitted, this period)"}] if has_add_earn else [])},
        {"key": "normal_ot", "label": "NORMAL OT", "columns": [
            {"key": "normal_ot_hours", "label": "Hrs", "type": "float"},
            {"key": "normal_ot_rate", "label": "Rate", "type": "currency"},
            {"key": "normal_ot_amount", "label": "Amount", "type": "currency"}]},
        {"key": "double_ot", "label": "DOUBLE OT", "columns": [
            {"key": "double_ot_hours", "label": "Hrs", "type": "float"},
            {"key": "double_ot_rate", "label": "Rate", "type": "currency"},
            {"key": "double_ot_amount", "label": "Amount", "type": "currency"}]},
        {"key": "gross", "label": "", "columns": [{"key": "total_earning", "label": "GROSS", "type": "currency"}]},
        {"key": "deductions", "label": "DEDUCTIONS",
         "columns": [{"key": f"D::{c}", "label": c, "type": "currency", "tooltip": tip(c)} for c in ded_comps]
         + ([{"key": f"D::{ADDITIONAL}", "label": "Additional", "type": "currency",
              "tooltip": "Additional Salary deductions (submitted, this period)"}] if has_add_ded else [])
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
        for key in ("total_working_days", "payment_days", "lwp_days", "normal_ot_hours", "normal_ot_rate",
                    "normal_ot_amount", "double_ot_hours", "double_ot_rate", "double_ot_amount", "total_earning",
                    "total_deduction", "net_pay", "loan_deduction"):
            cells[key] = flt(_get(r, key))
        for prefix, kind in (("E", "earnings"), ("D", "deductions")):
            for line in b.get(kind, []):
                key = f"{prefix}::{ADDITIONAL}" if line.get("additional_salary") else f"{prefix}::{line['component']}"
                cells[key] = flt(cells.get(key) or 0) + flt(line["amount"])
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
