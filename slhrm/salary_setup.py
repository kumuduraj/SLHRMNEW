# slhrm/salary_setup.py
"""Final salary components + "Standard Staff Structure" for Gills Hospitality pvt ltd (v0.2.0).

    bench --site hrm.gillsinternational.com execute slhrm.salary_setup.apply
    bench --site hrm.gillsinternational.com execute slhrm.salary_setup.apply --kwargs '{"dry_run": 1}'

Idempotent. Uses the standard HRMS doctypes through the API (no core changes).
- Components (COMPONENTS) are created when missing; existing ones are reused and only these
  properties are set on them: depends_on_payment_days (DPD_SYNC: Basic Salary / Base Allowance -> 0 because
  No Pay is entered manually as Additional Salary) and SLHRM's own fields (EPF_FLAGS, REDUCES).
- v0.2.0 ONE OT: "Normal OT" is renamed to "Overtime" (abbr OT) when "Overtime" does not exist yet;
  "Double OT" is deleted when nothing references it, else disabled and reported (_single_ot).
- SLHRM Settings: OT component (Overtime), APIT component, APIT slabs (loaded only when no slab
  with that effective date exists).
- Structure: if "Standard Staff Structure" differs from STRUCTURE_ROWS and no Salary Structure Assignment
  (draft or submitted) uses it -> cancel + amend (Frappe names the amendment "<name>-1", "-2", ...);
  otherwise a new "<name> v2" is created and reported.

EPF/ETF and APIT are computed by slhrm.statutory (apply_epf / apply_apit): structure rows of rated / APIT
components only make the rows exist. SSA.base = SUM of the package's earning overrides (intended).
"""
import json

import frappe
from frappe.utils import cint, flt

COMPANY = "Gills Hospitality pvt ltd"
STRUCTURE = "Standard Staff Structure"
LEGACY_STRUCTURE = "Standard Salary Structure - GHPL"

COMPONENTS = [
    # name, abbr, type, depends_on_payment_days, statistical (statistical_component + do_not_include_in_total)
    ("Basic Salary", "BS", "Earning", 0, 0),
    ("Base Allowance", "BA", "Earning", 0, 0),
    ("Vehicle Allowance", "VA", "Earning", 0, 0),
    ("Overtime", "OT", "Earning", 0, 0),
    ("Other Allowance", "OA", "Earning", 0, 0),
    ("Death Donation", "DD", "Deduction", 0, 0),
    ("No Pay", "NP", "Deduction", 0, 0),
    ("Other Deduction", "ODED", "Deduction", 0, 0),
    ("Salary Advance", "SADV", "Deduction", 0, 0),
    ("Personal Loan", "PLN", "Deduction", 0, 0),
    ("Staff Bill", "SB", "Deduction", 0, 0),  # v0.2.0: monthly via Additional Salary; not EPF base, not APIT-deductible
    ("EPF Employee 8%", "EPF8", "Deduction", 0, 0),
    ("APIT", "APIT", "Deduction", 0, 0),
    ("EPF Employer 12%", "EPF12", "Deduction", 0, 1),
    ("ETF Employer 3%", "ETF3", "Deduction", 0, 1),
]
DPD_SYNC = {"Basic Salary": 0, "Base Allowance": 0}  # existing components: approved property change
PACKAGE_EARNINGS = ("Basic Salary", "Base Allowance", "Vehicle Allowance")  # amount 0 in the structure

# component -> {slhrm_epf_applicable, slhrm_epf_rate}; applied idempotently, also on existing records
EPF_FLAGS = {
    "Basic Salary": {"slhrm_epf_applicable": 1, "slhrm_epf_rate": 0},
    "Base Allowance": {"slhrm_epf_applicable": 1, "slhrm_epf_rate": 0},
    "Vehicle Allowance": {"slhrm_epf_applicable": 1, "slhrm_epf_rate": 0},
    "Overtime": {"slhrm_epf_applicable": 0, "slhrm_epf_rate": 0},
    "Other Allowance": {"slhrm_epf_applicable": 0, "slhrm_epf_rate": 0},
    "EPF Employee 8%": {"slhrm_epf_applicable": 0, "slhrm_epf_rate": 8},
    "EPF Employer 12%": {"slhrm_epf_applicable": 0, "slhrm_epf_rate": 12},
    "ETF Employer 3%": {"slhrm_epf_applicable": 0, "slhrm_epf_rate": 3},
}
REDUCES = {"No Pay": {"slhrm_reduces_epf_base": 1}}  # No Pay lowers the EPF base and the APIT taxable amount

