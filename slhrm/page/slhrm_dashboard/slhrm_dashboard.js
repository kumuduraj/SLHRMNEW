// slhrm/page/slhrm_dashboard/slhrm_dashboard.js — live, punch-based Attendance Dashboard (v0.4.5).
// All numbers come from slhrm.live_dashboard.get_dashboard (permitted branches only); auto-refresh every 2 min.
frappe.pages["slhrm-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Attendance Dashboard"), single_column: true });
	const esc = frappe.utils.escape_html;
	const REFRESH_MS = 2 * 60 * 1000;
	const branch = page.add_field({ fieldname: "branch", label: __("Branch (all permitted)"), fieldtype: "Link", options: "Branch",
		change: () => load() });
	page.set_primary_action(__("Refresh"), () => load(), "refresh");
	page.add_inner_button(__("Open Attendance Markers"), () => frappe.set_route("List", "Attendance Marker"));
	page.add_inner_button(__("Attendance Calendar"), () => frappe.set_route("attendance-calendar"));
	const $body = $(`<div class="slhrm-live" style="padding:6px 0;"></div>`).appendTo(page.main);
	$body.html(`<p class="text-muted">${__("Loading…")}</p>`);
	const STATUS = { Online: "green", Delayed: "orange", Offline: "red", Disabled: "gray" };
	const t = (s) => (s ? moment(s).format("DD-MM HH:mm") : "-");
	const card = (title, value, color, extra) => `<div class="slhrm-kpi" style="border:1px solid var(--border-color);border-radius:8px;
		padding:10px 12px;border-left:4px solid ${color};"><div class="text-muted small">${title}</div>
		<div style="font-size:22px;font-weight:600;">${value}</div>${extra || ""}</div>`;
	const table = (head, rows, empty) => `<div style="overflow-x:auto;"><table class="table table-sm table-bordered slhrm-live-t" style="font-size:12px;margin:0;">
		<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.join("") :
		`<tr><td colspan="${head.length}" class="text-muted">${empty}</td></tr>`}</tbody></table></div>`;
	const section = (title, inner) => `<div class="slhrm-live-sec" style="border:1px solid var(--border-color);border-radius:8px;padding:10px;">
		<div style="font-weight:600;margin-bottom:6px;">${title}</div>${inner}</div>`;

	function load() {
		frappe.call({ method: "slhrm.live_dashboard.get_dashboard", args: { branch: branch.get_value() || "" } }).then((r) => render(r.message));
	}

	function render(d) {
		const c = d.counts;
		let html = `<style>
			.slhrm-live-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:8px; margin-bottom:10px; }
			.slhrm-live-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:10px; margin-bottom:10px; }
			.slhrm-live-t td, .slhrm-live-t th { white-space: nowrap; }
			@media (max-width: 480px) { .slhrm-live-grid { grid-template-columns: 1fr; } }
			</style>
			<div class="small text-muted" style="margin-bottom:6px;">${__("Updated {0} · branches: {1} · auto-refresh every 2 min",
				[moment(d.now).format("HH:mm:ss"), esc(d.branches.join(", "))])}</div>
			<div class="slhrm-live-kpis">` +
			card(__("Punched today"), `${c.punched} / ${c.employees}`, "#2f9e44") +
			card(__("Currently on duty"), c.on_duty, "#1971c2") +
			card(__("Not punched yet"), c.not_punched, "#868e96", c.not_arrived ? `<div class="small" style="color:#e03131;">${__("{0} late / not arrived", [c.not_arrived])}</div>` : "") +
			card(__("Late arrivals"), c.late, "#e8590c") +
			card(__("Unmatched punches today"), `<a href="/desk/query-report/Unmatched Device Users">${c.unmatched}</a>`, "#e03131") +
			`</div><div class="slhrm-live-grid">`;
		html += section(__("Currently on duty"), table([__("Employee"), __("IN"), __("Shift"), __("Hours so far")], d.on_duty.map((x) =>
			`<tr><td>${esc(x.employee_name)} <span class="text-muted">${esc(x.branch)}</span></td><td>${t(x.in_time)}${x.overnight ? ` <span class="badge" title="${__("started yesterday")}">${__("night")}</span>` : ""}</td>
			<td>${esc(x.shift || "-")}</td><td>${x.hours}</td></tr>`), __("Nobody on duty.")));
		html += section(__("Not punched yet"), table([__("Employee"), __("Shift"), ""], d.not_punched.map((x) =>
			`<tr class="${x.not_arrived ? "slhrm-not-arrived" : ""}"><td>${esc(x.employee_name)} <span class="text-muted">${esc(x.branch)}</span></td>
			<td>${esc(x.shift || "-")}</td><td>${x.not_arrived ? `<span class="indicator-pill red">${__("late / not arrived")}</span>` : ""}</td></tr>`),
			__("Everyone has punched.")));
		html += section(__("Late arrivals (shift assigned)"), table([__("Employee"), __("Shift start"), __("First punch"), __("Min late")], d.late.map((x) =>
			`<tr><td>${esc(x.employee_name)}</td><td>${t(x.shift_start)}</td><td>${t(x.first)}</td><td><b>${x.minutes}</b></td></tr>`),
			__("No late arrivals.")));
		html += section(__("Devices"), d.devices.map((x) => `<div style="display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--border-color);">
			<div><a href="/desk/biometric-device/${encodeURIComponent(x.name)}"><b>${esc(x.device_name)}</b></a>
			<div class="small text-muted">${__("Last successful sync")}: ${t(x.last_success_at)} · ${__("next read")}: ${t(x.next_read)} · ${__("every {0} min", [x.interval])}</div></div>
			<div><span class="indicator-pill ${STATUS[x.status] || "gray"} slhrm-dev-status">${__(x.status)}</span></div></div>`).join("") ||
			`<div class="text-muted">${__("No device serves these branches.")}</div>`);
		html += section(__("Yesterday ({0})", [moment(d.yesterday_date).format("DD-MM-YYYY")]), table([__("Branch"), __("Marker"), "P", "A", "NP", __("Missing")],
			d.yesterday.map((x) => `<tr><td>${esc(x.branch)}</td><td>${x.marker ? `<a href="/desk/attendance-marker/${encodeURIComponent(x.marker)}">${__(x.status)}</a>` :
				`<span class="indicator-pill red">${__("None")}</span>`}</td><td>${x.P}</td><td>${x.A}</td><td>${x.NP}</td><td>${x.missing || ""}</td></tr>`), ""));
		html += section(__("This month"), table([__("Branch"), __("Completed"), __("OT hrs"), __("Short hrs")], d.month.map((x) =>
			`<tr><td>${esc(x.branch)}</td><td><a class="slhrm-month-link" data-branch="${esc(x.branch)}">${x.completed} / ${x.working}</a></td>
			<td>${x.ot_hours}</td><td>${x.short_hours}</td></tr>`), ""));
		html += "</div>";
		$body.html(html);
		$body.find(".slhrm-month-link").css("cursor", "pointer").on("click", function () {
			frappe.route_options = { branch: $(this).data("branch") };
			frappe.set_route("attendance-calendar");
		});
	}

	load();
	setInterval(() => { if ($(wrapper).is(":visible")) load(); }, REFRESH_MS);
};
