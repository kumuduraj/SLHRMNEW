// slhrm/public/js/device_sync.js — Biometric Device "Sync Now" (form button + list action) and status colours.
// The server queues one background job per device (slhrm.biometric.sync_now → run_sync_now: the agent reads THAT device
// once, read-only); each result arrives as realtime "slhrm_device_sync" for the requesting user.
frappe.provide("slhrm.device_sync");

slhrm.device_sync.EVENT = "slhrm_device_sync";
slhrm.device_sync.STATUS_COLOR = { Online: "green", Delayed: "orange", Offline: "red", Disabled: "gray" };

slhrm.device_sync.can_sync = function () {
	return frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");
};

slhrm.device_sync.start = function (devices, on_done) {
	// devices: {serial: device name}
	const serials = Object.keys(devices);
	const rows = {};
	const esc = frappe.utils.escape_html;
	const dialog = new frappe.ui.Dialog({ title: __("Sync Now"), size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }] });
	const cell = (v) => (v === undefined || v === null || v === "" ? "-" : esc(String(v)));
	const render = () => {
		let html = `<table class="table table-bordered table-sm slhrm-sync-result" style="font-size:12px;"><thead><tr>
			<th>${__("Device")}</th><th>${__("Connected")}</th><th>${__("Inserted")}</th><th>${__("Duplicates")}</th>
			<th>${__("Unmatched")}</th><th>${__("Clock drift (s)")}</th><th>${__("Read (s)")}</th><th>${__("Duration (s)")}</th>
			<th>${__("Status")}</th></tr></thead><tbody>`;
		serials.forEach((s) => {
			const r = rows[s] || {};
			const res = r.result || {};
			let status;
			if (r.refused) status = `<span class="text-muted">${esc(r.refused)}</span>`;
			else if (!r.result) status = `<span class="text-muted">${__("Running… (the agent reads the device; this can take a few minutes)")}</span>`;
			else {
				const st = res.status || (res.connected ? "Online" : "Offline");
				const color = slhrm.device_sync.STATUS_COLOR[st] || "gray";
				status = `<span class="indicator-pill ${color}">${esc(__(st))}</span>` +
					(res.error ? `<div class="text-danger" style="white-space:normal;margin-top:4px;">${esc(res.error)}</div>` : "");
			}
			html += `<tr data-serial="${esc(s)}"><td><b>${esc(devices[s] || s)}</b></td>
				<td>${r.result ? (res.connected ? __("Yes") : __("No")) : "-"}</td>
				<td>${cell(res.inserted)}</td><td>${cell(res.duplicate)}</td><td>${cell(res.unmatched)}</td>
				<td>${cell(res.drift_seconds)}</td><td>${cell(res.read_seconds)}</td><td>${cell(res.duration_seconds)}</td>
				<td class="slhrm-sync-status">${status}</td></tr>`;
		});
		dialog.fields_dict.body.$wrapper.html(html + "</tbody></table>");
	};
	const pending = new Set();
	const finish = () => { frappe.realtime.off(slhrm.device_sync.EVENT, handler); if (on_done) on_done(); };
	const handler = (data) => {
		if (!data || !pending.has(data.serial)) return;
		rows[data.serial] = { result: data.result || {} };
		pending.delete(data.serial);
		render();
		if (!pending.size) finish();
	};
	frappe.realtime.on(slhrm.device_sync.EVENT, handler);
	dialog.onhide = () => frappe.realtime.off(slhrm.device_sync.EVENT, handler);
	render();
	dialog.show();
	frappe.call({ method: "slhrm.biometric.sync_now", type: "POST", args: { devices: JSON.stringify(serials) } }).then((r) => {
		const m = r.message || {};
		(m.queued || []).forEach((s) => pending.add(s));
		(m.refused || []).forEach((x) => { rows[x.device] = { refused: x.message }; });
		render();
		if (!pending.size) finish();
	}, () => { frappe.realtime.off(slhrm.device_sync.EVENT, handler); dialog.hide(); });
	return dialog;
};
