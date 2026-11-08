# slhrm/salary_setup.py
"""Standard salary components + "Standard Staff Structure" for Gills Hospitality pvt ltd.

    bench --site hrm.gillsinternational.com execute slhrm.salary_setup.apply

Idempotent: existing records (same name) are NOT modified — differences from the definition
below are reported instead. Uses the standard HRMS doctypes through the API (no core changes).
"Standard Salary Structure - GHPL" is left untouched (printed for reference).

EPF/ETF are percentages of the SSA `base`. With Employee Salary Packages, base = sum of the
package's earning overrides (intended), so EPF 8% = 8% of total package earnings.
Formula components have depends_on_payment_days = 0 (HRMS rejects formula + payment-days).
"""
import json

import frappe
from frappe.utils import cint, flt

COMPANY = "Gills Hospitality pvt ltd"
STRUCTURE = "Standard Staff Structure"
LEGACY_STRUCTURE = "Standard Salary Structure - GHPL"

COMPONENTS = [
    # name, abbr, type, depends_on_payment_days, statistical (statistical_component + do_not_include_in_total)
    ("Basic Salary", "BS", "Earning", 1, 0),
    ("Base Allowance", "BA", "Earning", 1, 0),
    ("Vehicle Allowance", "VA", "Earning", 0, 0),
    ("EPF Employee 8%", "EPF8", "Deduction", 0, 0),
    ("EPF Employer 12%", "EPF12", "Deduction", 0, 1),
    ("ETF Employer 3%", "ETF3", "Deduction", 0, 1),
]
EARNINGS = [("Basic Salary", 0), ("Base Allowance", 0), ("Vehicle Allowance", 0)]
DEDUCTIONS = [("EPF Employee 8%", "base * 0.08", 0), ("EPF Employer 12%", "base * 0.12", 1),
              ("ETF Employer 3%", "base * 0.03", 1)]


def _component_spec(name, abbr, typ, dpd, stat):
    return {"salary_component": name, "salary_component_abbr": abbr, "type": typ,
            "depends_on_payment_days": dpd, "statistical_component": stat, "do_not_include_in_total": stat}


def apply():
    frappe.set_user("Administrator")
    report = {"created": [], "existing_unchanged": [], "existing_with_diffs": {}, "refused": {}}

    for name, abbr, typ, dpd, stat in COMPONENTS:
        spec = _component_spec(name, abbr, typ, dpd, stat)
        if frappe.db.exists("Salary Component", name):
            cur = frappe.db.get_value("Salary Component", name, list(spec), as_dict=True)
            diffs = {k: {"existing": cur[k], "expected": v} for k, v in spec.items()
                     if str(cur[k] if cur[k] is not None else "") != str(v)}
            (report["existing_with_diffs"].__setitem__(name, diffs) if diffs
             else report["existing_unchanged"].append(name))
            continue
        clash = frappe.db.get_value("Salary Component", {"salary_component_abbr": abbr}, "name")
        if clash:
            report["refused"][name] = f"abbreviation {abbr} already used by {clash}"
            continue
        frappe.get_doc({"doctype": "Salary Component", **spec}).insert(ignore_permissions=True)
        report["created"].append(f"Salary Component: {name} ({abbr})")
    frappe.db.commit()

    expected_rows = {
        "earnings": [{"salary_component": c, "amount": 0, "amount_based_on_formula": 0, "formula": ""} for c, _ in EARNINGS],
        "deductions": [{"salary_component": c, "amount_based_on_formula": 1, "formula": f,
                        "statistical_component": s, "do_not_include_in_total": s, "depends_on_payment_days": 0}
                       for c, f, s in DEDUCTIONS],
    }
    if frappe.db.exists("Salary Structure", STRUCTURE):
        ss = frappe.get_doc("Salary Structure", STRUCTURE)
        diffs = {}
        for table, rows in expected_rows.items():
            have = {r.salary_component: r for r in ss.get(table)}
            for row in rows:
                h = have.get(row["salary_component"])
                if not h:
                    diffs[f"{table}:{row['salary_component']}"] = "missing"
                    continue
                d = {k: {"existing": h.get(k), "expected": v} for k, v in row.items()
                     if k != "salary_component" and str(h.get(k) if h.get(k) is not None else "") != str(v)
                     and not (k == "amount" and flt(h.get(k)) == flt(v))}
                if d:
                    diffs[f"{table}:{row['salary_component']}"] = d
            extra = set(have) - {r["salary_component"] for r in rows}
            if extra:
                diffs[f"{table}:extra"] = sorted(extra)
        if ss.docstatus != 1:
            diffs["docstatus"] = {"existing": ss.docstatus, "expected": 1}
        (report["existing_with_diffs"].__setitem__(STRUCTURE, diffs) if diffs
         else report["existing_unchanged"].append(STRUCTURE))
    elif report["refused"]:
        report["refused"][STRUCTURE] = "not created: some components were refused"
    else:
        ss = frappe.get_doc({
            "doctype": "Salary Structure", "__newname": STRUCTURE, "company": COMPANY,
            "currency": frappe.get_cached_value("Company", COMPANY, "default_currency"),
            "payroll_frequency": "Monthly", "is_active": "Yes", **expected_rows,
        })
        ss.insert(ignore_permissions=True)
        ss.submit()
        frappe.db.commit()
        report["created"].append(f"Salary Structure: {STRUCTURE} (submitted)")

    legacy = frappe.get_doc("Salary Structure", LEGACY_STRUCTURE) if frappe.db.exists("Salary Structure", LEGACY_STRUCTURE) else None
    report["untouched_legacy_structure"] = legacy and {
        "name": legacy.name, "docstatus": legacy.docstatus, "is_active": legacy.is_active, "modified": str(legacy.modified),
        "earnings": [(r.salary_component, flt(r.amount), r.formula or "") for r in legacy.earnings],
        "deductions": [(r.salary_component, flt(r.amount), r.formula or "") for r in legacy.deductions],
        "ssa_count": frappe.db.count("Salary Structure Assignment", {"salary_structure": legacy.name, "docstatus": 1}),
    }
    print(json.dumps(report, indent=1, default=str))
    return {"created": len(report["created"]), "diffs": len(report["existing_with_diffs"]), "refused": len(report["refused"])}


def describe():
    """Print the Standard Staff Structure as stored (read-only)."""
    ss = frappe.get_doc("Salary Structure", STRUCTURE)
    for table in ("earnings", "deductions"):
        for r in ss.get(table):
            print(table, r.salary_component, r.abbr, flt(r.amount), r.formula or "", "stat" if cint(r.statistical_component) else "")
