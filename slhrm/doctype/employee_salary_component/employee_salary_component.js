// Copyright (c) 2024, SLHRM and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Salary Component", {
    refresh(frm) {
        if (frm.doc.docstatus === 0 && !frm.is_new()) {
            // Show Recalculate button for saved but not submitted (not applicable here since not submittable)
        }
    },
});
