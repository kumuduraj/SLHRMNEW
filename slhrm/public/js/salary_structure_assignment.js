// Salary Structure Assignment — editable salary components
frappe.provide("slhrm.ssa");

function _load_components(frm) {
    if (!frm.doc.salary_structure) return;
    if (frm.doc.slhrm_components && frm.doc.slhrm_components.length > 0 && frm.doc.slhrm_components.some(c => c.salary_component)) return;

    frappe.call({
        method: "slhrm.api.get_salary_structure_components",
        args: { salary_structure: frm.doc.salary_structure },
        freeze: true,
        freeze_message: __("Loading salary components..."),
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

function _render_editable_table(frm) {
    // Fetch current amounts from Employee Salary Component
    frappe.call({
        method: "slhrm.api.get_employee_salary_components",
        args: { employee: frm.doc.employee },
        callback(r) {
            const components = r.message || [];
            if (!components.length) {
                frm.fields_dict.slhrm_components_html.$wrapper.html(
                    '<p style="color:#999;margin-top:10px;">No salary components found. Please save this SSA first to sync components.</p>'
                );
                return;
            }

            let html = '<table class="table table-bordered table-sm" style="margin-top:10px;" id="slhrm-editable-components">';
            html += '<thead><tr style="background:#f5f5f5;">';
            html += '<th style="width:5%;">No.</th>';
            html += '<th style="width:25%;">Salary Component</th>';
            html += '<th style="width:10%;">Type</th>';
            html += '<th style="width:8%;">Abbr</th>';
            html += '<th style="width:25%;">Formula</th>';
            html += '<th style="width:17%;">Amount</th>';
            html += '</tr></thead><tbody>';

            components.forEach((comp, idx) => {
                const color = comp.component_type === 'Earning' ? '#2196F3' : '#f44336';
                html += `<tr>`;
                html += `<td>${idx + 1}</td>`;
                html += `<td><strong>${comp.salary_component}</strong></td>`;
                html += `<td><span style="color:${color};font-weight:600;">${comp.component_type}</span></td>`;
                html += `<td>${comp.abbreviation}</td>`;
                html += `<td style="font-size:12px;">${comp.formula || ''}</td>`;
                html += `<td><input type="number" class="form-control form-control-sm slhrm-amount-input" `;
                html += `data-component="${comp.salary_component}" `;
                html += `data-abbreviation="${comp.abbreviation}" `;
                html += `data-type="${comp.component_type}" `;
                html += `data-formula="${comp.formula || ''}" `;
                html += `value="${comp.amount || 0}" style="text-align:right;font-weight:600;"></td>`;
                html += `</tr>`;
            });

            html += '</tbody></table>';
            frm.fields_dict.slhrm_components_html.$wrapper.html(html);
        },
    });
}

function _save_amounts(frm) {
    const inputs = document.querySelectorAll('.slhrm-amount-input');
    const components = [];
    inputs.forEach(input => {
        components.push({
            salary_component: input.dataset.component,
            component_type: input.dataset.type,
            abbreviation: input.dataset.abbreviation,
            formula: input.dataset.formula,
            amount: flt(input.value) || 0,
        });
    });

    if (!components.length) {
        frappe.msgprint(__("No components to save"));
        return;
    }

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
        if (frm.doc.docstatus === 0) {
            // Draft: auto-populate child table from salary structure
            _load_components(frm);
        } else if (frm.doc.docstatus === 1) {
            // Submitted: show editable HTML table
            _render_editable_table(frm);

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
        if (frm.doc.docstatus === 0) {
            _load_components(frm);
        }
    },
});
