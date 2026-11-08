// slhrm/doctype/attendance_marker/attendance_marker.js
//
// OT: calc_normal_ot / calc_double_ot are computed on the server (slhrm.overtime).
// normal_ot_hours / double_ot_hours (permlevel 1) default to the calculated values and
// follow recalculations until the user edits them. Ineligible rows stay at 0 (the
// server enforces this as well).

const OT_FIELDS = ["normal_ot_hours", "double_ot_hours"];
const CALC_FOR = { normal_ot_hours: "calc_normal_ot", double_ot_hours: "calc_double_ot" };

frappe.ui.form.on("Attendance Marker", {
	setup(frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_default("company"));
		}
	},

	refresh(frm) {
		frm.set_df_property("company", "read_only", 1);
		update_summary(frm);
		lock_ineligible_rows(frm);
	},

	date(frm) {
		auto_load_data(frm);
	},

	branch(frm) {
		auto_load_data(frm);
	},
});

frappe.ui.form.on("Attendance Marker Detail", {
	attendance_status(frm) {
		update_summary(frm);
	},

	attendance_details_remove(frm) {
		update_summary(frm);
	},

	form_render(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const grid_row = frm.fields_dict.attendance_details.grid.get_row(cdn);
		if (grid_row && grid_row.grid_form) {
			OT_FIELDS.forEach((f) =>
				grid_row.grid_form.set_df_property(f, "read_only", row.ot_eligible ? 0 : 1)
			);
		}
	},

	normal_ot_hours(frm, cdt, cdn) {
		guard_ot_value(frm, cdt, cdn, "normal_ot_hours");
	},

	double_ot_hours(frm, cdt, cdn) {
		guard_ot_value(frm, cdt, cdn, "double_ot_hours");
	},

	shift(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.employee || !frm.doc.date || !row.shift) return;

		frappe.call({
			method: "slhrm.api.recalc_attendance_row",
			args: { employee: row.employee, date: frm.doc.date, shift: row.shift },
			callback(r) {
				if (!r.message) return;
				const m = r.message;
				const prev_calc = { normal_ot_hours: row.calc_normal_ot, double_ot_hours: row.calc_double_ot };

				frappe.model.set_value(cdt, cdn, {
					in_time: m.in_time || "",
					out_time: m.out_time || "",
					auto_in_time: m.in_time || "",
					auto_out_time: m.out_time || "",
					worked_hours: m.worked_hours || 0,
					shift_hours: m.shift_hours || 0,
					ot_eligible: m.ot_eligible || 0,
					calc_normal_ot: m.calc_normal_ot || 0,
					calc_double_ot: m.calc_double_ot || 0,
					punch_source: m.punch_source || "",
					attendance_status: m.punch_count > 0 ? "Present" : "Absent",
				});

				// dirty flag: only follow the calculation if the user hasn't changed the value
				OT_FIELDS.forEach((f) => {
					const current = flt(row[f]);
					const untouched = !row[f] || current === flt(prev_calc[f]);
					if (!m.ot_eligible) {
						frappe.model.set_value(cdt, cdn, f, 0);
					} else if (untouched) {
						frappe.model.set_value(cdt, cdn, f, flt(m[CALC_FOR[f]]));
					}
				});
				lock_ineligible_rows(frm);

				if (m.warning) {
					frappe.show_alert({ message: m.warning, indicator: "orange" });
				}
			},
		});
	},
});

function guard_ot_value(frm, cdt, cdn, field) {
	const row = locals[cdt][cdn];
	if (!row.ot_eligible && flt(row[field])) {
		frappe.model.set_value(cdt, cdn, field, 0);
		frappe.show_alert({
			message: __("{0} is not eligible for overtime.", [row.employee_name || row.employee]),
			indicator: "orange",
		});
	} else if (flt(row[field]) < 0) {
		frappe.model.set_value(cdt, cdn, field, 0);
	}
}

function lock_ineligible_rows(frm) {
	const grid = frm.fields_dict.attendance_details && frm.fields_dict.attendance_details.grid;
	if (!grid) return;
	(frm.doc.attendance_details || []).forEach((row) => {
		const grid_row = grid.get_row(row.name);
		if (grid_row && grid_row.toggle_editable) {
			OT_FIELDS.forEach((f) => grid_row.toggle_editable(f, !!row.ot_eligible));
		}
	});
}

// ── Auto-load employees + punches when date & branch are set ──

function auto_load_data(frm) {
	if (!frm.doc.date || !frm.doc.branch) return;
	if (frm._loading) return;
	frm._loading = true;

	frappe.call({
		method: "slhrm.api.load_attendance_data",
		args: {
			date: frm.doc.date,
			branch: frm.doc.branch,
			device_id: frm.doc.device_id || "",
		},
		callback(r) {
			frm._loading = false;
			if (!r.message) {
				frappe.msgprint(__("No data found."));
				return;
			}

			const data = r.message;
			const matched = data.matched || {};
			const warnings = [];

			frm.clear_table("attendance_details");
			data.employees.forEach((emp) => {
				const m = matched[emp.name] || {};
				const has_punch = m.punch_count > 0;
				frm.add_child("attendance_details", {
					employee: emp.name,
					employee_name: emp.employee_name,
					department: emp.department,
					shift: emp.default_shift || "",
					attendance_status: has_punch ? "Present" : "Absent",
					attendance_source: !has_punch ? "Manual" : m.punch_source === "App" ? "App" : "Biometric",
					punch_source: m.punch_source || "",
					in_time: m.in_time || "",
					out_time: m.out_time || "",
					auto_in_time: m.in_time || "",
					auto_out_time: m.out_time || "",
					worked_hours: m.worked_hours || 0,
					shift_hours: m.shift_hours || 0,
					ot_eligible: m.ot_eligible || 0,
					calc_normal_ot: m.calc_normal_ot || 0,
					calc_double_ot: m.calc_double_ot || 0,
					normal_ot_hours: m.ot_eligible ? m.calc_normal_ot || 0 : 0,
					double_ot_hours: m.ot_eligible ? m.calc_double_ot || 0 : 0,
				});
				if (m.warning) warnings.push(emp.employee_name + ": " + m.warning);
			});

			frm.clear_table("punch_references");
			(data.punch_refs || []).forEach((ref, i) => {
				frm.add_child("punch_references", {
					employee: ref.employee,
					punch_doctype: ref.punch_doctype,
					punch_log: ref.punch_log,
					punch_time: ref.punch_time,
					punch_sequence: i + 1,
					used_as: ref.used_as,
				});
			});

			frm.refresh_field("attendance_details");
			frm.refresh_field("punch_references");
			update_summary(frm);
			lock_ineligible_rows(frm);

			frappe.show_alert({
				message: __("{0} present, {1} absent, {2} punches loaded.", [
					frm.doc.present_count,
					frm.doc.absent_count,
					(data.punch_refs || []).length,
				]),
				indicator: "green",
			});

			if (warnings.length) {
				frappe.msgprint({ title: __("Warnings"), indicator: "orange", message: warnings.join("<br>") });
			}
		},
		error() {
			frm._loading = false;
		},
	});
}

// ── Summary counter (recalc on status change) ──

function update_summary(frm) {
	const rows = frm.doc.attendance_details || [];
	let present = 0,
		absent = 0;
	rows.forEach((row) => {
		if (row.attendance_status === "Present") present++;
		else if (row.attendance_status === "Absent") absent++;
	});
	frm.set_value("total_employees", rows.length);
	frm.set_value("present_count", present);
	frm.set_value("absent_count", absent);
}