SETTINGS_COMPONENTS = {"ot_component": "Overtime", "apit_component": "APIT"}
OT_RENAME = ("Normal OT", "Overtime", "OT")  # old name -> new name, new abbr
OT_RETIRE = "Double OT"
APIT_EFFECTIVE_FROM = "2025-04-01"
APIT_SLABS = [  # monthly = annual table / 12 (exact thresholds; Raj 2026-11-10): from, to (0 = no limit), rate %
    (0, 150000, 0), (150000, 233333.33, 6), (233333.33, 275000, 18), (275000, 316666.67, 24), (316666.67, 358333.33, 30),
    (358333.33, 0, 36),
]

STRUCTURE_ROWS = {
    "earnings": [{"salary_component": c, "amount": 0, "amount_based_on_formula": 0, "formula": ""} for c in PACKAGE_EARNINGS],
    "deductions": [
        {"salary_component": "Death Donation", "amount": 200, "amount_based_on_formula": 0, "formula": "",
         "statistical_component": 0, "do_not_include_in_total": 0, "depends_on_payment_days": 0},
        {"salary_component": "EPF Employee 8%", "amount_based_on_formula": 1, "formula": "base * 0.08",
         "statistical_component": 0, "do_not_include_in_total": 0, "depends_on_payment_days": 0},
        {"salary_component": "APIT", "amount": 0, "amount_based_on_formula": 0, "formula": "",
         "statistical_component": 0, "do_not_include_in_total": 0, "depends_on_payment_days": 0},
        {"salary_component": "EPF Employer 12%", "amount_based_on_formula": 1, "formula": "base * 0.12",
         "statistical_component": 1, "do_not_include_in_total": 1, "depends_on_payment_days": 0},
        {"salary_component": "ETF Employer 3%", "amount_based_on_formula": 1, "formula": "base * 0.03",
         "statistical_component": 1, "do_not_include_in_total": 1, "depends_on_payment_days": 0},
    ],
}

# Payroll Worksheet: columns shown even when empty (slhrm.payroll_pay.fixed_columns; order = left to right)
WORKSHEET_FIXED_EARNINGS = ["Basic Salary", "Base Allowance", "Vehicle Allowance", "Other Allowance"]
WORKSHEET_FIXED_DEDUCTIONS = ["Death Donation", "No Pay", "Other Deduction", "Salary Advance", "Personal Loan",
                              "Staff Bill", "EPF Employee 8%", "APIT"]


def _component_spec(name, abbr, typ, dpd, stat):
    return {"salary_component": name, "salary_component_abbr": abbr, "type": typ,
            "depends_on_payment_days": dpd, "statistical_component": stat, "do_not_include_in_total": stat,
            # package earnings must stay on the slip at amount 0 so the overrides can fill them in
            "remove_if_zero_valued": 0 if name in PACKAGE_EARNINGS else 1}


def _norm(v):
    return "" if v is None else str(v)


