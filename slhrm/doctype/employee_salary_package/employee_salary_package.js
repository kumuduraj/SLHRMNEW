// slhrm/doctype/employee_salary_package/employee_salary_package.js
//
// Effective dating: every amount change applies from Effective From (default: first day of next month);
// the server creates a new Salary Structure Assignment from that date and keeps earlier ones.
// Load Components never replaces amounts: it only adds missing structure components and offers
// components no longer in the structure for removal (the user ticks them).

const ESP_API = "slhrm.doctype.employee_salary_package.employee_salary_package.";

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
                    frappe.set_route("List", "Salary Slip", { employee: frm.doc.employee });
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

        if (frm.is_new() && !frm.doc.effective_from) {
            slhrm_default_effective_from(frm);
        }
        frm._slhrm_eff_touched = false;  // a fresh edit session starts on the saved date
        slhrm_render_history(frm);
    },

    employee(frm) {
        if (!frm.doc.employee) return;

        frappe.call({
            method: ESP_API + "get_active_ssa_structure",
            args: { employee: frm.doc.employee },
            callback: function (r) {
                if (r.message) {
                    frm.set_value("salary_structure", r.message.salary_structure);
                    if (r.message.income_tax_slab) {
                        frm.set_value("income_tax_slab", r.message.income_tax_slab);
                    }
                    frappe.show_alert({
                        message: __("Salary Structure loaded from existing SSA."),
                        indicator: "blue",
                    });
                }
            },
        });
        if (!frm.doc.effective_from) slhrm_default_effective_from(frm);
    },

    salary_structure(frm) {
        if (!frm.doc.salary_structure) return;
        slhrm_plan_load_components(frm, __("Salary Structure changed"));
    },

    load_components(frm) {
        if (!frm.doc.salary_structure) {
            frappe.throw(__("Please select a Salary Structure first."));
            return;
        }
        slhrm_plan_load_components(frm, __("Load Components"));
    },

    effective_from(frm) {
        // the user picked a date (not our automatic default) -> keep it for this edit
        if (frm.doc.effective_from && frm.doc.effective_from !== frm._slhrm_auto_eff) {
            frm._slhrm_eff_touched = true;
        }
    },
});

frappe.ui.form.on("Employee Salary Package Detail", {
    amount(frm) {
        slhrm_on_amount_change(frm);
    },

    override(frm) {
        slhrm_on_amount_change(frm);
    },

    components_remove(frm) {
        slhrm_on_amount_change(frm);
    },
});


function slhrm_first_of_next_month() {
    const d = frappe.datetime.str_to_obj(frappe.datetime.get_today());
    return frappe.datetime.obj_to_str(new Date(d.getFullYear(), d.getMonth() + 1, 1));
}


function slhrm_default_effective_from(frm) {
    frm._slhrm_auto_eff = slhrm_first_of_next_month();
    return frm.set_value("effective_from", frm._slhrm_auto_eff);
}


function slhrm_on_amount_change(frm) {
    slhrm_calculate_package_totals(frm);
    // an amount change applies from a NEW date unless the user chose one in this edit
    if (!frm.is_new() && !frm._slhrm_eff_touched && frm.doc.effective_from !== slhrm_first_of_next_month()) {
        slhrm_default_effective_from(frm).then(() => {
            frappe.show_alert({
                message: __("Effective From set to {0} for this change — earlier periods keep their amounts.",
                    [frappe.datetime.str_to_user(frm.doc.effective_from)]),
                indicator: "blue",
            });
        });
    }
}


// ── Load Components: plan → confirm → apply (never replaces amounts) ──

function slhrm_plan_load_components(frm, title) {
    const current = (frm.doc.components || []).map(r => ({
        salary_component: r.salary_component, salary_component_type: r.salary_component_type,
        amount: r.amount, override: r.override,
    }));
    frappe.call({
        method: ESP_API + "plan_load_components",
        args: { salary_structure: frm.doc.salary_structure, components: JSON.stringify(current) },
        freeze: true,
        freeze_message: __("Comparing with Salary Structure..."),
        callback: function (r) {
            const plan = r.message;
            if (!plan) return;
            if (!current.length) {  // empty package: just take the structure's components
                slhrm_apply_plan(frm, plan, []);
                return;
            }
            if (!plan.add.length && !plan.remove.length) {
                frappe.msgprint({
                    title: title,
                    indicator: "green",
                    message: __("The package already has every component of {0}. Nothing to add or remove; amounts unchanged.",
                        [frm.doc.salary_structure]),
                });
                return;
            }
            slhrm_plan_dialog(frm, plan, title);
        },
    });
}


