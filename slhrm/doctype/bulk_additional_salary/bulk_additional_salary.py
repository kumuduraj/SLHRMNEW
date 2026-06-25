import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, now_datetime, getdate
import calendar


class BulkAdditionalSalary(Document):
    def validate(self):
        self.validate_salary_component()
        self.validate_employees()
        self.calculate_totals()

    def validate_salary_component(self):
        """Get the type of the selected salary component."""
        comp_type = frappe.db.get_value(
            "Salary Component", self.salary_component, "type"
        )
        if comp_type not in ("Earning", "Deduction"):
            frappe.throw(
                _("Salary Component '{0}' has invalid type '{1}'. Must be Earning or Deduction.").format(
                    self.salary_component, comp_type
                ),
                title=_("Invalid Salary Component"),
            )
        self.component_type = comp_type

    def validate_employees(self):
        """Basic validation on employee rows."""
        if not self.employees:
            frappe.throw(
                _("Employee table is empty. Click 'Get Employees' to load employees."),
                title=_("No Employees"),
            )

        for row in self.employees:
            if flt(row.amount) < 0:
                frappe.throw(
                    _("Row {0}: Amount cannot be negative for {1}").format(
                        row.idx, row.employee_name or row.employee
                    )
                )

    def calculate_totals(self):
        """Calculate summary fields."""
        self.total_employees = sum(
            1 for row in self.employees if flt(row.amount) > 0
        )
        self.total_amount = sum(
            flt(row.amount) for row in self.employees if flt(row.amount) > 0
        )

    def on_submit(self):
        """Create individual Additional Salary records for each employee with amount > 0."""
        if not self.employees:
            frappe.throw(_("No employees in the table."))

        created_count = 0
        payroll_date = self.get_payroll_date()

        for row in self.employees:
            if flt(row.amount) <= 0:
                row.db_set("status", "Skipped", update_modified=False)
                continue

            try:
                # Check for existing Additional Salary
                existing = self.check_existing_additional_salary(
                    row.employee, payroll_date
                )

                if existing and not self.overwrite_existing:
                    row.db_set("status", "Skipped", update_modified=False)
                    row.db_set(
                        "remarks",
                        _("Additional Salary {0} already exists. Enable 'Overwrite Existing' to replace.").format(existing),
                        update_modified=False,
                    )
                    row.db_set("additional_salary", existing, update_modified=False)
                    continue

                if existing and self.overwrite_existing:
                    # Cancel existing record
                    existing_doc = frappe.get_doc("Additional Salary", existing)
                    if existing_doc.docstatus == 1:
                        existing_doc.cancel()

                # Create new Additional Salary
                add_sal = frappe.new_doc("Additional Salary")
                add_sal.employee = row.employee
                add_sal.salary_component = self.salary_component
                add_sal.amount = flt(row.amount)
                add_sal.payroll_date = payroll_date
                add_sal.company = self.company
                add_sal.type = self.component_type or "Earning"
                add_sal.ref_doctype = self.doctype
                add_sal.ref_docname = self.name

                add_sal.insert(ignore_permissions=True)

                if self.auto_submit_additional_salary:
                    add_sal.submit()

                row.db_set("additional_salary", add_sal.name, update_modified=False)
                row.db_set("status", "Created", update_modified=False)
                created_count += 1

            except Exception as e:
                row.db_set("status", "Error", update_modified=False)
                row.db_set("remarks", str(e)[:500], update_modified=False)
                frappe.log_error(
                    title=f"Bulk Additional Salary Error - {row.employee}",
                    message=frappe.get_traceback(),
                )

        self.db_set("additional_salaries_created", created_count, update_modified=False)

        frappe.msgprint(
            _("{0} Additional Salary records created out of {1} employees.").format(
                created_count, self.total_employees
            ),
            title=_("Bulk Additional Salary"),
            indicator="green",
        )

    def on_cancel(self):
        """Cancel all linked Additional Salary records."""
        cancelled_count = 0

        for row in self.employees:
            if row.additional_salary:
                try:
                    add_sal = frappe.get_doc("Additional Salary", row.additional_salary)
                    if add_sal.docstatus == 1:
                        add_sal.cancel()
                        cancelled_count += 1
                except Exception:
                    frappe.log_error(
                        title=f"Bulk Additional Salary Cancel Error - {row.additional_salary}",
                        message=frappe.get_traceback(),
                    )

            row.db_set("status", "Pending", update_modified=False)
            row.db_set("additional_salary", None, update_modified=False)

        if cancelled_count:
            frappe.msgprint(
                _("{0} Additional Salary records cancelled.").format(cancelled_count),
                title=_("Cancelled"),
                indicator="orange",
            )

    def get_payroll_date(self):
        """
        Calculate the payroll date from month and year.
        Returns the last day of the selected month.
        """
        month_number = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12,
        }.get(self.payroll_month)

        if not month_number:
            frappe.throw(_("Invalid payroll month: {0}").format(self.payroll_month))

        last_day = calendar.monthrange(cint(self.payroll_year), month_number)[1]
        return f"{cint(self.payroll_year)}-{month_number:02d}-{last_day:02d}"

    def check_existing_additional_salary(self, employee, payroll_date):
        """
        Check if an Additional Salary already exists for this
        employee + component + payroll date.
        """
        existing = frappe.db.get_value(
            "Additional Salary",
            filters={
                "employee": employee,
                "salary_component": self.salary_component,
                "payroll_date": payroll_date,
                "docstatus": ["!=", 2],  # not cancelled
            },
            fieldname="name",
        )
        return existing


@frappe.whitelist()
def get_employees(branch, company, default_amount=0, show_all=0):
    """
    Fetch active employees for the given branch and company.
    Returns list of dicts for populating the child table.

    By default, only employees with an active Salary Structure Assignment
    are returned (required by Additional Salary). Set show_all=1 to include all.
    """
    if not branch:
        frappe.throw(_("Please select a Branch first."))

    employees = frappe.get_all(
        "Employee",
        filters={
            "branch": branch,
            "company": company,
            "status": "Active",
        },
        fields=["name", "employee_name", "designation", "department"],
        order_by="employee_name asc",
    )

    if not employees:
        frappe.throw(
            _("No active employees found in branch '{0}'.").format(branch),
            title=_("No Employees Found"),
        )

    default_amt = flt(default_amount)
    show_all = cint(show_all)

    result = []
    for emp in employees:
        if not show_all:
            # Only include employees with an active Salary Structure Assignment
            has_ssa = frappe.db.exists(
                "Salary Structure Assignment",
                {"employee": emp.name, "docstatus": 1},
            )
            if not has_ssa:
                continue

        result.append({
            "employee": emp.name,
            "employee_name": emp.employee_name,
            "designation": emp.designation,
            "department": emp.department,
            "amount": default_amt,
            "status": "Pending",
        })

    if not result:
        frappe.throw(
            _("No employees with active Salary Structure Assignment found in branch '{0}'.").format(branch),
            title=_("No Employees Found"),
        )

    return result
