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
"""
import frappe
from frappe.utils import flt

RATE_FIELD = "slhrm_epf_rate"
APPLICABLE_FIELD = "slhrm_epf_applicable"


def _flags(components):
    if not components:
        return {}
    return {
        r.name: r
        for r in frappe.get_all(
            "Salary Component",
            filters={"name": ["in", list(components)]},
            fields=["name", "salary_component_abbr", APPLICABLE_FIELD, RATE_FIELD],
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


def epf_base(slip, flags=None):
    rows = [r for r in slip.get("earnings") or [] if not r.do_not_include_in_total]
    flags = flags if flags is not None else _flags({r.salary_component for r in rows})
    return flt(sum(flt(r.amount) for r in rows
                   if flags.get(r.salary_component) and flags[r.salary_component].get(APPLICABLE_FIELD)), 2)


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