function slhrm_plan_dialog(frm, plan, title) {
    const esc = frappe.utils.escape_html;
    const money = v => format_currency(flt(v), frappe.defaults.get_default("currency"));
    const table = (rows, cols) => '<table class="table table-bordered table-sm slhrm-plan" style="font-size:12px; margin-bottom:10px;"><thead><tr>' +
        cols.map(c => '<th>' + c[0] + '</th>').join("") + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + cols.map(c => '<td' + (c[2] ? ' style="text-align:right; white-space:nowrap;"' : '') + '>' + c[1](r) + '</td>').join("") + '</tr>').join("") +
        '</tbody></table>';
    const amount_cell = r => r.override ? money(r.amount) : '<span class="text-muted">' + __("structure value") + '</span>';

    let html = '<div class="slhrm-plan-summary">';
    html += '<p><b>' + __("Kept (amounts unchanged)") + ' — ' + plan.keep.length + '</b></p>';
    html += plan.keep.length ? table(plan.keep, [[__("Component"), r => esc(r.salary_component)], [__("Type"), r => esc(r.salary_component_type || "")], [__("Amount"), amount_cell, 1]])
        : '<p class="text-muted">' + __("none") + '</p>';
    html += '<p><b>' + __("Added from {0}", [esc(frm.doc.salary_structure)]) + ' — ' + plan.add.length + '</b></p>';
    html += plan.add.length ? table(plan.add, [[__("Component"), r => esc(r.salary_component)], [__("Type"), r => esc(r.salary_component_type)],
        [__("Amount"), r => r.override ? money(r.amount) : '<span class="text-muted">' + __("structure formula") + (r.default_formula ? ': ' + esc(r.default_formula) : '') + '</span>', 1]])
        : '<p class="text-muted">' + __("none") + '</p>';
    html += '<p><b>' + __("Not in the structure — remove?") + ' — ' + plan.remove.length + '</b></p>';
    if (!plan.remove.length) html += '<p class="text-muted">' + __("none") + '</p>';
    html += '</div>';

    const fields = [{ fieldtype: "HTML", fieldname: "summary", options: html }];
    plan.remove.forEach((r, i) => fields.push({
        fieldtype: "Check", fieldname: "remove_" + i, default: 0,
        label: __("Remove {0} ({1})", [r.salary_component, r.override ? money(r.amount) : __("structure value")]),
    }));

    const d = new frappe.ui.Dialog({
        title: title,
        fields: fields,
        size: "large",
        primary_action_label: __("Apply"),
        primary_action(values) {
            const remove = plan.remove.filter((r, i) => values["remove_" + i]).map(r => r.salary_component);
            d.hide();
            slhrm_apply_plan(frm, plan, remove);
        },
    });
    d.$wrapper.addClass("slhrm-load-components-dialog");
    d.show();
}


function slhrm_apply_plan(frm, plan, remove) {
    remove.forEach(c => {
        (frm.doc.components || []).filter(r => r.salary_component === c)
            .forEach(r => frappe.model.clear_doc(r.doctype, r.name));
    });
    plan.add.forEach(comp => {
        const row = frm.add_child("components");
        ["salary_component", "salary_component_type", "amount", "override", "default_formula",
         "default_amount", "depends_on_payment_days"].forEach(k => { row[k] = comp[k]; });
    });
    frm.refresh_field("components");
    slhrm_calculate_package_totals(frm);
    if (plan.add.length || remove.length) slhrm_on_amount_change(frm);
    frappe.show_alert({
        message: __("{0} added, {1} removed, {2} kept unchanged.", [plan.add.length, remove.length, plan.keep.length]),
        indicator: "green",
    });
}


// ── Assignment history (read-only, from the server's onload) ──

function slhrm_render_history(frm) {
    const field = frm.fields_dict.assignment_history_html;
    if (!field) return;
    const rows = (frm.doc.__onload && frm.doc.__onload.assignment_history) || [];
    if (!rows.length) {
        field.$wrapper.html('<p class="text-muted">' + __("No Salary Structure Assignments yet.") + '</p>');
        return;
    }
    const esc = frappe.utils.escape_html;
    const color = { "In force today": "green", "Future": "blue", "Earlier period": "gray", "Cancelled": "red" };
    let html = '<table class="table table-bordered table-sm" style="font-size:12px;"><thead><tr>' +
        '<th>' + __("From Date") + '</th><th style="text-align:right;">' + __("Base") + '</th><th>' + __("Status") +
        '</th><th>' + __("Assignment") + '</th><th>' + __("Structure") + '</th></tr></thead><tbody>';
    rows.forEach(r => {
        html += '<tr><td>' + frappe.datetime.str_to_user(r.from_date) + '</td>' +
            '<td style="text-align:right; white-space:nowrap;">' + format_currency(r.base, frappe.defaults.get_default("currency")) + '</td>' +
            '<td><span class="indicator-pill ' + (color[r.status] || "gray") + '">' + esc(__(r.status)) + '</span></td>' +
            '<td><a href="/desk/salary-structure-assignment/' + encodeURIComponent(r.name) + '">' + esc(r.name) + '</a></td>' +
            '<td>' + esc(r.salary_structure || "") + (r.slhrm_managed ? "" : ' <span class="text-muted">(' + __("not from package") + ')</span>') + '</td></tr>';
    });
    field.$wrapper.html(html + '</tbody></table>');
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
