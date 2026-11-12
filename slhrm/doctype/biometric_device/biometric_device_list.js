// slhrm/doctype/biometric_device/biometric_device_list.js — Online / Delayed / Offline pill (replaces Enabled), Sync Now.
frappe.listview_settings["Biometric Device"] = {
	add_fields: ["connection_status", "enabled", "device_name", "last_success_at"],
	get_indicator(doc) {
		const st = doc.connection_status || "Offline";
		return [__(st), (slhrm.device_sync && slhrm.device_sync.STATUS_COLOR[st]) || "gray", "connection_status,=," + st];
	},
	onload(listview) {
		if (!slhrm.device_sync.can_sync()) return;
		listview.page.add_actions_menu_item(__("Sync Now"), () => {
			const sel = listview.get_checked_items();
			if (!sel.length) {
				frappe.msgprint(__("Select one or more devices."));
				return;
			}
			const devices = {};
			sel.forEach((d) => { devices[d.name] = d.device_name || d.name; });
			slhrm.device_sync.start(devices, () => listview.refresh());
		}, false);
	},
};
