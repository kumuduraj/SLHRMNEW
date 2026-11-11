// slhrm/doctype/slhrm_settings/slhrm_settings.js
frappe.ui.form.on("SLHRM Settings", {
	setup(frm) {
		["ot_component"].forEach((field) => {
			frm.set_query(field, () => ({ filters: { type: "Earning", disabled: 0 } }));
		});
		frm.set_query("no_pay_component", () => ({ filters: { type: "Deduction", disabled: 0 } }));
	},
});