def apply(dry_run=0):
    frappe.set_user("Administrator")
    dry = cint(dry_run)
    report = {"dry_run": bool(dry), "created": [], "reused": [], "changed": {}, "refused": {}, "structure": {}}
    report["single_ot"] = _single_ot(dry)

    for name, abbr, typ, dpd, stat in COMPONENTS:
        spec = _component_spec(name, abbr, typ, dpd, stat)
        if frappe.db.exists("Salary Component", name):
            cur = frappe.db.get_value("Salary Component", name, ["type", "salary_component_abbr", "depends_on_payment_days"], as_dict=True)
            report["reused"].append(f"{name} ({cur.salary_component_abbr}, {cur.type})")
            if name in DPD_SYNC and cint(cur.depends_on_payment_days) != DPD_SYNC[name]:
                report["changed"].setdefault(name, {})["depends_on_payment_days"] = [cur.depends_on_payment_days, DPD_SYNC[name]]
                if not dry:
                    frappe.db.set_value("Salary Component", name, "depends_on_payment_days", DPD_SYNC[name])
            continue
        if dry and name == OT_RENAME[1] and frappe.db.exists("Salary Component", OT_RENAME[0]):
            report["reused"].append(f"{name} (= renamed {OT_RENAME[0]})")
            continue
        clash = frappe.db.get_value("Salary Component", {"salary_component_abbr": abbr}, "name")
        if clash:
            report["refused"][name] = f"abbreviation {abbr} already used by {clash}"
            continue
        report["created"].append(f"Salary Component: {name} ({abbr}, {typ}{', statistical' if stat else ''})")
        if not dry:
            frappe.get_doc({"doctype": "Salary Component", **spec}).insert(ignore_permissions=True)
    if not dry:
        frappe.db.commit()

    report["epf_flags"] = sync_epf_flags(EPF_FLAGS, dry_run=dry)
    report["reduces_flags"] = sync_epf_flags(REDUCES, dry_run=dry)
    report["settings"] = _apply_settings(dry)
    report["structure"] = _apply_structure(dry)

    legacy = frappe.get_doc("Salary Structure", LEGACY_STRUCTURE) if frappe.db.exists("Salary Structure", LEGACY_STRUCTURE) else None
    report["untouched_legacy_structure"] = legacy and {"name": legacy.name, "docstatus": legacy.docstatus,
                                                      "ssa_count": frappe.db.count("Salary Structure Assignment", {"salary_structure": legacy.name, "docstatus": 1})}
    print(json.dumps(report, indent=1, default=str))
    return {"created": len(report["created"]), "changed": len(report["changed"]), "refused": len(report["refused"]),
            "structure": report["structure"].get("action")}


def component_references(name):
    """Where a Salary Component is used (counts); empty dict = unused."""
    refs = {
        "Salary Detail": frappe.db.count("Salary Detail", {"salary_component": name}),
        "Additional Salary": frappe.db.count("Additional Salary", {"salary_component": name}),
        "Employee Salary Package Detail": frappe.db.count("Employee Salary Package Detail", {"salary_component": name}),
        "SSA package snapshot": frappe.db.count("Salary Structure Assignment", {"slhrm_package_components": ["like", f'%"{name}"%']}),
        "Payroll Settings / formulas": frappe.db.count("Salary Detail", {"formula": ["like", f"%{name}%"]}),
    }
    return {k: v for k, v in refs.items() if v}


def _single_ot(dry):
    """Rename Normal OT -> Overtime (abbr OT); delete Double OT when unused, else disable + report."""
    old, new, abbr = OT_RENAME
    out = {}
    if frappe.db.exists("Salary Component", old) and not frappe.db.exists("Salary Component", new):
        clash = frappe.db.get_value("Salary Component", {"salary_component_abbr": abbr, "name": ["!=", old]}, "name")
        out["rename"] = f"{old} -> {new}" + (f" (abbr kept: {abbr} used by {clash})" if clash else f", abbr -> {abbr}")
        if not dry:
            frappe.rename_doc("Salary Component", old, new, force=True)
            frappe.db.set_value("Salary Component", new, "salary_component", new)
            if not clash:
                frappe.db.set_value("Salary Component", new, "salary_component_abbr", abbr)
            frappe.db.commit()
    elif frappe.db.exists("Salary Component", old):
        out["rename"] = f"both {old} and {new} exist — NOT renamed ({old} refs: {component_references(old)})"
    if frappe.db.exists("Salary Component", OT_RETIRE):
        refs = component_references(OT_RETIRE)
        if refs:
            out["retire"] = f"{OT_RETIRE} is used {refs} — disabled, not deleted"
            if not dry:
                frappe.db.set_value("Salary Component", OT_RETIRE, "disabled", 1)
        else:
            out["retire"] = f"{OT_RETIRE} unused — deleted"
            if not dry:
                frappe.delete_doc("Salary Component", OT_RETIRE, ignore_permissions=True)
        if not dry:
            frappe.db.commit()
    return out or "unchanged"


