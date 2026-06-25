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

function _recalc_in_dialog(dlg) {
    const comps = dlg.get_values().components || [];
    let bs = 0, ba = 0, va = 0;
    comps.forEach(c => {
        if (c.abbreviation === "BS") bs = flt(c.amount) || 0;
        else if (c.abbreviation === "BA") ba = flt(c.amount) || 0;
        else if (c.abbreviation === "VA") va = flt(c.amount) || 0;
    });

    const comp_vals = { "BS": bs, "BA": ba, "VA": va };

    comps.forEach(c => {
        if (c.formula && c.formula.trim() && !c.amount) {
            let expr = c.formula;
            ["BS", "BA", "VA"].forEach(a => {
                const re = new RegExp("\\b" + a + "\\b", "g");
                expr = expr.replace(re, String(comp_vals[a] || 0));
            });
            try {
                const result = Function('"use strict"; return (' + expr + ')')();
                c.amount = isFinite(result) ? Math.round(result * 100) / 100 : 0;
            } catch (e) {
                c.amount = 0;
            }
        }
        comp_vals[c.abbreviation] = flt(c.amount) || 0;
    });

    // Update the table in dialog
    const table = dlg.fields_dict.components.grid;
    table.refresh();
}

function _open_edit_dialog(frm) {
    const components = (frm.doc.slhrm_components || []).map(c => ({
        salary_component: c.salary_component,
        component_type: c.component_type,
        abbreviation: c.abbreviation,
        formula: c.formula,
        amount: c.amount || 0,
        editable: !c.formula || !c.formula.trim(),
    }));

    const fields = components.map((c, i) => ({
        fieldname: "comp_" + i,
        label: c.salary_component + " (" + c.abbreviation + ")" + (c.formula ? " [" + c.formula + "]" : ""),
        fieldtype: "Currency",
        default: c.amount,
        read_only: !!c.formula,
        description: c.formula ? __("Auto-calculated: ") + c.formula : "",
    }));

    // Add Base field
    fields.unshift({
        fieldname: "base_field",
        label: __("Base (Basic Salary)"),
        fieldtype: "Currency",
        default: frm.doc.base || 0,
    });

    const d = new frappe.ui.Dialog({
        title: __("Edit Salary Components - ") + frm.doc.name,
        fields: fields,
        primary_action_label: __("Save"),
        primary_action(values) {
            const components = [];
            frm.doc.slhrm_components.forEach((c, i) => {
                const key = "comp_" + i;
                let amt = flt(values[key]) || 0;

                // Re-evaluate formula if it has one
                if (c.formula && c.formula.trim()) {
                    let bs_val = flt(values.base_field) || 0;
                    let ba_val = flt(values["comp_" + frm.doc.slhrm_components.findIndex(
                        x => x.abbreviation === "BA")]) || 0;
                    let va_val = flt(values["comp_" + frm.doc.slhrm_components.findIndex(
                        x => x.abbreviation === "VA")]) || 0;

                    let expr = c.formula;
                    ["BS", "BA", "VA"].forEach(a => {
                        const re = new RegExp("\\b" + a + "\\b", "g");
                        const v = a === "BS" ? bs_val : a === "BA" ? ba_val : va_val;
                        expr = expr.replace(re, String(v));
                    });
                    try {
                        const result = Function('"use strict"; return (' + expr + ')')();
                        amt = isFinite(result) ? Math.round(result * 100) / 100 : 0;
                    } catch (e) { /* keep manual amount */ }
                }

                components.push({
                    salary_component: c.salary_component,
                    amount: amt,
                });
            });

            frappe.call({
                method: "slhrm.api.update_ssa_components",
                args: { ssa_name: frm.doc.name, components: components },
                freeze: true,
                freeze_message: __("Saving amounts..."),
                callback(r) {
                    if (r.message) {
                        frappe.show_alert({ message: __("Amounts saved"), indicator: "green" });
                        frm.reload_doc();
                    }
                },
            });
            d.hide();
        },
    });

    // Add Recalculate button
    d.add_custom_button(__("Recalculate"), function () {
        const vals = d.get_values();
        let bs = flt(vals.base_field) || 0;
        let ba = flt(vals["comp_" + frm.doc.slhrm_components.findIndex(x => x.abbreviation === "BA")]) || 0;
        let va = flt(vals["comp_" + frm.doc.slhrm_components.findIndex(x => x.abbreviation === "VA")]) || 0;
        const cv = { "BS": bs, "BA": ba, "VA": va };

        frm.doc.slhrm_components.forEach((c, i) => {
            if (c.formula && c.formula.trim()) {
                let expr = c.formula;
                ["BS", "BA", "VA"].forEach(a => {
                    const re = new RegExp("\\b" + a + "\\b", "g");
                    expr = expr.replace(re, String(cv[a] || 0));
                });
                try {
                    const result = Function('"use strict"; return (' + expr + ')')();
                    d.set_value("comp_" + i, isFinite(result) ? Math.round(result * 100) / 100 : 0);
                } catch (e) {}
            }
        });
    });

    d.show();
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        _load_components(frm);

        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Edit Amounts"), function () {
                _open_edit_dialog(frm);
            }, __("Actions"));
        }
    },
    salary_structure(frm) {
        if (!frm.doc.salary_structure) {
            frm.clear_table("slhrm_components");
            frm.refresh_field("slhrm_components");
            frm.set_value("base", 0);
            frm.set_value("ctc", 0);
            return;
        }
        _load_components(frm);
    },
});
