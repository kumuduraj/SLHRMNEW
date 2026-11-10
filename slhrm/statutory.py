# slhrm/statutory.py
"""EPF / ETF on the FINAL (prorated, post-package) earnings of a Salary Slip.

Configured on Salary Component (SLHRM custom fields, fixtures):
  slhrm_epf_applicable  (earnings)   the row's final amount counts toward the EPF/ETF base
  slhrm_epf_rate        (deductions, statistical components)  % of that base

apply_epf(slip), run after apply_package_overrides (see slhrm.overrides.salary_slip.apply_salary_rules):
  epf_base = sum of final earning amounts whose component is flagged (OT only if its component is
             flagged; rows marked do_not_include_in_total never count)
  deduction rows with a rate -> amount = round(epf_base * rate / 100, 2); a rated deduction that the
             structure lists but HRMS dropped (zero value) is added back
  statistical rows with a rate -> same value, returned as the EMPLOYER lines; never in totals
  totals -> HRMS's own get_component_totals() / set_net_pay()

The structure formulas of rated components (e.g. base * 0.08) only make the row exist; their values
are always replaced here.

v0.1.0: deduction rows whose component has slhrm_reduces_epf_base (No Pay) are SUBTRACTED from the EPF
base and from the APIT taxable amount.

APIT (monthly Advance Personal Income Tax, SLHRM-calculated):
  taxable = all earnings on the slip (not do_not_include_in_total; incl. OT and Other
            Allowance) - deductions flagged slhrm_reduces_epf_base (No Pay)
  APIT    = progressive sum over the SLHRM Settings "APIT Slab" rows (slab set with the latest
            effective_from <= the period start), rounded to 2 dp; 0 for Employee.slhrm_apit_exempt
  row     = SLHRM Settings apit_component (added / updated / removed when 0); totals re-done the HRMS way.
"""
import frappe
from frappe.utils import cint, flt, getdate

RATE_FIELD = "slhrm_epf_rate"
APPLICABLE_FIELD = "slhrm_epf_applicable"
REDUCES_FIELD = "slhrm_reduces_epf_base"
APIT_EXEMPT_FIELD = "slhrm_apit_exempt"
SETTINGS = "SLHRM Settings"


def _flags(components):
    if not components:
        return {}
    return {
        r.name: r
        for r in frappe.get_all(
            "Salary Component",
            filters={"name": ["in", list(components)]},
            fields=["name", "salary_component_abbr", APPLICABLE_FIELD, RATE_FIELD, REDUCES_FIELD],
        )
    }


def _structure_deductions(salary_structure):
    """Deduction rows of the slip's structure (incl. statistical ones), in structure order."""
    return frappe.get_all(
        "Salary Detail",
        filters={"parent": salary_structure, "parenttype": "Salary Structure", "parentfield": "deductions"},
        fields=["salary_component", "abbr", "statistical_component", "do_not_include_in_total",
                "do_not_include_in_accounts", "is_tax_applicable", "variable_based_on_taxable_salary",
                "exempted_from_income_tax"],
        order_by="idx asc",
    )


def reductions(slip, flags=None):
    """Sum of deduction rows whose component reduces the EPF base / APIT taxable (No Pay)."""
    rows = [r for r in slip.get("deductions") or [] if not r.do_not_include_in_total]
    flags = flags if flags is not None else _flags({r.salary_component for r in rows})
    return flt(sum(flt(r.amount) for r in rows
                   if flags.get(r.salary_component) and cint(flags[r.salary_component].get(REDUCES_FIELD))), 2)


def epf_base(slip, flags=None):
    """EPF-applicable earnings - No Pay (never below 0)."""
    rows = [r for r in slip.get("earnings") or [] if not r.do_not_include_in_total]
    if flags is None:
        flags = _flags({r.salary_component for r in rows} | {r.salary_component for r in slip.get("deductions") or []})
    earned = sum(flt(r.amount) for r in rows
                 if flags.get(r.salary_component) and flags[r.salary_component].get(APPLICABLE_FIELD))
    return flt(max(0.0, earned - reductions(slip, flags)), 2)


def apply_epf(slip):
    """Set EPF/ETF rows from the final earnings and re-total the slip the HRMS way.

    Returns {"epf_base": float, "employer": [{component, abbr, amount, rate}], "applied": bool}.
    """
    out = {"epf_base": 0.0, "employer": [], "applied": False}
    structure_rows = _structure_deductions(slip.salary_structure) if slip.get("salary_structure") else []
    names = ({r.salary_component for r in slip.get("earnings") or []}
             | {r.salary_component for r in slip.get("deductions") or []}
             | {r.salary_component for r in structure_rows})
    flags = _flags(names)
    rate = lambda c: flt(flags[c].get(RATE_FIELD)) if c in flags else 0.0  # noqa: E731
    base = epf_base(slip, flags)
    out["epf_base"] = base
    value = lambda c: flt(base * rate(c) / 100, 2)  # noqa: E731

    have = {r.salary_component for r in slip.get("deductions") or []}
    for r in slip.get("deductions") or []:
        if r.do_not_include_in_total or rate(r.salary_component) <= 0:
            continue
        r.amount = r.default_amount = value(r.salary_component)
        r.additional_amount = 0
        out["applied"] = True

    for s in structure_rows:
        c = s.salary_component
        if rate(c) <= 0:
            continue
        if s.statistical_component or s.do_not_include_in_total:
            out["employer"].append({"component": c, "abbr": s.abbr, "amount": value(c), "rate": rate(c)})
            out["applied"] = True
        elif c not in have:  # zero-valued at formula time (e.g. package earnings) -> HRMS dropped it
            row = slip.append("deductions", {})
            for attr in ("salary_component", "abbr", "do_not_include_in_accounts", "is_tax_applicable",
                         "variable_based_on_taxable_salary", "exempted_from_income_tax"):
                row.set(attr, s.get(attr))
            row.depends_on_payment_days = 0
            row.amount = row.default_amount = value(c)
            row.additional_amount = 0
            have.add(c)
            out["applied"] = True

    retotal(slip)
    return out


