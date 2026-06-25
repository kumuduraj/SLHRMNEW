// Salary Structure Assignment — link to editable Employee Salary Component
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

function _sync_components(frm) {
    frappe.call({
        method: "slhrm.api.sync_employee_salary_components",
        args: { ssa_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Syncing salary components..."),
        callback(r) {
            if (r.message) {
                frappe.show_alert({
                    message: __("Synced {1} components to Employee Salary Component", [r.message.created + r.message.updated]),
                    indicator: "green"
                });
            }
        },
    });
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            // Show sync button
            frm.add_custom_button(__("Sync Components"), function () {
                _sync_components(frm);
            }, __("Actions"));

            // Show link to editable Employee Salary Component
            if (frm.doc.employee) {
                frm.add_custom_button(__("Edit Amounts"), function () {
                    frappe.set_route("List", "Employee Salary Component", {
                        employee: frm.doc.employee,
                    });
                }, __("Actions"));

                // Show read-only summary of current amounts
                frappe.call({
                    method: "slhrm.api.get_employee_salary_components",
                    args: { employee: frm.doc.employee },
                    callback(r) {
                        if (r.message && r.message.length) {
                            let html = '<table class="table table-bordered table-sm" style="margin-top:10px;">';
                            html += '<tr style="background:#f5f5f5;"><th>Component</th><th>Type</th><th>Abbr</th><th style="text-align:right;">Amount</th></tr>';
                            r.message.forEach(row => {
                                const color = row.component_type === 'Earning' ? '#2196F3' : '#f44336';
                                html += `<tr>
                                    <td>${row.salary_component}</td>
                                    <td><span style="color:${color};font-weight:600;">${row.component_type}</span></td>
                                    <td>${row.abbreviation}</td>
                                    <td style="text-align:right;font-weight:600;">${format_currency(row.amount)}</td>
                                </tr>`;
                            });
                            html += '</table>';
                            frm.fields_dict.slhrm_components_html.$wrapper.html(html);
                        } else {
                            frm.fields_dict.slhrm_components_html.$wrapper.html(
                                '<p style="color:#999;margin-top:10px;">No salary components found. Click "Sync Components" to populate.</p>'
                            );
                        }
                    },
                });
            }
        } else {
            // Draft: auto-populate child table
            _load_components(frm);
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
