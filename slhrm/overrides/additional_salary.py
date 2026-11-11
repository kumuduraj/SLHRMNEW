# slhrm/overrides/additional_salary.py
"""doc_events Additional Salary.before_validate (v0.2.2): for SLHRM's payslip components entries ADD UP.

HRMS adds one slip row per Additional Salary when overwrite_salary_structure_amount = 0 (the structure's 0 line
stays); with overwrite = 1 a second Additional Salary of the same component in the period is refused ("Multiple
Additional Salaries with overwrite property"). So two Salary Advances of 5,000 + 3,000 give 8,000 only with 0.
"""
import frappe
from frappe import _
from frappe.utils import cint

from slhrm.salary_setup import ADDITIVE_COMPONENTS


def before_validate(doc, method=None):
    if doc.salary_component in ADDITIVE_COMPONENTS and cint(doc.overwrite_salary_structure_amount):
        doc.overwrite_salary_structure_amount = 0
        if not doc.flags.ignore_permissions and frappe.request:
            frappe.msgprint(_("{0}: entries of a month add up, so Overwrite Salary Structure Amount was turned off.").format(
                doc.salary_component), alert=True, indicator="blue")
