import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, getdate, today


class EmployeeSalaryPackage(Document):
    def validate(self):
        self.validate_components()
        self.calculate_totals()

    def validate_components(self):
        if not self.components:
            frappe.throw(
                _("Salary components table is empty. Click 'Load Components' to populate."),
                title=_("No Components"),
            )

        seen = set()
        for row in self.components:
            if flt(row.amount) < 0:
                frappe.throw(
                    _("Row {0}: Amount for '{1}' cannot be negative.").format(
                        row.idx, row.salary_component
                    )
                )
            if row.salary_component in seen:
                frappe.throw(
                    _("Row {0}: Duplicate salary component '{1}'.").format(
                        row.idx, row.salary_component
                    )
                )
            seen.add(row.salary_component)

        has_earning = any(
            row.salary_component_type == "Earning"
            and row.override
            and flt(row.amount) > 0
            for row in self.components
        )
        if not has_earning:
            frappe.throw(
                _("At least one Earning component must have an amount greater than zero."),
                title=_("No Earnings"),
            )

    def calculate_totals(self):
        self.total_earning = sum(
            flt(row.amount) for row in self.components
            if row.salary_component_type == "Earning" and row.override
        )
        self.total_deduction = sum(
            flt(row.amount) for row in self.components
            if row.salary_component_type == "Deduction" and row.override
        )
        self.net_total = flt(self.total_earning) - flt(self.total_deduction)

    def on_update(self):
        self.manage_ssa()

    def manage_ssa(self):
        new_base = flt(self.total_earning)
        new_from_date = getdate(self.effective_from)

        existing_ssa = self._get_managed_ssa()

        if existing_ssa:
            old_base = flt(existing_ssa.base)
            old_from_date = getdate(existing_ssa.from_date)
            old_structure = existing_ssa.salary_structure

            no_change = (
                old_base == new_base
                and old_from_date == new_from_date
                and old_structure == self.salary_structure
            )

            if no_change:
                self.db_set("current_ssa", existing_ssa.name, update_modified=False)
                self.db_set("current_ssa_base", old_base, update_modified=False)
                self.db_set("ssa_status", "Active", update_modified=False)
                return

            self._cancel_ssa(existing_ssa.name)

        ssa_name = self._create_ssa(new_base, new_from_date)

        self.db_set("current_ssa", ssa_name, update_modified=False)
        self.db_set("current_ssa_base", new_base, update_modified=False)
        self.db_set("ssa_status", "Active", update_modified=False)

        action = "updated" if existing_ssa else "created"
        frappe.msgprint(
            _("Salary Structure Assignment <b>{0}</b> {1} with base {2}, effective {3}.").format(
                ssa_name,
                action,
                frappe.format_value(new_base, {"fieldtype": "Currency"}),
                frappe.format_value(new_from_date, {"fieldtype": "Date"}),
            ),
            title=_("SSA {0}".format(action.title())),
            indicator="green",
        )

    def _get_managed_ssa(self):
        ssa_name = frappe.db.get_value(
            "Salary Structure Assignment",
            filters={
                "employee": self.employee,
                "slhrm_managed": 1,
                "docstatus": 1,
            },
            fieldname="name",
            order_by="from_date desc",
        )

        if ssa_name:
            return frappe.get_doc("Salary Structure Assignment", ssa_name)
        return None

    def _cancel_ssa(self, ssa_name):
        try:
            ssa = frappe.get_doc("Salary Structure Assignment", ssa_name)
            if ssa.docstatus == 1:
                ssa.flags.ignore_permissions = True
                ssa.cancel()
                frappe.db.commit()
        except Exception:
            frappe.log_error(
                title=f"SLHRM: Error cancelling SSA {ssa_name}",
                message=frappe.get_traceback(),
            )
            frappe.throw(
                _("Could not cancel existing SSA {0}. Please check error log.").format(ssa_name)
            )

    def _create_ssa(self, base, from_date):
        ssa = frappe.new_doc("Salary Structure Assignment")
        ssa.employee = self.employee
        ssa.salary_structure = self.salary_structure
        ssa.company = self.company
        ssa.from_date = from_date
        ssa.base = base
        ssa.slhrm_managed = 1
        ssa.slhrm_package_link = self.name

        if self.income_tax_slab:
            ssa.income_tax_slab = self.income_tax_slab

        ssa.flags.ignore_permissions = True
        ssa.insert()
        ssa.submit()
        frappe.db.commit()

        return ssa.name

    def on_trash(self):
        existing_ssa = self._get_managed_ssa()
        if existing_ssa:
            self._cancel_ssa(existing_ssa.name)
            frappe.msgprint(
                _("SSA {0} cancelled because the Employee Salary Package was deleted.").format(
                    existing_ssa.name
                ),
                indicator="orange",
            )


@frappe.whitelist()
def load_components(salary_structure):
    if not salary_structure:
        frappe.throw(_("Please select a Salary Structure."))

    structure = frappe.get_doc("Salary Structure", salary_structure)
    components = []

    for row in structure.earnings:
        comp_doc = frappe.get_cached_doc("Salary Component", row.salary_component)
        is_formula = cint(row.amount_based_on_formula)

        components.append({
            "salary_component": row.salary_component,
            "salary_component_type": "Earning",
            "amount": flt(row.amount) if not is_formula else 0,
            "override": 1,
            "default_formula": row.formula or "",
            "default_amount": flt(row.amount),
            "depends_on_payment_days": cint(comp_doc.depends_on_payment_days),
        })

    for row in structure.deductions:
        comp_doc = frappe.get_cached_doc("Salary Component", row.salary_component)
        is_formula = cint(row.amount_based_on_formula)

        components.append({
            "salary_component": row.salary_component,
            "salary_component_type": "Deduction",
            "amount": flt(row.amount) if not is_formula else 0,
            "override": 0 if is_formula else 1,
            "default_formula": row.formula or "",
            "default_amount": flt(row.amount),
            "depends_on_payment_days": cint(comp_doc.depends_on_payment_days),
        })

    return components


@frappe.whitelist()
def get_active_ssa_structure(employee):
    if not employee:
        frappe.throw(_("Please select an Employee."))

    ssa = frappe.db.get_value(
        "Salary Structure Assignment",
        filters={
            "employee": employee,
            "docstatus": 1,
        },
        fieldname=["salary_structure", "base", "from_date", "income_tax_slab"],
        order_by="from_date desc",
        as_dict=True,
    )

    return ssa
