import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, get_last_day, flt, cint, nowdate


MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December",
}


class PayrollWorksheet(Document):
    def autoname(self):
        branch_abbr = frappe.db.get_value("Branch", self.branch, "abbr") or "BR"
        self.name = frappe.model.naming.make_autoname(
            f"PWS-{self.payroll_year}-{self.payroll_month}-{branch_abbr}-.####"
        )

    def validate(self):
        self._set_dates()
        self._set_month_name()
        self._set_title()
        self._validate_no_duplicate()
        self._validate_employees()
        self._recalculate_all()

    def before_submit(self):
        if not self.employees:
            frappe.throw(_("Employee table is empty. Select branch and month to load data."))

    def on_submit(self):
        if self.auto_create_payroll:
            self._create_payroll_entry()

    def on_cancel(self):
        if self.payroll_entry:
            pe_docstatus = frappe.db.get_value("Payroll Entry", self.payroll_entry, "docstatus")
            if pe_docstatus == 1:
                frappe.throw(
                    _("Cannot cancel — Payroll Entry {0} is already submitted. "
                      "Cancel it first.").format(self.payroll_entry)
                )
            elif pe_docstatus == 0:
                frappe.delete_doc("Payroll Entry", self.payroll_entry, force=True)
                self.db_set("payroll_entry", None)

    def _set_dates(self):
        year = cint(self.payroll_year)
        month = cint(self.payroll_month)
        if not year or not month:
            return
        self.start_date = get_first_day(f"{year}-{month:02d}-01")
        self.end_date = get_last_day(f"{year}-{month:02d}-01")

    def _set_month_name(self):
        self.month_name = MONTH_NAMES.get(self.payroll_month, "")

    def _set_title(self):
        self.title = f"{self.branch} - {self.month_name} {self.payroll_year}"

    def _validate_no_duplicate(self):
        existing = frappe.db.exists(
            "Payroll Worksheet",
            {
                "company": self.company,
                "branch": self.branch,
                "payroll_year": self.payroll_year,
                "payroll_month": self.payroll_month,
                "docstatus": ["<", 2],
                "name": ["!=", self.name],
            },
        )
        if existing:
            frappe.throw(
                _("A Payroll Worksheet already exists for {0} - {1} {2} ({3})").format(
                    self.branch, self.month_name, self.payroll_year, existing
                )
            )

    def _validate_employees(self):
        if not self.employees:
            return
        seen = set()
        for row in self.employees:
            if row.employee in seen:
                frappe.throw(
                    _("Duplicate employee {0} in row {1}").format(row.employee, row.idx)
                )
            seen.add(row.employee)

    def _recalculate_all(self):
        total_ot = total_gross = total_ded = total_net = 0

        for row in self.employees:
            row.ot_amount = flt(row.ot_hours) * flt(row.ot_rate)
            row.total_earning = flt(row.base) + flt(row.ot_amount) + flt(row.additional_earning_total)
            row.total_deduction = flt(row.additional_deduction_total) + flt(row.loan_deduction)
            row.net_pay = flt(row.total_earning) - flt(row.total_deduction)

            total_ot += flt(row.ot_amount)
            total_gross += flt(row.total_earning)
            total_ded += flt(row.total_deduction)
            total_net += flt(row.net_pay)

        self.total_employees = len(self.employees)
        self.total_ot_amount = total_ot
        self.total_gross_pay = total_gross
        self.total_deductions = total_ded
        self.total_net_pay = total_net

    @frappe.whitelist()
    def create_payroll_entry(self):
        if self.docstatus != 1:
            frappe.throw(_("Submit the Payroll Worksheet first."))

        if self.payroll_entry:
            frappe.throw(
                _("Payroll Entry {0} already exists.").format(self.payroll_entry)
            )

        pe = frappe.new_doc("Payroll Entry")
        pe.company = self.company
        pe.department = None
        pe.posting_date = self.posting_date or nowdate()
        pe.payroll_frequency = "Monthly"
        pe.start_date = self.start_date
        pe.end_date = self.end_date
        pe.currency = self.currency or frappe.db.get_value(
            "Company", self.company, "default_currency"
        )
        pe.exchange_rate = 1
        pe.flags.ignore_permissions = True
        pe.save()

        self.db_set("payroll_entry", pe.name)

        frappe.msgprint(
            _("Payroll Entry {0} created. Open it to Get Employees and Create Salary Slips.").format(
                frappe.utils.get_link_to_form("Payroll Entry", pe.name)
            ),
            alert=True,
        )
        return pe.name
