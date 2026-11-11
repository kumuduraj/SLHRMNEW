import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_first_day, get_last_day, nowdate

from slhrm.payroll_ot import get_marker_totals, get_ot_eligibility
from slhrm.payroll_pay import OT_INPUT_FIELDS, compose_pay, ot_fields, row_apit
from slhrm.statutory import apit_component

MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December",
}

OT_PERMLEVEL = 1


class PayrollWorksheet(Document):
    def autoname(self):
        branch_name = (self.branch or "BR").replace(" ", "")[:6].upper()
        self.name = frappe.model.naming.make_autoname(
            f"PWS-{self.payroll_year}-{self.payroll_month}-{branch_name}-.####"
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
        errors = [r for r in self.employees if (r.row_error or "").strip()]
        if errors:
            frappe.throw(
                _("Cannot submit: {0} row(s) could not be calculated. Fix them and use "
                  "Refresh Salary Data, or remove the rows:").format(len(errors))
                + "<br>"
                + "<br>".join(
                    frappe.utils.escape_html(f"{r.employee_name or r.employee}: {r.row_error}") for r in errors[:20]
                )
            )
        self._check_no_pay_days_current()

    def _check_no_pay_days_current(self):
        """No Pay is inside the stored preview (EPF / APIT), so it can't be recomputed on save: refuse to submit when
        the submitted markers now give different No Pay days than the loaded rows (marker changed after loading)."""
        marker = get_marker_totals([r.employee for r in self.employees], self.start_date, self.end_date)
        stale = [r for r in self.employees
                 if flt(r.no_pay_days) != flt((marker.get(r.employee) or {}).get("no_pay_days"))]
        if stale:
            frappe.throw(
                _("No Pay days changed in the Attendance Markers since this worksheet was loaded. Use Refresh Salary Data, "
                  "then submit:") + "<br>" + "<br>".join(
                    frappe.utils.escape_html("{0}: {1} → {2}".format(
                        r.employee_name or r.employee, flt(r.no_pay_days),
                        flt((marker.get(r.employee) or {}).get("no_pay_days")))) for r in stale[:20]))

    def on_submit(self):
        self._create_additional_salaries()
        if self.auto_create_payroll:
            self.create_payroll_entry()

    def on_cancel(self):
        self._cancel_additional_salaries()
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

    # ── Overtime + totals (server-side; never trust client OT values) ──

    def _recalculate_all(self):
        """Recalculate OT and pay totals for every row.

        - eligibility re-read from Employee; ineligible -> all OT 0
        - users without permlevel-1 write: new rows take the marker hours, existing rows keep the stored
          (approved) OT / short hours
        - users with permlevel-1 write: their OT / short hours stand; negatives are rejected
        - net OT, short balance, rate (Basic / 200 x 1.5) and amount always via slhrm.overtime (payroll_pay.ot_fields)
        - salary numbers (structure_gross/deduction incl. the worksheet No Pay, loan, basic_salary) come from the
          HRMS preview stored by load/refresh; this method does NOT rebuild the preview (slhrm/payroll_pay.py)
        """
        settings = frappe.get_cached_doc("SLHRM Settings")
        employees = [row.employee for row in self.employees if row.employee]
        eligibility = get_ot_eligibility(employees)
        can_edit_ot = self._can_write_ot()

        stored, marker = {}, None
        if not can_edit_ot:
            if not self.is_new():
                stored = {
                    r.name: r
                    for r in frappe.get_all(
                        "Payroll Worksheet Employee",
                        filters={"parent": self.name, "parenttype": self.doctype},
                        fields=["name", *OT_INPUT_FIELDS],
                    )
                }
            if any(row.name not in stored for row in self.employees):
                marker = get_marker_totals(employees, self.start_date, self.end_date)

        total_ot = total_no_pay = total_gross = total_ded = total_net = 0
        has_apit = bool(apit_component())

        for row in self.employees:
            row.ot_eligible = cint(eligibility.get(row.employee))
            if row.ot_eligible and not can_edit_ot:
                prev = stored.get(row.name) or (marker or {}).get(row.employee) or {}
                for field in OT_INPUT_FIELDS:
                    row.set(field, flt(prev.get(field)))
            elif row.ot_eligible:
                for field in OT_INPUT_FIELDS:
                    if flt(row.get(field)) < 0:
                        frappe.throw(
                            _("Row {0} ({1}): {2} cannot be negative.").format(
                                row.idx, row.employee_name or row.employee, row.meta.get_label(field)
                            )
                        )
            row.update(ot_fields(row.employee, row.ot_eligible, row.ot_hours, row.short_hours, row.basic_salary, settings))

            # pay = HRMS preview (structure_gross / structure_deduction incl. No Pay / loan) + OT; APIT incl. OT
            apit = row_apit(row, self.start_date) if has_apit else None
            row.update(compose_pay(
                row.structure_gross, row.structure_deduction, row.ot_amount,
                row.loan_deduction, row.apit_preview, apit,
            ))

            total_ot += flt(row.ot_amount)
            total_no_pay += flt(row.no_pay_amount)
            total_gross += flt(row.total_earning)
            total_ded += flt(row.total_deduction)
            total_net += flt(row.net_pay)

        self.total_employees = len(self.employees)
        self.total_ot_amount = total_ot
        self.total_no_pay_amount = total_no_pay
        self.total_gross_pay = total_gross
        self.total_deductions = total_ded
        self.total_net_pay = total_net

    def _can_write_ot(self):
        if frappe.session.user == "Administrator" or self.flags.ignore_permissions:
            return True
        return OT_PERMLEVEL in self.get_permlevel_access("write")

    # ── OT / No Pay -> Additional Salary ────────────────────────

    def _create_additional_salaries(self):
        """Per employee one submitted Additional Salary "Overtime" (ot_amount > 0, SLHRM Settings ot_component) and one
        "No Pay" (no_pay_amount > 0, no_pay_component); overwrite 0 (they add to manual entries), ref = this worksheet."""
        settings = frappe.get_cached_doc("SLHRM Settings")
        plan = [(settings.ot_component, "ot_amount", "ot_component"),
                (settings.no_pay_component, "no_pay_amount", "no_pay_component")]
        currency = self.currency or frappe.get_cached_value("Company", self.company, "default_currency")
        created = {}
        for component, field, setting in plan:
            rows = [r for r in self.employees if flt(r.get(field)) > 0]
            if not rows:
                continue
            if not component:
                frappe.throw(
                    _("Set {0} in {1} before submitting this worksheet.").format(
                        frappe.get_meta("SLHRM Settings").get_label(setting),
                        frappe.utils.get_link_to_form("SLHRM Settings", "SLHRM Settings"),
                    )
                )
            for row in rows:
                ads = frappe.new_doc("Additional Salary")
                ads.employee = row.employee
                ads.company = self.company
                ads.currency = currency
                ads.salary_component = component
                ads.amount = flt(row.get(field))
                ads.payroll_date = self.end_date
                ads.overwrite_salary_structure_amount = 0  # adds to the structure's 0 line and manual entries (v0.2.2)
                ads.ref_doctype = self.doctype
                ads.ref_docname = self.name
                # authorised by submitting this worksheet (HR Manager / System Manager)
                ads.flags.ignore_permissions = True
                ads.insert()
                ads.submit()
                created[component] = created.get(component, 0) + 1

        if created:
            frappe.msgprint(
                _("Created Additional Salary: {0}.").format(", ".join(f"{c} × {n}" for c, n in created.items())),
                alert=True,
            )

    def _cancel_additional_salaries(self):
        records = frappe.get_all(
            "Additional Salary",
            filters={"ref_doctype": self.doctype, "ref_docname": self.name},
            fields=["name", "docstatus"],
        )
        if not records:
            return

        names = [r.name for r in records]
        submitted_slips = frappe.db.sql_list(
            """
            SELECT DISTINCT ss.name
            FROM `tabSalary Detail` sd
            INNER JOIN `tabSalary Slip` ss ON ss.name = sd.parent AND sd.parenttype = 'Salary Slip'
            WHERE sd.additional_salary IN %(names)s AND ss.docstatus = 1
            """,
            {"names": names},
        )
        if submitted_slips:
            frappe.throw(
                _("Cannot cancel: these submitted Salary Slips include this worksheet's overtime / No Pay. "
                  "Cancel them first: {0}").format(", ".join(submitted_slips))
            )

        for r in records:
            ads = frappe.get_doc("Additional Salary", r.name)
            ads.flags.ignore_permissions = True
            if ads.docstatus == 1:
                ads.cancel()
            try:
                frappe.delete_doc("Additional Salary", r.name, ignore_permissions=True)
            except frappe.LinkExistsError:
                # still referenced by a draft Salary Slip: stays cancelled (no longer counted)
                pass

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