def _apply_settings(dry):
    s = frappe.get_single("SLHRM Settings")
    out = {}
    for field, comp in SETTINGS_COMPONENTS.items():
        if s.get(field) != comp:
            out[field] = [s.get(field), comp]
            s.set(field, comp)
    existing = {(flt(r.from_amount), flt(r.to_amount), flt(r.rate), str(r.effective_from)) for r in s.get("apit_slabs") or []}
    want = [(flt(a), flt(b), flt(c), APIT_EFFECTIVE_FROM) for a, b, c in APIT_SLABS]
    if not any(e[3] == APIT_EFFECTIVE_FROM for e in existing):
        out["apit_slabs"] = f"loaded {len(want)} slabs effective {APIT_EFFECTIVE_FROM}"
        for a, b, c, d in want:
            s.append("apit_slabs", {"from_amount": a, "to_amount": b, "rate": c, "effective_from": d})
    elif set(want) - existing:
        out["apit_slabs"] = f"slabs effective {APIT_EFFECTIVE_FROM} exist but differ — NOT changed (edit SLHRM Settings)"
    if out and not dry:
        s.flags.ignore_permissions = True
        s.save()
        frappe.db.commit()
    return out or "unchanged"


def replace_apit_slabs(effective_from=APIT_EFFECTIVE_FROM):
    """Replace the SLHRM Settings APIT slab rows of `effective_from` with APIT_SLABS (other dates kept).
    bench --site … execute slhrm.salary_setup.replace_apit_slabs"""
    frappe.set_user("Administrator")
    s = frappe.get_single("SLHRM Settings")
    keep = [r for r in s.get("apit_slabs") or [] if str(r.effective_from) != str(effective_from)]
    old = [(flt(r.from_amount), flt(r.to_amount), flt(r.rate)) for r in s.get("apit_slabs") or [] if str(r.effective_from) == str(effective_from)]
    s.set("apit_slabs", [])
    for r in keep:
        s.append("apit_slabs", {"from_amount": r.from_amount, "to_amount": r.to_amount, "rate": r.rate, "effective_from": r.effective_from})
    for a, b, c in APIT_SLABS:
        s.append("apit_slabs", {"from_amount": a, "to_amount": b, "rate": c, "effective_from": effective_from})
    s.flags.ignore_permissions = True
    s.save()
    frappe.db.commit()
    out = {"effective_from": effective_from, "old": old, "new": [(flt(a), flt(b), flt(c)) for a, b, c in APIT_SLABS], "kept_other_dates": len(keep)}
    print(json.dumps(out, indent=1))
    return out


def _rows_differ(ss):
    diffs = {}
    for table, rows in STRUCTURE_ROWS.items():
        have = [r for r in ss.get(table)]
        if [r.salary_component for r in have] != [r["salary_component"] for r in rows]:
            diffs[table] = {"existing": [r.salary_component for r in have], "expected": [r["salary_component"] for r in rows]}
            continue
        for h, w in zip(have, rows):
            d = {k: [h.get(k), v] for k, v in w.items() if k != "salary_component" and _norm(h.get(k)) != _norm(v)
                 and not (k == "amount" and flt(h.get(k)) == flt(v))}
            if d:
                diffs[f"{table}:{w['salary_component']}"] = d
    return diffs


def _active_structure():
    """The current version of STRUCTURE: the submitted, active one with the longest amendment chain."""
    names = frappe.get_all("Salary Structure", filters={"name": ["like", f"{STRUCTURE}%"], "docstatus": 1}, pluck="name")
    names = [n for n in names if n == STRUCTURE or n.startswith(f"{STRUCTURE}-")]
    return sorted(names, key=lambda n: (len(n), n))[-1] if names else None


