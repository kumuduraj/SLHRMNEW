frappe.ui.form.on("Bulk Additional Salary", {
    refresh(frm) {
        // Set current year as default
        if (frm.is_new() && !frm.doc.payroll_year) {
            frm.set_value("payroll_year", new Date().getFullYear());
        }

        // Style the Get Employees button
        if (!frm.doc.docstatus) {
            frm.fields_dict.get_employees.input_type = "button";
            frm.fields_dict.get_employees.$input.addClass("btn-primary");
        }

        // Add "View Additional Salaries" button after submit
        if (frm.doc.docstatus === 1 && frm.doc.additional_salaries_created > 0) {
            frm.add_custom_button(__("View Additional Salaries"), function () {
                frappe.set_route("List", "Additional Salary", {
                    ref_doctype: "Bulk Additional Salary",
                    ref_docname: frm.doc.name,
                });
            });
        }

        // Summary indicators
        if (frm.doc.total_employees > 0) {
            frm.dashboard.add_indicator(
                __("Employees: {0}", [frm.doc.total_employees]),
                "blue"
            );
            frm.dashboard.add_indicator(
                __("Total: {0}", [format_currency(frm.doc.total_amount)]),
                "green"
            );
        }
    },

    get_employees(frm) {
        if (!frm.doc.branch) {
            frappe.throw(__("Please select a Branch first."));
            return;
        }
        if (!frm.doc.company) {
            frappe.throw(__("Please select a Company first."));
            return;
        }

        // Confirm if table already has data
        if (frm.doc.employees && frm.doc.employees.length > 0) {
            frappe.confirm(
                __("This will replace the current employee list. Continue?"),
                function () {
                    slhrm_fetch_employees(frm);
                }
            );
        } else {
            slhrm_fetch_employees(frm);
        }
    },

    salary_component(frm) {
        if (frm.doc.salary_component) {
            frappe.db.get_value(
                "Salary Component",
                frm.doc.salary_component,
                "type"
            ).then((r) => {
                if (r && r.message) {
                    frm.set_value("component_type", r.message.type);
                    frappe.show_alert({
                        message: __("Component type: {0}", [r.message.type]),
                        indicator: r.message.type === "Earning" ? "green" : "orange",
                    });
                }
            });
        } else {
            frm.set_value("component_type", "");
        }
    },

    default_amount(frm) {
        // Update all existing rows with the new default amount
        if (frm.doc.employees && frm.doc.employees.length > 0 && flt(frm.doc.default_amount) > 0) {
            frappe.confirm(
                __("Apply default amount {0} to all employees?", [format_currency(frm.doc.default_amount)]),
                function () {
                    frm.doc.employees.forEach(function (row) {
                        frappe.model.set_value(row.doctype, row.name, "amount", frm.doc.default_amount);
                    });
                    frm.refresh_field("employees");
                    slhrm_update_totals(frm);
                }
            );
        }
    },

    is_recurring(frm) {
        frm.toggle_reqd("start_date", frm.doc.is_recurring);
        frm.toggle_reqd("end_date", frm.doc.is_recurring);
    },

    start_date(frm) {
        slhrm_validate_recurring_dates(frm);
    },

    end_date(frm) {
        slhrm_validate_recurring_dates(frm);
    },
});

function slhrm_validate_recurring_dates(frm) {
    if (frm.doc.is_recurring && frm.doc.start_date && frm.doc.end_date) {
        if (frappe.datetime.get_diff(frm.doc.end_date, frm.doc.start_date) < 0) {
            frappe.msgprint(__("End Date must be after Start Date."));
            frm.set_value("end_date", "");
        }
    }
}

frappe.ui.form.on("Bulk Additional Salary Detail", {
    amount(frm, cdt, cdn) {
        slhrm_update_totals(frm);
    },

    employees_remove(frm, cdt, cdn) {
        slhrm_update_totals(frm);
    },
});

function slhrm_fetch_employees(frm) {
    frappe.call({
      method: "slhrm.slhrm.doctype.bulk_additional_salary.bulk_additional_salary.get_employees",
      args: {
        branch: frm.doc.branch,
        company: frm.doc.company,
        default_amount: frm.doc.default_amount || 0,
        show_all: frm.doc.show_all_employees || 0,
      },
        freeze: true,
        freeze_message: __("Loading employees..."),
        callback: function (r) {
            if (r.message) {
                frm.clear_table("employees");

                r.message.forEach(function (emp) {
                    let row = frm.add_child("employees");
                    row.employee = emp.employee;
                    row.employee_name = emp.employee_name;
                    row.designation = emp.designation;
                    row.department = emp.department;
                    row.amount = emp.amount;
                    row.status = emp.status;
                });

                frm.refresh_field("employees");
                slhrm_update_totals(frm);

                frappe.show_alert({
                    message: __("{0} employees loaded.", [r.message.length]),
                    indicator: "green",
                });
            }
        },
    });
}

function slhrm_update_totals(frm) {
    let total = 0;
    let count = 0;

    (frm.doc.employees || []).forEach(function (row) {
        if (flt(row.amount) > 0) {
            total += flt(row.amount);
            count += 1;
        }
    });

    frm.set_value("total_employees", count);
    frm.set_value("total_amount", total);
}
