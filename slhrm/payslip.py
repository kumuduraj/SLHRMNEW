# slhrm/payslip.py
"""Payslip lines for the "SLHRM Payslip" print format (jinja method `payslip_data`), read-only.

Order = the slip's Salary Structure rows (Standard Staff Structure-1: Basic Salary, Base Allowance, Vehicle Allowance,
Overtime, Other Allowance | Death Donation, No Pay, Other Deduction, Salary Advance, Personal Loan, Staff Bill,
EPF Employee 8%, APIT), then any other component on the slip. Every structure line is shown, zero included.
HRMS adds ONE slip row per Additional Salary (overwrite 0) next to the structure's 0 row, so amounts are SUMMED
per component here (two Salary Advances 5,000 + 3,000 → one line 8,000). Statistical rows (employer EPF 12% /
ETF 3%) never count in totals; they are listed separately (slhrm.statutory.employer_lines).
"""
import frappe
from frappe.utils import flt

from slhrm.statutory import employer_lines


def _structure_order(salary_structure, parentfield):
    if not salary_structure:
        return []
    return frappe.get_all("Salary Detail", filters={"parent": salary_structure, "parenttype": "Salary Structure",
                                                    "parentfield": parentfield},
                          fields=["salary_component", "statistical_component", "do_not_include_in_total"], order_by="idx asc")


def _lines(doc, table):
    order = [r.salary_component for r in _structure_order(doc.get("salary_structure"), table)
             if not (r.statistical_component or r.do_not_include_in_total)]
    sums = {}
    for r in doc.get(table) or []:
        if r.get("do_not_include_in_total") or r.get("statistical_component"):
            continue
        sums[r.salary_component] = flt(sums.get(r.salary_component, 0)) + flt(r.amount)
    comps = order + [c for c in sums if c not in order]
    return [{"component": c, "amount": flt(sums.get(c, 0), 2)} for c in comps]


def payslip_data(doc):
    """{earnings, deductions, gross, total_deduction, net, employer} for one Salary Slip (doc or name)."""
    if isinstance(doc, str):
        doc = frappe.get_doc("Salary Slip", doc)
    earnings, deductions = _lines(doc, "earnings"), _lines(doc, "deductions")
    return frappe._dict(
        earnings=earnings, deductions=deductions,
        gross=flt(doc.gross_pay, 2), total_deduction=flt(doc.total_deduction, 2), net=flt(doc.net_pay, 2),
        employer=employer_lines(doc),
    )
