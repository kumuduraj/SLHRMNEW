// Salary Structure Assignment - dynamic salary components, editable after submit
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

function _save_components(frm) {
    const components = [];
    frm.doc.slhrm_components.forEach(row => {
        components.push({
            salary_component: row.salary_component,
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
                frappe.show_alert({ message: __("Amounts saved"), indicator: "green" });
                frm.reload_doc();
            }
        },
    });
}

function _force_grid_editable(frm) {
    if (frm.doc.docstatus !== 1) return;
    const field = frm.fields_dict.slhrm_components;
    if (!field || !field.grid) return;

    const grid = field.grid;
    grid.editable = true;
    grid.grid_editable = true;

    // Override Frappe's docstatus check that blocks editing
    frm.enable_save = function () {};
    frm.save = function () { _save_components(frm); };

    // Make every row's Amount cell editable
    setTimeout(() => {
        grid.grid_rows.forEach(row => {
            if (row && row.grid_row) {
                row.grid_row.editable = true;
                // Enable the input fields
                const wrapper = row.grid_row.wrapper;
                if (wrapper) {
                    wrapper.find(".grid-input").removeAttr("disabled readonly");
                    wrapper.find("input, select, textarea").removeAttr("disabled readonly");
                    wrapper.find(".grid-row-check").removeAttr("disabled");
                }
            }
        });
    }, 300);

    // Add Save button
    frm.clear_custom_buttons();
    frm.add_custom_button(__("Save Amounts"), function () {
        _save_components(frm);
    }, __("Actions"));
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        _load_components(frm);

        if (frm.doc.docstatus === 1) {
            // Override the form's read-only state for child table editing
            frm.read_only = false;
            frm.allow_edit = true;

            setTimeout(() => _force_grid_editable(frm), 200);
            setTimeout(() => _force_grid_editable(frm), 500);
            setTimeout(() => _force_grid_editable(frm), 1000);
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
