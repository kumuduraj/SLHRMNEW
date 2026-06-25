frappe.ui.form.on("Employee Salary Package", {
    refresh(frm) {
        if (frm.fields_dict.load_components && frm.fields_dict.load_components.$input) {
            frm.fields_dict.load_components.$input.addClass("btn-primary");
        }

        if (frm.doc.current_ssa) {
            frm.add_custom_button(
                __("View SSA: {0}", [frm.doc.current_ssa]),
                function () {
                    frappe.set_route("Form", "Salary Structure Assignment", frm.doc.current_ssa);
                },
                __("Links")
            );
        }

        if (!frm.is_new()) {
            frm.add_custom_button(
                __("Salary Slips"),
                function () {
                    frappe.set_route("List", "Salary Slip", {
                        employee: frm.doc.employee,
                    });
                },
                __("Links")
            );
        }

        if (frm.doc.ssa_status === "Active") {
            frm.dashboard.add_indicator(__("SSA: Active"), "green");
        } else if (frm.doc.current_ssa) {
            frm.dashboard.add_indicator(__("SSA: {0}", [frm.doc.ssa_status || "Unknown"]), "orange");
        } else if (!frm.is_new()) {
            frm.dashboard.add_indicator(__("SSA: Not Created"), "red");
        }
    },

    employee(frm) {
        if (!frm.doc.employee) return;

        frappe.call({
            method: "slhrm.doctype.employee_salary_package.employee_salary_package.get_active_ssa_structure",
            args: { employee: frm.doc.employee },
            callback: function (r) {
                if (r.message) {
                    frm.set_value("salary_structure", r.message.salary_structure);
                    if (r.message.income_tax_slab) {
                        frm.set_value("income_tax_slab", r.message.income_tax_slab);
                    }
                    if (!frm.doc.effective_from && r.message.from_date) {
                        frm.set_value("effective_from", r.message.from_date);
                    }
                    frappe.show_alert({
                        message: __("Salary Structure loaded from existing SSA."),
                        indicator: "blue",
                    });
                }
            },
        });

        if (!frm.doc.effective_from) {
            frm.set_value("effective_from", frappe.datetime.get_today());
        }
    },

    salary_structure(frm) {
        if (!frm.doc.salary_structure) return;

        if (frm.doc.components && frm.doc.components.length > 0) {
            frappe.confirm(
                __("Salary Structure changed. Reload components? This will replace current amounts."),
                function () {
                    slhrm_load_components(frm);
                }
            );
        } else {
            slhrm_load_components(frm);
        }
    },

    load_components(frm) {
        if (!frm.doc.salary_structure) {
            frappe.throw(__("Please select a Salary Structure first."));
            return;
        }

        if (frm.doc.components && frm.doc.components.length > 0) {
            frappe.confirm(
                __("This will replace all current components and amounts. Continue?"),
                function () {
                    slhrm_load_components(frm);
                }
            );
        } else {
            slhrm_load_components(frm);
        }
    },

    effective_from(frm) {
        if (frm.doc.effective_from && !frm.is_new() && frm.doc.current_ssa) {
            frm.dashboard.add_comment(
                __("Changing Effective From will create a new SSA on save."),
                "blue",
                true
            );
        }
    },
});

frappe.ui.form.on("Employee Salary Package Detail", {
    amount(frm, cdt, cdn) {
        slhrm_calculate_package_totals(frm);
    },

    override(frm, cdt, cdn) {
        slhrm_calculate_package_totals(frm);
    },

    components_remove(frm, cdt, cdn) {
        slhrm_calculate_package_totals(frm);
    },
});


function slhrm_load_components(frm) {
    frappe.call({
        method: "slhrm.doctype.employee_salary_package.employee_salary_package.load_components",
        args: { salary_structure: frm.doc.salary_structure },
        freeze: true,
        freeze_message: __("Loading components from Salary Structure..."),
        callback: function (r) {
            if (!r.message) return;

            frm.clear_table("components");

            r.message.forEach(function (comp) {
                let row = frm.add_child("components");
                row.salary_component = comp.salary_component;
                row.salary_component_type = comp.salary_component_type;
                row.amount = comp.amount;
                row.override = comp.override;
                row.default_formula = comp.default_formula;
                row.default_amount = comp.default_amount;
                row.depends_on_payment_days = comp.depends_on_payment_days;
            });

            frm.refresh_field("components");
            slhrm_calculate_package_totals(frm);

            frappe.show_alert({
                message: __("{0} components loaded. Enter amounts and save.", [r.message.length]),
                indicator: "green",
            });
        },
    });
}

function slhrm_calculate_package_totals(frm) {
    let total_earning = 0;
    let total_deduction = 0;

    (frm.doc.components || []).forEach(function (row) {
        if (!row.override) return;

        if (row.salary_component_type === "Earning") {
            total_earning += flt(row.amount);
        } else if (row.salary_component_type === "Deduction") {
            total_deduction += flt(row.amount);
        }
    });

    frm.set_value("total_earning", total_earning);
    frm.set_value("total_deduction", total_deduction);
    frm.set_value("net_total", total_earning - total_deduction);
}
