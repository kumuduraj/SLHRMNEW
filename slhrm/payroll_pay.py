# slhrm/payroll_pay.py
"""Pay composition for the Payroll Worksheet — ONE rule, used by load_payroll_data,
PayrollWorksheet._recalculate_all and slhrm.api.calc_worksheet_row (the JS does no math).

RULE (mirrors what HRMS puts on the Salary Slip for a full month):
    total_earning   = structure earnings + OT (normal + double) + Additional Salary earnings
    total_deduction = structure deductions + Additional Salary deductions + loan repayment
    net_pay         = total_earning - total_deduction

- "structure earnings/deductions" = every component of the employee's Salary Structure,
  evaluated with the SSA base. A Basic component with formula `base` therefore already
  carries the base salary: `base` is a formula input shown for reference and is NEVER
  added on its own (adding it caused the old base double count).
- "Additional Salary" = submitted records for the period, EXCLUDING the OT records a Payroll
  Worksheet creates (ref_doctype = 'Payroll Worksheet') — those are counted as OT.
- No proration: assumes full payment days. The Salary Slip prorates components with
  depends_on_payment_days by payment days / working days, so absences make them differ.
"""
import re

import frappe
from frappe.utils import flt

PRECISION = 2


# ── Salary Structure ────────────────────────────────────────────


def get_latest_ssa(employees, as_on):
    """{employee: _dict(name, base, salary_structure)} — latest submitted SSA with from_date <= as_on."""
    if not employees:
        return {}
    rows = frappe.db.sql(
        """
        SELECT ssa.name, ssa.employee, ssa.base, ssa.salary_structure, ssa.from_date
        FROM `tabSalary Structure Assignment` ssa
        WHERE ssa.employee IN %(employees)s AND ssa.docstatus = 1 AND ssa.from_date <= %(as_on)s
        ORDER BY ssa.employee, ssa.from_date DESC, ssa.creation DESC
        """,
        {"employees": list(employees), "as_on": as_on},
        as_dict=True,
    )
    out = {}
    for r in rows:
        out.setdefault(r.employee, frappe._dict(name=r.name, base=flt(r.base), salary_structure=r.salary_structure))
    return out


def _get_package_components(employees):
    """Employee Salary Package amounts + override flags (legacy Employee Salary Component fallback)."""
    amounts, overrides = {}, {}
    if not employees:
        return amounts, overrides
    for r in frappe.db.sql(
        """
        SELECT esp.employee, espd.salary_component, espd.amount, espd.override
        FROM `tabEmployee Salary Package` esp
        INNER JOIN `tabEmployee Salary Package Detail` espd ON espd.parent = esp.name
        WHERE esp.employee IN %(employees)s
        """,
        {"employees": list(employees)},
        as_dict=True,
    ):
        amounts.setdefault(r.employee, {})[r.salary_component] = flt(r.amount)
        overrides.setdefault(r.employee, {})[r.salary_component] = r.override
    if not amounts:
        for r in frappe.db.sql(
            """
            SELECT employee, salary_component, amount
            FROM `tabEmployee Salary Component`
            WHERE employee IN %(employees)s
            """,
            {"employees": list(employees)},
            as_dict=True,
        ):
            amounts.setdefault(r.employee, {})[r.salary_component] = flt(r.amount)
    return amounts, overrides


