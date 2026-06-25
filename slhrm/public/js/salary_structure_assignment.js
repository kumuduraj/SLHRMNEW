// Salary Structure Assignment - auto-populate salary components & calculate totals
frappe.provide("slhrm.ssa");

function _load_components(frm) {
    if (!frm.doc.salary_structure) return;
    if (frm.doc.slhrm_components && frm.doc.slhrm_components.some(c => c.salary_component)) return;

    frappe.call({
        method: "slhrm.api.get_salary_structure_components",
        args: { salary_structure: frm.doc.salary_structure },
        callback(r) {
            if (!r.message) return;
            frm.clear_table("slhrm_components");
            r.message.forEach(comp => {
                frm.add_child("slhrm_components", {
                    salary_component: comp.salary_component,
                    component_type: comp.component_type,
                    abbreviation: comp.abbreviation,
                    formula: comp.formula,
                    amount: 0,
                });
            });
            frm.refresh_field("slhrm_components");
        },
    });
}

function _recalc_totals(frm) {
    if (!frm.doc.slhrm_components) return;

    let bs = 0, ba = 0, va = 0;

    frm.doc.slhrm_components.forEach(row => {
        if (row.amount && row.amount > 0) {
            const abbr = (row.abbreviation || "").toUpperCase();
            if (abbr === "BS") bs = flt(row.amount);
            else if (abbr === "BA") ba = flt(row.amount);
            else if (abbr === "VA") va = flt(row.amount);
        }
    });

    const comp_vals = { "BS": bs, "BA": ba, "VA": va, "base": bs, "basic": bs };

    frm.doc.slhrm_components.forEach(row => {
        if (row.formula && row.formula.trim()) {
            let expr = row.formula;
            ["BS", "BA", "VA"].forEach(a => {
                const re = new RegExp("\\b" + a + "\\b", "g");
                expr = expr.replace(re, String(comp_vals[a] || 0));
            });
            try {
                const result = Function('"use strict"; return (' + expr + ')')();
                row.amount = isFinite(result) ? Math.round(result * 100) / 100 : 0;
            } catch (e) {
                row.amount = 0;
            }
            comp_vals[row.abbreviation] = flt(row.amount);
            comp_vals[row.salary_component] = flt(row.amount);
        }
    });

    frm.refresh_field("slhrm_components");

    const base_val = bs || 0;
    frm.set_value("base", base_val);

    let total_earnings = 0;
    let total_deductions = 0;
    frm.doc.slhrm_components.forEach(row => {
        const amt = flt(row.amount) || 0;
        if (row.component_type === "Earning") total_earnings += amt;
        else if (row.component_type === "Deduction") total_deductions += amt;
    });

    frm.set_value("total_cost_to_company", total_earnings);
}

function _save_amounts(frm) {
    const components = [];
    frm.doc.slhrm_components.forEach(row => {
        components.push({
            salary_component: row.salary_component,
            amount: flt(row.amount) || 0,
        });
    });

    frappe.call({
        method: "slhrm.api.update_ssa_components",
        args: {
            ssa_name: frm.doc.name,
            components: components,
        },
        freeze: true,
        freeze_message: __("Saving amounts..."),
        callback(r) {
            if (r.message) {
                frappe.show_alert({
                    message: __("Amounts saved successfully"),
                    indicator: "green",
                });
                frm.reload_doc();
            }
        },
    });
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        _load_components(frm);
        setTimeout(() => _recalc_totals(frm), 500);

        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Update Amounts"), function () {
                _save_amounts(frm);
            }, __("Actions"));

            frm.add_custom_button(__("Recalculate"), function () {
                _recalc_totals(frm);
                frappe.show_alert({
                    message: __("Totals recalculated. Click 'Update Amounts' to save."),
                    indicator: "orange",
                });
            }, __("Actions"));
        }
    },
    salary_structure(frm) {
        if (!frm.doc.salary_structure) {
            frm.clear_table("slhrm_components");
            frm.refresh_field("slhrm_components");
            frm.set_value("base", 0);
            frm.set_value("total_cost_to_company", 0);
            return;
        }
        _load_components(frm);
    },
});

frappe.ui.form.on("Salary Structure Assignment Component", {
    amount(frm, cdt, cdn) {
        _recalc_totals(frm);
    },
});
