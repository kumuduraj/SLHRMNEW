// slhrm/doctype/employee_salary_package/employee_salary_package_list.js
//
// "Import Salary Packages" (HR Manager / System Manager): upload the HR xlsx as a PRIVATE file →
// slhrm.salary_import.preview_import (dry run, nothing written) → preview table → Apply
// (slhrm.salary_import.apply_import; the uploaded file is deleted afterwards, also on Cancel).

frappe.listview_settings["Employee Salary Package"] = {
	onload(listview) {
		if (!frappe.user.has_role(["HR Manager", "System Manager"])) return;
		listview.page.add_inner_button(__("Import Salary Packages"), () => slhrm_salary_import(listview));
	},
};

function slhrm_salary_import(listview) {
	new frappe.ui.FileUploader({
		allow_multiple: false,
		make_attachments_public: false,
		allow_toggle_private: false,
		disable_file_browser: true,
		allow_web_link: false,
		allow_take_photo: false,
		restrictions: { allowed_file_types: [".xlsx"] },
		on_success(file) {
			frappe.call({
				method: "slhrm.salary_import.preview_import",
				args: { file_url: file.file_url },
				freeze: true,
				freeze_message: __("Checking the file…"),
			}).then((r) => slhrm_salary_preview(listview, file.file_url, r.message || {}));
		},
	});
}

const SI_AMOUNTS = ["Basic Salary", "Base Allowance", "Vehicle Allowance"];
const SI_COLORS = { create: "green", update: "blue", unchanged: "gray", skipped: "orange", error: "red" };

function si_money(v) {
	return v === null || v === undefined || v === "" ? "" : format_currency(v);
}

function slhrm_salary_preview(listview, file_url, data) {
	const esc = frappe.utils.escape_html;
	const counts = data.counts || {};
	const rows = data.rows || [];
	const can_apply = rows.some((r) => r.action === "create" || r.action === "update");
	const summary = Object.keys(SI_COLORS)
		.filter((k) => counts[k])
		.map((k) => `<span class="indicator-pill ${SI_COLORS[k]}">${esc(__(k))}: ${counts[k]}</span>`)
		.join(" ");
	let html = `<p>${__("Structure")}: <b>${esc(data.structure || "")}</b> &nbsp; ${summary}</p>`;
	html += `<div class="si-scroll" style="max-height: 50vh; overflow: auto;"><table class="table table-bordered table-sm si-rows" style="font-size: 12px;">
		<thead><tr><th>${__("Row")}</th><th>${__("Employee")}</th><th>${__("Name")}</th><th>${__("Branch")}</th>` +
		SI_AMOUNTS.map((c) => `<th class="text-right">${esc(__(c))}</th>`).join("") +
		`<th>${__("Effective From")}</th><th>${__("APIT Exempt")}</th><th>${__("Action")}</th><th>${__("SSA")}</th><th>${__("Message")}</th></tr></thead><tbody>`;
	rows.forEach((r) => {
		html += `<tr data-action="${esc(r.action)}"><td>${r.row}</td><td>${esc(r.employee || "")}</td><td>${esc(r.employee_name || "")}</td><td>${esc(r.branch || "")}</td>` +
			SI_AMOUNTS.map((c) => `<td class="text-right">${si_money(r[c])}</td>`).join("") +
			`<td>${r.effective_from ? frappe.datetime.str_to_user(r.effective_from) : ""}</td>` +
			`<td>${r.apit_exempt === null || r.apit_exempt === undefined ? "" : r.apit_exempt ? __("Yes") : __("No")}</td>` +
			`<td><span class="indicator-pill ${SI_COLORS[r.action] || "gray"}">${esc(__(r.action || ""))}</span></td>` +
			`<td>${esc(r.ssa || "")}</td><td>${esc(r.message || "")}</td></tr>`;
	});
	html += `</tbody></table></div>`;
	if ((data.totals || []).length) {
		html += `<h6 style="margin-top: 12px;">${__("Totals per branch (rows to create / update / unchanged)")}</h6>
			<table class="table table-bordered table-sm si-totals" style="font-size: 12px;"><thead><tr><th>${__("Branch")}</th><th class="text-right">${__("Employees")}</th>` +
			SI_AMOUNTS.map((c) => `<th class="text-right">${esc(__(c))}</th>`).join("") + `<th class="text-right">${__("Total")}</th></tr></thead><tbody>`;
		data.totals.forEach((t) => {
			html += `<tr><td>${esc(t.branch)}</td><td class="text-right">${t.employees}</td>` +
				SI_AMOUNTS.map((c) => `<td class="text-right">${si_money(t[c])}</td>`).join("") +
				`<td class="text-right"><b>${si_money(t.total)}</b></td></tr>`;
		});
		html += `</tbody></table>`;
	}
	let applied = false;
	const d = new frappe.ui.Dialog({
		title: __("Import Salary Packages — preview (nothing saved yet)"),
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "preview", options: html }],
		primary_action_label: can_apply ? __("Apply") : __("Close"),
		primary_action() {
			if (!can_apply) {
				d.hide();
				return;
			}
			frappe.call({
				method: "slhrm.salary_import.apply_import",
				args: { file_url },
				freeze: true,
				freeze_message: __("Creating / updating packages…"),
			}).then((r) => {
				applied = true;
				d.hide();
				const c = (r.message || {}).counts || {};
				frappe.msgprint({
					title: __("Salary packages imported"),
					indicator: c.error ? "orange" : "green",
					message: Object.keys(c).map((k) => `${esc(__(k))}: ${c[k]}`).join("<br>"),
				});
				listview.refresh();
			});
		},
	});
	d.onhide = () => {
		if (!applied) frappe.call({ method: "slhrm.salary_import.discard_import", args: { file_url } });
	};
	d.show();
}