def _eval_formula(formula, values):
    """Evaluate a structure formula: variable names -> numbers, then arithmetic only."""
    if not formula:
        return 0
    var_map = {k.upper(): v for k, v in values.items()}
    expr = re.sub(r"[A-Za-z_]+", lambda m: str(var_map.get(m.group(0).upper(), 0)), formula.strip())
    try:
        return flt(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return 0


def get_structure_amounts(employees, as_on):
    """Per employee: base, salary_structure, earnings {component: amount}, deductions {...},
    structure_earning_total, structure_deduction_total. Also returns the ordered component list
    [{name, type ('earnings'/'deductions'), abbr}] across all structures.
    """
    ssa_map = get_latest_ssa(employees, as_on)
    pkg_amounts, pkg_overrides = _get_package_components(employees)

    structures = list({s.salary_structure for s in ssa_map.values() if s.salary_structure})
    details, abbr = {}, {}
    if structures:
        for d in frappe.db.sql(
            """
            SELECT parent, parentfield, salary_component, amount, formula, idx
            FROM `tabSalary Detail`
            WHERE parenttype = 'Salary Structure' AND parent IN %(structures)s
            ORDER BY parent, parentfield, idx
            """,
            {"structures": structures},
            as_dict=True,
        ):
            details.setdefault(d.parent, []).append(d)
        names = list({d.salary_component for rows in details.values() for d in rows})
        for c in frappe.get_all("Salary Component", filters={"name": ["in", names]},
                                fields=["name", "salary_component_abbr"]):
            abbr[c.name] = c.salary_component_abbr or c.name.upper()[:10]

    components, seen = [], set()
    result = {}
    for emp in employees:
        ssa = ssa_map.get(emp)
        res = frappe._dict(base=0.0, salary_structure="", earnings={}, deductions={},
                           structure_earning_total=0.0, structure_deduction_total=0.0)
        result[emp] = res
        if not ssa:
            continue
        res.base, res.salary_structure = flt(ssa.base), ssa.salary_structure

        pkg = pkg_amounts.get(emp, {})
        ovr = pkg_overrides.get(emp, {})
        values = {"base": res.base}
        for comp, amt in pkg.items():
            for key in (abbr.get(comp, comp.upper()[:10]), comp.upper(), comp):
                values[key] = amt

        for d in details.get(ssa.salary_structure, []):
            comp = d.salary_component
            pkg_amt = pkg.get(comp, 0)
            if ovr.get(comp) and pkg_amt:
                amt = pkg_amt  # package override wins over the formula
            elif d.formula:
                amt = _eval_formula(d.formula, values)
            else:
                amt = pkg_amt or flt(d.amount)
            amt = flt(amt, PRECISION)
            for key in (abbr.get(comp, comp.upper()[:10]), comp.upper(), comp):
                values[key] = amt

            bucket = res.earnings if d.parentfield == "earnings" else res.deductions
            bucket[comp] = flt(bucket.get(comp, 0) + amt, PRECISION)
            if comp not in seen:
                seen.add(comp)
                components.append({"name": comp, "type": d.parentfield, "abbr": abbr.get(comp, comp.upper()[:10])})

        res.structure_earning_total = flt(sum(res.earnings.values()), PRECISION)
        res.structure_deduction_total = flt(sum(res.deductions.values()), PRECISION)
    return result, components


# ── Additional Salary ───────────────────────────────────────────


def get_additional_salary(employees, start_date, end_date):
    """Submitted Additional Salary for the period, excluding Payroll Worksheet OT records.

    Returns (rows, totals) where totals = {employee: {"earning": x, "deduction": y}}.
    """
    if not employees:
        return [], {}
    rows = frappe.db.sql(
        """
        SELECT ads.name, ads.employee, ads.employee_name, ads.salary_component, ads.amount,
               ads.type, sc.type AS component_type
        FROM `tabAdditional Salary` ads
        LEFT JOIN `tabSalary Component` sc ON sc.name = ads.salary_component
        WHERE ads.employee IN %(employees)s
            AND ads.docstatus = 1
            AND IFNULL(ads.ref_doctype, '') != 'Payroll Worksheet'
            AND (
                (ads.payroll_date BETWEEN %(start)s AND %(end)s)
                OR (
                    ads.from_date IS NOT NULL AND ads.to_date IS NOT NULL
                    AND ads.from_date <= %(end)s AND ads.to_date >= %(start)s
                )
            )
        """,
        {"employees": list(employees), "start": start_date, "end": end_date},
        as_dict=True,
    )
    totals = {}
    for r in rows:
        r.is_earning = (r.type == "Earning") if r.type else (r.component_type == "Earning")
        t = totals.setdefault(r.employee, {"earning": 0.0, "deduction": 0.0})
        t["earning" if r.is_earning else "deduction"] = flt(
            t["earning" if r.is_earning else "deduction"] + flt(r.amount), PRECISION
        )
    return rows, totals


# ── Composition ─────────────────────────────────────────────────


def compose_pay(structure_earning_total=0, structure_deduction_total=0, ot_amount=0,
                additional_earning_total=0, additional_deduction_total=0, loan_deduction=0):
    """Apply the RULE (module docstring). Returns the totals for one employee row."""
    earning = flt(structure_earning_total) + flt(ot_amount) + flt(additional_earning_total)
    deduction = flt(structure_deduction_total) + flt(additional_deduction_total) + flt(loan_deduction)
    return {
        "total_earning": flt(earning, PRECISION),
        "total_deduction": flt(deduction, PRECISION),
        "net_pay": flt(earning - deduction, PRECISION),
    }
