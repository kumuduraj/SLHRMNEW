// SLHRM — Employee form (wired via hooks.doctype_js).
// "Issue Temporary Password": HR Manager / System Manager give a plain employee login a new random
// password (shown once, here only); the user must change it at the next login (slhrm/user_setup.py).
frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.user_id) return;
		if (!frappe.user.has_role("HR Manager") && !frappe.user.has_role("System Manager")) return;
		frm.add_custom_button(
			__("Issue Temporary Password"),
			() => {
				frappe.confirm(
					__("Give {0} a new temporary password? The current password stops working and the user must change it at the next login.", [frappe.utils.escape_html(frm.doc.user_id)]),
					() => {
						frappe
							.xcall("slhrm.user_setup.issue_temporary_password", { employee: frm.doc.name })
							.then((r) => {
								frappe.msgprint({
									title: __("Temporary password"),
									indicator: "green",
									message: __("User <b>{0}</b><br>Temporary password (shown only now): <code>{1}</code><br>The user must change it at the next login.", [
										frappe.utils.escape_html(r.user),
										frappe.utils.escape_html(r.password),
									]),
								});
							});
					}
				);
			},
			__("Actions")
		);
	},
});
