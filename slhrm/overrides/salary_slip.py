import frappe
from frappe.utils import flt


def apply_salary_package(doc, method):
    if not doc.employee:
        return

    package_name = frappe.db.exists("Employee Salary Package", doc.employee)
    if not package_name:
        return

    package = frappe.get_doc("Employee Salary Package", package_name)
    if not package.components:
        return

    override_map = {}
    for row in package.components:
        if row.override and flt(row.amount) >= 0:
            override_map[row.salary_component] = {
                "amount": flt(row.amount),
                "type": row.salary_component_type,
                "depends_on_payment_days": row.depends_on_payment_days,
            }

    if not override_map:
        return

    total_working_days = flt(doc.total_working_days)
    payment_days = flt(doc.payment_days) or total_working_days

    for slip_row in doc.earnings:
        if slip_row.salary_component in override_map:
            pkg = override_map[slip_row.salary_component]
            amount = pkg["amount"]
            slip_row.default_amount = amount

            if pkg["depends_on_payment_days"] and total_working_days > 0:
                slip_row.amount = flt(amount * payment_days / total_working_days)
            else:
                slip_row.amount = amount

    for slip_row in doc.deductions:
        if slip_row.salary_component in override_map:
            pkg = override_map[slip_row.salary_component]
            amount = pkg["amount"]
            slip_row.default_amount = amount

            if pkg["depends_on_payment_days"] and total_working_days > 0:
                slip_row.amount = flt(amount * payment_days / total_working_days)
            else:
                slip_row.amount = amount

    doc.gross_pay = sum(flt(r.amount) for r in doc.earnings)
    doc.total_deduction = sum(flt(r.amount) for r in doc.deductions)
    doc.net_pay = flt(doc.gross_pay) - flt(doc.total_deduction)

    if hasattr(doc, "rounded_total"):
        doc.rounded_total = round(flt(doc.net_pay))