def retotal(slip):
    """Totals via HRMS's own helpers: gross = sum of the final (already prorated) earning amounts,
    then set_net_pay() for total deduction, net, rounded total, base_* and words."""
    slip.set_precision_for_component_amounts()
    slip.gross_pay = slip.get_component_totals("earnings")
    slip.base_gross_pay = flt(flt(slip.gross_pay) * flt(slip.exchange_rate), slip.precision("base_gross_pay"))
    slip.set_net_pay()


# ── APIT ────────────────────────────────────────────────────────


def apit_component():
    return frappe.db.get_single_value(SETTINGS, "apit_component")


def apit_slabs(on_date):
    """Slab rows of the set with the latest effective_from <= on_date: [(from, to or None, rate)]."""
    rows = frappe.get_all("SLHRM APIT Slab", filters={"parent": SETTINGS, "parenttype": SETTINGS},
                          fields=["from_amount", "to_amount", "rate", "effective_from"])
    d = getdate(on_date)
    dates = sorted({getdate(r.effective_from) for r in rows if r.effective_from and getdate(r.effective_from) <= d})
    if not dates:
        return []
    chosen = dates[-1]
    return sorted(((flt(r.from_amount), flt(r.to_amount) or None, flt(r.rate)) for r in rows
                   if r.effective_from and getdate(r.effective_from) == chosen), key=lambda x: x[0])


def calc_apit(taxable, slabs):
    """Pure: (amount rounded to 2 dp, bands [{from, to, rate, portion, tax}]) — progressive over the slabs."""
    taxable = max(0.0, flt(taxable))
    bands, total = [], 0.0
    for lo, hi, rate in slabs:
        top = taxable if hi is None else min(taxable, hi)
        portion = max(0.0, top - lo)
        tax = portion * rate / 100
        if portion > 0:
            bands.append({"from": lo, "to": hi, "rate": rate, "portion": flt(portion, 2), "tax": flt(tax, 4)})
        total += tax
    return flt(total, 2), bands


def is_apit_exempt(employee):
    return bool(employee) and cint(frappe.db.get_value("Employee", employee, APIT_EXEMPT_FIELD))


def apit_taxable(slip, flags=None):
    rows = [r for r in slip.get("earnings") or [] if not r.do_not_include_in_total]
    if flags is None:
        flags = _flags({r.salary_component for r in slip.get("deductions") or []})
    return flt(max(0.0, sum(flt(r.amount) for r in rows) - reductions(slip, flags)), 2)


def worksheet_apit(taxable_base, ot_amount=0, employee=None, on_date=None):
    """APIT for a worksheet row: preview taxable (without worksheet OT) + OT —
    the same amount the final slip computes once the OT arrives as Additional Salary."""
    if not apit_component() or is_apit_exempt(employee):
        return 0.0
    amount, _bands = calc_apit(flt(taxable_base) + flt(ot_amount), apit_slabs(on_date))
    return amount


def apply_apit(slip):
    """Set the APIT deduction row (after package overrides and EPF) and re-total the HRMS way.
    Returns {component, taxable, amount, exempt, bands}."""
    comp = apit_component()
    out = {"component": comp, "taxable": 0.0, "amount": 0.0, "exempt": False, "bands": []}
    if not comp:
        return out
    out["exempt"] = is_apit_exempt(slip.employee)
    out["taxable"] = apit_taxable(slip)
    if not out["exempt"]:
        out["amount"], out["bands"] = calc_apit(out["taxable"], apit_slabs(slip.start_date))
    rows = [r for r in slip.get("deductions") or [] if r.salary_component == comp and not r.additional_salary]
    if out["amount"] > 0:
        row = rows[0] if rows else None
        if not row:
            abbr = frappe.db.get_value("Salary Component", comp, "salary_component_abbr")
            row = slip.append("deductions", {"salary_component": comp, "abbr": abbr})
            row.depends_on_payment_days = 0
        row.amount = row.default_amount = out["amount"]
        row.additional_amount = 0
        for extra in rows[1:]:
            slip.remove(extra)
    else:
        for r in rows:
            slip.remove(r)
    retotal(slip)
    return out
