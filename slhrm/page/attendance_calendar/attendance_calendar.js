// slhrm/page/attendance_calendar/attendance_calendar.js — month completion per branch + employee register (v0.4.4).
// Read-only; all numbers come from slhrm.attendance_calendar.get_calendar (existing markers / rows / punches).
frappe.pages["attendance-calendar"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Attendance Calendar"), single_column: true });
	const prev = frappe.datetime.add_months(frappe.datetime.get_today(), -1);
	const months = [];
	for (let i = 0; i < 18; i++) {
		const d = frappe.datetime.add_months(frappe.datetime.get_today(), -i);
		months.push({ value: d.slice(0, 7), label: moment(d).format("MMMM YYYY") });
	}
	const state = { only_attention: 0 };
	const branch = page.add_field({ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch", change: () => load() });
	const month = page.add_field({ fieldname: "month", label: __("Month"), fieldtype: "Select", options: months, default: prev.slice(0, 7),
		change: () => load() });
	month.set_value(prev.slice(0, 7));
	wrapper.slhrm_branch = branch;  // the dashboard opens the calendar with frappe.route_options = {branch}
	page.set_secondary_action(__("Export register (Excel)"), () => {
		if (!branch.get_value()) return frappe.msgprint(__("Select a Branch."));
		window.open(`/api/method/slhrm.attendance_calendar.export_register?branch=${encodeURIComponent(branch.get_value())}` +
			`&month=${encodeURIComponent(month.get_value())}&only_attention=${state.only_attention}`);
	});
	const $body = $(`<div class="slhrm-cal" style="padding:8px 0;"></div>`).appendTo(page.main);
	$body.html(`<p class="text-muted">${__("Select a Branch.")}</p>`);
	const esc = frappe.utils.escape_html;
	if (frappe.route_options && frappe.route_options.branch) {
		const b = frappe.route_options.branch;
		frappe.route_options = null;
		setTimeout(() => branch.set_value(b), 0);
	}
	const COLOR = { green: ["#e6f4ea", "#2f9e44"], orange: ["#fff4e5", "#e8590c"], red: ["#fdecea", "#e03131"], grey: ["#f1f3f5", "#868e96"] };

	function load() {
		if (!branch.get_value() || !month.get_value()) return;
		frappe.call({ method: "slhrm.attendance_calendar.get_calendar", args: { branch: branch.get_value(), month: month.get_value() } })
			.then((r) => { state.data = r.message; render(); });
	}

	function open_day(x) {
		if (x.marker) return frappe.set_route("Form", "Attendance Marker", x.marker);
		if (x.color === "red") frappe.new_doc("Attendance Marker", { date: x.date, branch: branch.get_value() });
	}

	function render() {
		const data = state.data;
		const h = data.header;
		let html = `<style>
			.slhrm-cal-grid { display:grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap:4px; }
			.slhrm-cal-day { border:1px solid var(--border-color); border-radius:6px; padding:4px 6px; min-height:64px; cursor:default; font-size:11px; }
			.slhrm-cal-day.click { cursor:pointer; }
			.slhrm-cal-head { font-size:11px; color:var(--text-muted); text-align:center; }
			.slhrm-reg td, .slhrm-reg th { white-space:nowrap; text-align:center; padding:2px 4px !important; font-size:11px; }
			.slhrm-reg td.n, .slhrm-reg th.n { text-align:left; position:sticky; left:0; background:var(--card-bg, #fff); z-index:1; }
			.slhrm-reg td.warn { color:#e8590c; font-weight:600; }
			.slhrm-reg td.pend { background: #fdecea; }
			</style>
			<div class="slhrm-cal-summary" style="margin-bottom:8px;"><b>${__("Completed {0} / {1} working days", [h.completed, h.working])}</b>
			— ${esc(data.branch)}, ${esc(data.label)}</div>`;
		if (h.pending.length) {
			html += `<div class="slhrm-cal-pending" style="margin-bottom:8px;">${__("Pending days")}: ` + h.pending.map((p) =>
				`<a class="slhrm-cal-pend indicator-pill ${p.color === "red" ? "red" : "orange"}" data-date="${p.date}" style="margin:2px;cursor:pointer;">${
					moment(p.date).format("DD MMM")} — ${esc(p.reason)}</a>`).join("") + "</div>";
		}
		html += `<div class="slhrm-cal-grid">` + ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => `<div class="slhrm-cal-head">${__(d)}</div>`).join("");
		for (let i = 0; i < data.days[0].weekday; i++) html += "<div></div>";
		data.days.forEach((x) => {
			const [bg, fg] = COLOR[x.color];
			const click = x.marker || x.color === "red";
			const counts = x.marker ? `P ${x.P} · A ${x.A} · NP ${x.NP}` : "";
			const extra = (x.flagged ? `⚠ ${x.flagged} ` : "") + (x.unmatched ? `· ${__("{0} unmatched", [x.unmatched])}` : "");
			const label = x.color === "red" ? __("Create marker") : x.color === "grey" ? (x.holiday ? __("Holiday") : "") :
				x.marker_status === "Draft" ? __("Draft") : "";
			html += `<div class="slhrm-cal-day ${click ? "click" : ""}" data-date="${x.date}" data-color="${x.color}"
				style="background:${bg};border-color:${fg};" title="${esc(x.reason || "")}">
				<div style="font-weight:600;color:${fg};">${x.day} <span style="font-weight:400;">${esc(label)}</span></div>
				<div>${counts}</div><div style="color:#e8590c;">${esc(extra)}</div></div>`;
		});
		html += `</div><div style="margin:6px 0 14px;" class="small text-muted">` +
			Object.entries({ green: __("submitted, clean"), orange: __("draft, or flagged / unmatched"), red: __("working day, no marker"),
				grey: __("holiday / future") }).map(([k, v]) => `<span style="display:inline-block;width:10px;height:10px;background:${COLOR[k][0]};
				border:1px solid ${COLOR[k][1]};margin:0 4px 0 10px;"></span>${v}`).join("") + "</div>";
		// register
		const rows = data.register.filter((r) => !state.only_attention || r.attention);
		html += `<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;"><b>${__("Employee register")}</b>
			<label class="small" style="margin:0;"><input type="checkbox" class="slhrm-reg-only" ${state.only_attention ? "checked" : ""}>
			${__("only employees with pending / flagged days")}</label>
			<span class="small text-muted">${__("P / A / NP / L / SL; ⚠ flagged; blank = no submitted marker")}</span></div>
			<div style="overflow-x:auto;"><table class="table table-bordered table-sm slhrm-reg"><thead><tr><th class="n">${__("Employee")}</th>` +
			data.days.map((x) => `<th>${x.day}</th>`).join("") + `<th>P</th><th>A</th><th>NP</th><th>${__("OT hrs")}</th><th>${__("Short hrs")}</th></tr></thead><tbody>`;
		rows.forEach((r) => {
			html += `<tr data-employee="${esc(r.employee)}"><td class="n"><b>${esc(r.employee_name)}</b> <span class="text-muted">${esc(r.employee_number)}</span></td>` +
				data.days.map((x) => {
					const c = r.cells[x.date];
					const pend = !c.text && !c.holiday && !x.future;
					return `<td class="${c.flags.length ? "warn" : ""} ${pend ? "pend" : ""}" data-date="${x.date}" title="${esc((c.code || "") + (c.flags.length ? " — " + c.flags.join(", ") : ""))}">${esc(c.text)}</td>`;
				}).join("") +
				`<td>${r.totals.P}</td><td>${r.totals.A}</td><td>${r.totals.NP}</td><td>${r.totals.ot}</td><td>${r.totals.short}</td></tr>`;
		});
		if (!rows.length) html += `<tr><td colspan="${data.days.length + 6}" class="text-muted">${__("No employees.")}</td></tr>`;
		html += "</tbody></table></div>";
		$body.html(html);
		$body.find(".slhrm-cal-day.click").on("click", function () { open_day(data.days.find((x) => x.date === $(this).data("date"))); });
		$body.find(".slhrm-cal-pend").on("click", function () { open_day(data.days.find((x) => x.date === $(this).data("date"))); });
		$body.find(".slhrm-reg-only").on("change", function () { state.only_attention = this.checked ? 1 : 0; render(); });
	}
};

frappe.pages["attendance-calendar"].on_page_show = function (wrapper) {
	if (frappe.route_options && frappe.route_options.branch && wrapper.slhrm_branch) {
		const b = frappe.route_options.branch;
		frappe.route_options = null;
		wrapper.slhrm_branch.set_value(b);
	}
};
