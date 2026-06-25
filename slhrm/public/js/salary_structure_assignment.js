// Salary Structure Assignment - editable salary components table
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

function _force_editable(frm) {
    if (frm.doc.docstatus !== 1) return;
    const field = frm.fields_dict.slhrm_components;
    if (!field || !field.grid) return;

    const grid = field.grid;
    grid.editable = true;
    grid.grid_editable = true;

    // Remove disabled/readonly from all inputs in the grid
    setTimeout(() => {
        field.$wrapper.find("input, select, textarea").removeAttr("disabled readonly");
        field.$wrapper.find(".grid-input").removeAttr("disabled readonly");
        field.$wrapper.find(".btn-open").show();
    }, 100);
    setTimeout(() => {
        field.$wrapper.find("input, select, textarea").removeAttr("disabled readonly");
    }, 300);
    setTimeout(() => {
        field.$wrapper.find("input, select, textarea").removeAttr("disabled readonly");
    }, 600);
}

function _save_amounts(frm) {
    const components = [];
    frm.doc.slhrm_components.forEach(row => {
        components.push({
            salary_component: row.salary_component,
            component_type: row.component_type,
            abbreviation: row.abbreviation,
            formula: row.formula,
            amount: flt(row.amount) || 0,
        });
    });

    frappe.call({
        method: "slhrm.api.update_ssa_components",
        args: { ssa_name: frm.doc.name, components: components },
        freeze: true,
        freeze_message: __("Saving amounts..."),
        callback(r) {
            if (r.message) {
                frappe.show_alert({ message: __("Amounts saved successfully"), indicator: "green" });
                frm.reload_doc();
            }
        },
    });
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        _load_components(frm);

        if (frm.doc.docstatus === 1) {
            _force_editable(frm);

            frm.add_custom_button(__("Save Amounts"), function () {
                _save_amounts(frm);
            }, __("Actions"));
        }
    },
    salary_structure(frm) {
        if (!frm.doc.salary_structure) {
            frm.clear_table("slhrm_components");
            frm.refresh_field("slhrm_components");
            return;
        }
        _load_components(frm);
    },
});

frappe.ui.form.on("Salary Structure Assignment Component", {
    amount(frm, cdt, cdn) {
        // Auto-recalculate when amount changes
    },
});