def _apply_structure(dry):
    current = _active_structure()
    if not current:
        if dry:
            return {"action": "create", "name": STRUCTURE}
        ss = frappe.get_doc({"doctype": "Salary Structure", "__newname": STRUCTURE, "company": COMPANY,
                             "currency": frappe.get_cached_value("Company", COMPANY, "default_currency"),
                             "payroll_frequency": "Monthly", "is_active": "Yes", **STRUCTURE_ROWS})
        ss.insert(ignore_permissions=True)
        ss.submit()
        frappe.db.commit()
        return {"action": "created", "name": ss.name}
    ss = frappe.get_doc("Salary Structure", current)
    diffs = _rows_differ(ss)
    if not diffs:
        return {"action": "unchanged", "name": current}
    users = frappe.get_all("Salary Structure Assignment", filters={"salary_structure": current, "docstatus": ["<", 2]},
                           fields=["name", "employee", "docstatus"])
    if dry:
        return {"action": "cancel + amend" if not users else "create v2", "name": current, "diffs": diffs,
                "ssa_using_it": users}
    if not users:
        ss.flags.ignore_permissions = True
        ss.cancel()
        new = frappe.copy_doc(ss)
        new.amended_from = ss.name
        new.docstatus = 0
        new.set("earnings", [])
        new.set("deductions", [])
        for table, rows in STRUCTURE_ROWS.items():
            for r in rows:
                new.append(table, r)
        new.insert(ignore_permissions=True)
        new.submit()
        frappe.db.commit()
        return {"action": "cancelled + amended", "cancelled": ss.name, "name": new.name, "diffs": diffs}
    name = f"{STRUCTURE} v2"
    if frappe.db.exists("Salary Structure", name):
        return {"action": "v2 exists — not changed", "name": name, "ssa_using_current": users}
    v2 = frappe.get_doc({"doctype": "Salary Structure", "__newname": name, "company": COMPANY,
                         "currency": frappe.get_cached_value("Company", COMPANY, "default_currency"),
                         "payroll_frequency": "Monthly", "is_active": "Yes", **STRUCTURE_ROWS})
    v2.insert(ignore_permissions=True)
    v2.submit()
    frappe.db.commit()
    return {"action": "created v2 (current is used by SSAs)", "name": v2.name, "ssa_using_current": users, "diffs": diffs}


def sync_epf_flags(flags, dry_run=0):
    """Set SLHRM's own Salary Component fields (only these) on existing components; returns what changed."""
    out = {}
    for name, want in flags.items():
        if not frappe.db.exists("Salary Component", name):
            out[name] = "missing"
            continue
        cur = frappe.db.get_value("Salary Component", name, list(want), as_dict=True)
        diff = {k: v for k, v in want.items() if flt(cur.get(k)) != flt(v)}
        if diff:
            if not cint(dry_run):
                doc = frappe.get_doc("Salary Component", name)
                doc.update(diff)
                doc.save(ignore_permissions=True)
            out[name] = {"set": diff, "was": {k: cur.get(k) for k in diff}}
        else:
            out[name] = "unchanged"
    if not cint(dry_run):
        frappe.db.commit()
    return out


def describe():
    """Print the current Standard Staff Structure as stored (read-only)."""
    name = _active_structure()
    ss = frappe.get_doc("Salary Structure", name)
    print(name, "docstatus", ss.docstatus)
    for table in ("earnings", "deductions"):
        for r in ss.get(table):
            f = frappe.db.get_value("Salary Component", r.salary_component,
                                    ["slhrm_epf_applicable", "slhrm_epf_rate", "slhrm_reduces_epf_base", "depends_on_payment_days"], as_dict=True)
            print(table, r.salary_component, r.abbr, flt(r.amount), r.formula or "", "stat" if cint(r.statistical_component) else "",
                  f"epf_applicable={cint(f.slhrm_epf_applicable)} epf_rate={flt(f.slhrm_epf_rate)} reduces={cint(f.slhrm_reduces_epf_base)} dpd={cint(f.depends_on_payment_days)}")
