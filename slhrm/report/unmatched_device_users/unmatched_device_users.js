// Unmatched Device Users — "Map to Employee" writes Employee.slhrm_biometric_device_id via
// slhrm.biometric.map_device_user; that employee's Unmatched punches re-match on the server.
frappe.query_reports["Unmatched Device Users"] = {
	filters: [
		{ fieldname: "device", label: __("Device"), fieldtype: "Link", options: "Biometric Device" },
	],

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "action" && data && data.device_user_id) {
			const esc = frappe.utils.escape_html;
			return `<button class="btn btn-xs btn-primary slhrm-map-btn"
				data-serial="${esc(data.device_serial)}" data-uid="${esc(data.device_user_id)}"
				data-name="${esc(data.user_name || "")}" data-emp="${esc(data.suggested_employee || "")}"
				data-device="${esc(data.device_name || "")}">${__("Map to Employee")}</button>`;
		}
		return default_formatter(value, row, column, data);
	},

	onload(report) {
		$(report.page.wrapper).on("click", ".slhrm-map-btn", function (e) {
			e.preventDefault();
			e.stopPropagation();
			const b = $(this).data();
			slhrm_map_device_user(report, {
				serial: String(b.serial), uid: String(b.uid), name: b.name, emp: b.emp, device: b.device,
			});
		});
	},
};

function slhrm_map_device_user(report, row) {
	const d = new frappe.ui.Dialog({
		title: __("Map device user {0} ({1})", [row.uid, row.name || __("no name")]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__("Device")}: ${frappe.utils.escape_html(row.device)}</p>`,
			},
			{
				fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee", reqd: 1,
				default: row.emp || undefined, get_query: () => ({ filters: { status: "Active" } }),
			},
		],
		primary_action_label: __("Map"),
		primary_action(values) {
			const call = (replace) =>
				frappe.call({
					method: "slhrm.biometric.map_device_user",
					args: { device_serial: row.serial, device_user_id: row.uid, employee: values.employee, replace: replace ? 1 : 0 },
					freeze: true,
				}).then((r) => {
					const m = r.message || {};
					if (m.refused) {
						frappe.msgprint({ title: __("Not mapped"), message: frappe.utils.escape_html(m.refused), indicator: "red" });
						return;
					}
					if (m.confirm) {
						frappe.confirm(m.confirm, () => call(true));
						return;
					}
					d.hide();
					frappe.show_alert({ message: __("Mapped to {0}: {1} punch(es) matched", [m.employee, m.matched]), indicator: "green" });
					report.refresh();
				});
			call(false);
		},
	});
	d.show();
}
