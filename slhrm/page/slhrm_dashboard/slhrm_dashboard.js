// slhrm/page/slhrm_dashboard/slhrm_dashboard.js — Attendance Dashboard v2 (v0.4.6): one card per branch + branch tabs with
// three panels. All numbers from slhrm.live_dashboard.get_dashboard (permitted branches only); auto-refresh every 2 min.
frappe.pages["slhrm-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Attendance Dashboard"), single_column: true });
	const esc = frappe.utils.escape_html;
	const REFRESH_MS = 2 * 60 * 1000;
	const MAX_ROWS = 10;
	const state = { tab: "All", expanded: {} };
	page.set_primary_action(__("Refresh"), () => load(), "refresh");
	page.add_inner_button(__("Open Attendance Markers"), () => frappe.set_route("List", "Attendance Marker"));
	page.add_inner_button(__("Attendance Calendar"), () => frappe.set_route("attendance-calendar"));
	const $updated = $(`<span class="text-muted small slhrm-updated" style="margin-left:8px;"></span>`).appendTo(page.$title_area);
	const $body = $(`<div class="slhrm-live2" style="padding:4px 0;"></div>`).appendTo(page.main);
	$body.html(`<p class="text-muted">${__("Loading…")}</p>`);

	const C = { teal: "var(--teal-600, #0c8599)", indigo: "var(--indigo-500, #4c6ef5)", orange: "var(--orange-500, #f76707)",
		purple: "var(--purple-500, #7950f2)", cyan: "var(--cyan-600, #1098ad)", pink: "var(--pink-500, #e64980)",
		blue: "var(--blue-500, #228be6)", green: "var(--green-500, #40c057)", yellow: "var(--yellow-600, #fab005)", red: "var(--red-500, #fa5252)" };
	const DOT = { Online: C.green, Delayed: "var(--yellow-500, #fcc419)", Offline: C.red, "No device": "var(--gray-500, #adb5bd)" };
	const YCOL = { None: "red", Draft: "orange", Submitted: "green" };
	const tm = (s, today) => !s ? "" : (s.slice(0, 10) === today ? moment(s).format("HH:mm") : moment(s).format("DD-MM HH:mm"));
	const css = `<style>
		.slhrm-cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap:10px; margin-bottom:12px; }
		.slhrm-bcard { border:1px solid var(--border-color); border-radius:10px; padding:10px 12px; cursor:pointer;
			background: var(--card-bg); box-shadow: var(--shadow-sm); }
		.slhrm-bcard.sel { outline:2px solid var(--primary, #2490ef); }
		.slhrm-bcard .big { font-size:26px; font-weight:700; line-height:1.1; }
		.slhrm-bcard .lbl, .slhrm-panel .lbl { font-size:11px; color:var(--text-muted); }
		.slhrm-bar { height:6px; border-radius:3px; background:var(--gray-200, #eee); overflow:hidden; margin:4px 0 8px; }
		.slhrm-bar > div { height:100%; }
		.slhrm-pill { display:inline-block; font-size:11px; padding:1px 7px; border-radius:10px; margin:1px 2px 1px 0; color:#fff; white-space:nowrap; }
		.slhrm-row { display:flex; justify-content:space-between; align-items:center; gap:6px; font-size:12px; margin-top:4px; }
		.slhrm-tabs { display:flex; flex-wrap:wrap; gap:6px; margin:4px 0 10px; }
		.slhrm-tabs button { border-radius:14px; }
		.slhrm-panels { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:10px; }
		.slhrm-panel { border:1px solid var(--border-color); border-radius:10px; overflow:hidden; background: var(--card-bg); }
		.slhrm-panel .ph { color:#fff; padding:6px 10px; font-weight:600; display:flex; justify-content:space-between; }
		.slhrm-panel .pr { display:flex; gap:8px; padding:4px 10px; font-size:12px; border-top:1px solid var(--border-color); }
		.slhrm-panel .pr .n { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
		.slhrm-panel .pr .t, .slhrm-panel .pr .s { white-space:nowrap; color:var(--text-muted); }
		.slhrm-dot { display:inline-block; width:10px; height:10px; border-radius:50%; vertical-align:middle; }
		</style>`;

	function load() {
		frappe.call({ method: "slhrm.live_dashboard.get_dashboard" }).then((r) => { state.data = r.message; render(); });
	}

	function card(b) {
		const col = C[b.color] || C.blue;
		const pct = b.employees ? Math.round(100 * b.punched / b.employees) : 0;
		const m = b.month;
		const mpct = m.working ? Math.round(100 * m.completed / m.working) : 0;
		const devtip = b.devices.map((d) => `${d.device_name}: ${d.status}, ${__("last sync")} ${tm(d.last_success_at, state.data.today) || "-"}, ${__("next read")} ${tm(d.next_read, state.data.today)}`).join("\n") || __("No device");
		const pill = (label, n, bg) => `<span class="slhrm-pill" style="background:${bg};${n ? "" : "opacity:.45;"}">${label} ${n}</span>`;
		const y = b.yesterday;
		return `<div class="slhrm-bcard ${state.tab === b.branch ? "sel" : ""}" data-branch="${esc(b.branch)}" style="border-top:5px solid ${col};">
			<div class="slhrm-row" style="margin-top:0;"><b style="font-size:14px;">${esc(b.branch)}</b>
				<span title="${esc(devtip)}"><span class="slhrm-dot slhrm-devdot" data-status="${esc(b.device)}" style="background:${DOT[b.device] || DOT.Offline};"></span>
				<span class="lbl">${esc(__(b.device))}</span>${b.unmatched ? ` <a class="slhrm-pill slhrm-unmatched" href="/desk/query-report/Unmatched Device Users"
				style="background:${C.red};" title="${__("Unmatched punches today")}">${b.unmatched}</a>` : ""}</span></div>
			<div style="margin-top:6px;"><span class="big slhrm-punched">${b.punched} / ${b.employees}</span> <span class="lbl">${__("punched today")}</span></div>
			<div class="slhrm-bar"><div style="width:${pct}%;background:${col};"></div></div>
			<div>${pill(__("On duty"), b.on_duty, C.green)}${b.has_device ? pill(__("Not punched"), b.not_punched, C.red) : ""}${pill(__("Late"), b.late, C.orange)}${pill(__("Missing OUT"), b.missing_out, "var(--yellow-600, #f59f00)")}</div>
			${b.has_device ? "" : `<div class="lbl slhrm-nodevice" style="margin-top:4px;">${__("No device — attendance by manual marker")}</div>`}
			<div class="slhrm-row"><span class="lbl">${__("Yesterday")}</span><a class="slhrm-yday indicator-pill ${YCOL[y.status]}" data-branch="${esc(b.branch)}">${__(y.status)}</a></div>
			<div class="slhrm-row"><span class="lbl">${__("Month")}</span><a class="slhrm-month" data-branch="${esc(b.branch)}" style="font-weight:600;">${m.completed} / ${m.working} ${__("days")}</a></div>
			<div class="slhrm-bar" style="margin-bottom:0;"><div style="width:${mpct}%;background:${col};opacity:.7;"></div></div></div>`;
	}

	function panel(key, title, color, rows, fmt) {
		const all = state.expanded[key];
		const shown = all ? rows : rows.slice(0, MAX_ROWS);
		return `<div class="slhrm-panel" data-panel="${key}"><div class="ph" style="background:${color};"><span>${title}</span><span>${rows.length}</span></div>` +
			(shown.length ? shown.map(fmt).join("") : `<div class="pr text-muted">${__("None")}</div>`) +
			(rows.length > MAX_ROWS ? `<div class="pr"><a class="slhrm-showall" data-panel="${key}">${all ? __("Show less") : __("Show all ({0})", [rows.length])}</a></div>` : "") + "</div>";
	}

	function render() {
		const d = state.data;
		$updated.text(__("Updated {0}", [moment(d.now).format("HH:mm")]));
		if (state.tab !== "All" && !d.branches.some((b) => b.branch === state.tab)) state.tab = "All";
		const colorOf = Object.fromEntries(d.branches.map((b) => [b.branch, C[b.color] || C.blue]));
		const pick = (k) => (state.tab === "All" ? d.branches.flatMap((b) => d.lists[b.branch][k].map((x) => Object.assign({ branch: b.branch }, x)))
			: d.lists[state.tab][k].map((x) => Object.assign({ branch: state.tab }, x)));
		const dot = (x) => (state.tab === "All" ? `<span class="slhrm-dot" style="background:${colorOf[x.branch]};margin-right:4px;" title="${esc(x.branch)}"></span>` : "");
		const nameRow = (x, time, extra) => `<div class="pr"><span class="n">${dot(x)}${esc(x.employee_name)}</span><span class="t">${time}</span>
			<span class="s">${esc(x.shift || "")}${extra || ""}</span></div>`;
		const sel = d.branches.find((b) => b.branch === state.tab);
		let html = css + `<div class="slhrm-cards">${d.branches.map(card).join("")}</div>`;
		html += `<div class="slhrm-tabs">` + ["All"].concat(d.branches.map((b) => b.branch)).map((t) =>
			`<button class="btn btn-xs ${t === state.tab ? "btn-primary" : "btn-default"} slhrm-tab" data-tab="${esc(t)}">${t === "All" ? __("All") : esc(t)}</button>`).join("") + "</div>";
		if (sel && !sel.has_device) html += `<div class="alert alert-secondary small" style="padding:6px 10px;">${__("No device — attendance by manual marker")}</div>`;
		const on = pick("on_duty"), np = pick("not_punched"), late = pick("late"), miss = pick("missing_out");
		html += `<div class="slhrm-panels">` +
			panel("on_duty", __("On duty"), "var(--green-600, #2f9e44)", on, (x) => nameRow(x, tm(x.time, d.today))) +
			panel("not_punched", __("Not punched yet"), "var(--red-600, #e03131)", np, (x) => nameRow(x, x.time ? tm(x.time, d.today) : "",
				x.not_arrived ? ` <span class="slhrm-pill" style="background:${C.red};">${__("late")}</span>` : "")) +
			panel("late", __("Late arrivals"), "var(--orange-600, #e8590c)", late, (x) => nameRow(x, tm(x.time, d.today), ` <b style="color:var(--orange-600,#e8590c);">+${x.minutes}m</b>`)) +
			"</div>";
		if (miss.length) {
			html += `<div class="slhrm-missing" style="margin-top:10px;border-radius:8px;padding:6px 10px;background:var(--yellow-100,#fff9db);border:1px solid var(--yellow-400,#ffd43b);font-size:12px;">
				<b>${__("Missing OUT")} (${miss.length})</b> · ` + miss.map((x) => `${dot(x)}${esc(x.employee_name)} <span class="text-muted">${tm(x.time, d.today)}</span>`).join(" · ") + "</div>";
		}
		$body.html(html);
		$body.find(".slhrm-bcard").on("click", function () { state.tab = $(this).data("branch"); render(); });
		$body.find(".slhrm-tab").on("click", function () { state.tab = $(this).data("tab"); render(); });
		$body.find(".slhrm-showall").on("click", function () { const k = $(this).data("panel"); state.expanded[k] = !state.expanded[k]; render(); });
		$body.find(".slhrm-unmatched").on("click", (e) => e.stopPropagation());
		$body.find(".slhrm-yday").on("click", function (e) {
			e.stopPropagation();
			const b = d.branches.find((x) => x.branch === $(this).data("branch"));
			if (b.yesterday.marker) frappe.set_route("Form", "Attendance Marker", b.yesterday.marker);
			else frappe.new_doc("Attendance Marker", { date: b.yesterday.date, branch: b.branch });
		});
		$body.find(".slhrm-month").on("click", function (e) {
			e.stopPropagation();
			frappe.route_options = { branch: $(this).data("branch") };
			frappe.set_route("attendance-calendar");
		});
	}

	load();
	setInterval(() => { if ($(wrapper).is(":visible")) load(); }, REFRESH_MS);
};
