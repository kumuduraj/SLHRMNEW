// Salary Structure Assignment - auto-populate salary components & make editable after submit
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

function _make_grid_editable(frm) {
    if (frm.doc.docstatus !== 1) return;
    if (!frm.fields_dict.slhrm_components) return;

    const grid = frm.fields_dict.slhrm_components.grid;
    if (!grid) return;

    // Force grid editable
    grid.editable = true;
    grid.grid_editable = true;

    // Enable all rows
    if (grid.grid_rows) {
        grid.grid_rows.forEach(row => {
            if (row.grid_row) {
                row.grid_row.editable = true;
            }
        });
    }

    // Enable the Amount field in each row
    frm.doc.slhrm_components.forEach((comp, idx) => {
        const row_wrapper = grid.grid_rows[idx];
        if (row_wrapper && row_wrapper.grid_row) {
            row_wrapper.grid_row.editable = true;
        }
    });

    // Add Save button
    frm.page.clear_indicator();
    frm.add_custom_button(__("Save Changes"), function () {
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
                    frappe.show_alert({ message: __("Amounts saved successfully"), indicator: "green" });
                    frm.reload_doc();
                }
            },
        });
    }, __("Actions"));
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        _load_components(frm);

        if (frm.doc.docstatus === 1) {
            // Try to make grid editable after a short delay
            setTimeout(() => _make_grid_editable(frm), 200);
            setTimeout(() => _make_grid_editable(frm), 500);
            setTimeout(() => _make_grid_editable(frm), 1000);
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
