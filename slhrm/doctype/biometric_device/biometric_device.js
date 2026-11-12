// slhrm/doctype/biometric_device/biometric_device.js — connection status in the header, last read summary, Sync Now.
frappe.ui.form.on("Biometric Device", {
	refresh(frm) {
		if (frm.is_new()) return;
		const st = frm.doc.connection_status || "Offline";
		frm.page.set_indicator(__(st), slhrm.device_sync.STATUS_COLOR[st] || "gray");
		const parts = [];
		if (frm.doc.last_read_seconds || frm.doc.record_count) {
			parts.push(__("Last read {0} s, {1} records", [format_number(frm.doc.last_read_seconds || 0, null, 0),
				format_number(frm.doc.record_count || 0, null, 0)]));
		}
		parts.push(__("Last successful sync: {0}", [frm.doc.last_success_at ? frappe.datetime.comment_when(frm.doc.last_success_at) : __("never")]));
		if (frm.doc.last_success_at && frm.doc.clock_drift_seconds !== undefined && frm.doc.clock_drift_seconds !== null) {
			parts.push(__("Clock drift {0} s", [format_number(frm.doc.clock_drift_seconds, null, 0)]));
		}
		if (st !== "Online" && frm.doc.last_error) {
			parts.push(__("Last error: {0}", [frappe.utils.escape_html(frm.doc.last_error)]));
		}
		frm.set_intro(`<span class="slhrm-device-summary">${parts.join(" · ")}</span>`,
			{ Online: "green", Delayed: "orange", Offline: "red" }[st] || "blue");
		if (frm.doc.enabled && slhrm.device_sync.can_sync()) {
			frm.add_custom_button(__("Sync Now"), () => {
				slhrm.device_sync.start({ [frm.doc.name]: frm.doc.device_name }, () => frm.reload_doc());
			});
		}
	},
});
