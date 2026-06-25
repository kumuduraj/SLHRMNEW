// Salary Structure Assignment - auto-populate salary components
frappe.provide("slhrm.ssa");

frappe.ui.form.on("Salary Structure Assignment", {
    salary_structure(frm) {
        if (!frm.doc.salary_structure) {
            frm.clear_table("slhrm_components");
            frm.refresh_field("slhrm_components");
            return;
        }

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
    },
});
