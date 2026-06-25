// Salary Structure Assignment - link to Employee Salary Components
frappe.provide("slhrm.ssa");

function _render_components_link(frm) {
    if (!frm.doc.employee) return;
    if (frm.doc.docstatus !== 1) return;

    const html = `
        <div style="padding: 10px 0;">
            <a class="btn btn-xs btn-primary" href="/app/employee-salary-component?employee=${frm.doc.employee}">
                ${__("Open Salary Components")} →
            </a>
            <span style="margin-left: 10px; color: gray; font-size: 12px;">
                ${__("Edit amounts directly — no submit lock")}
            </span>
        </div>
    `;
    frm.fields_dict.slhrm_components_html.$wrapper.html(html);
}

frappe.ui.form.on("Salary Structure Assignment", {
    refresh(frm) {
        _render_components_link(frm);

        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Edit Salary Components"), function () {
                frappe.set_route("List", "Employee Salary Component", {
                    employee: frm.doc.employee,
                });
            }, __("Actions"));

            frm.add_custom_button(__("Sync Components"), function () {
                frappe.call({
                    method: "slhrm.api.sync_employee_salary_components",
                    args: { ssa_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Syncing components..."),
                    callback(r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: __("Created: {0}, Updated: {1}",
                                    [r.message.created, r.message.updated]),
                                indicator: "green",
                            });
                        }
                    },
                });
            }, __("Actions"));
        }
    },
});
