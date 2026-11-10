// Device Users Other Branch — read-only list (slhrm.biometric.other_branch_rows).
frappe.query_reports["Device Users Other Branch"] = {
	filters: [{ fieldname: "device", label: __("Device"), fieldtype: "Link", options: "Biometric Device" }],
};
