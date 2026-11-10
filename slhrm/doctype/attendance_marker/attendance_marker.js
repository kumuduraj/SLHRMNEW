// slhrm/doctype/attendance_marker/attendance_marker.js
//
// Overnight: IN = shift date (marker date) + IN time; OUT = (next day if "OUT next day") + OUT time.
// The box is ticked by the loader when the OUT punch is after midnight and by the server whenever
// OUT < IN; supervisors may tick / untick it. Manual edits recalculate worked hours and OT on the
// server (slhrm.api.calc_attendance_times) — this file does no time math.
//
// OT (v0.2.0, one OT type): calc_ot is computed on the server (slhrm.overtime): (Early In + Late Out)/60,
// all worked hours on a holiday. ot_hours (permlevel 1: HR Manager / Attendance Supervisor) defaults to
// calc_ot and follows recalculations until the user edits it; the server records ot_edited_by / on.
// Early/late minutes and short-leave excuses come from the server too; this file only shows them:
// Late In / Early Out are orange in the grid unless excused, and the Lates counts are rows with an
// un-excused Late In / Early Out.

const OT_FIELDS = ["ot_hours"];
const CALC_FOR = { ot_hours: "calc_ot" };
const FIGURE_FIELDS = ["early_in_min", "late_in_min", "early_out_min", "late_out_min",
	"late_in_excused", "early_out_excused", "calc_ot"];
const LATE_FIELDS = { late_in_min: "late_in_excused", early_out_min: "early_out_excused" };

function figures(m) {
	const out = {};
	FIGURE_FIELDS.forEach((f) => { out[f] = m[f] || 0; });
	return out;
}

// orange Late In / Early Out cells in the grid (not when excused by short leave)
function set_late_formatters(frm) {
	const grid = frm.fields_dict.attendance_details && frm.fields_dict.attendance_details.grid;
	Object.entries(LATE_FIELDS).forEach(([field, excused]) => {
		const formatter = (value, df, options, doc) => {
			const v = cint(value);
			if (!v) return "";
			if (doc && cint(doc[excused])) {
				return `<span class="slhrm-excused text-muted" title="${__("Excused (short leave)")}">${v}</span>`;
			}
			return `<span class="slhrm-late" style="color: var(--orange-600, #e8590c); font-weight: 600;">${v}</span>`;
		};
		const dfs = [frappe.meta.get_docfield("Attendance Marker Detail", field, frm.doc.name),
			grid && grid.get_docfield(field)];
		dfs.forEach((df) => { if (df) df.formatter = formatter; });
		(grid && grid.docfields || []).forEach((df) => { if (df.fieldname === field) df.formatter = formatter; });
	});
}

frappe.ui.form.on("Attendance Marker", {
	setup(frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_default("company"));
		}
	},

	onload(frm) {
		set_late_formatters(frm);
	},

	refresh(frm) {
		set_late_formatters(frm);
		frm.set_df_property("company", "read_only", 1);
		update_summary(frm);
		lock_ineligible_rows(frm);
		show_previous_day(frm);
	},

	date(frm) {
		auto_load_data(frm);
		show_previous_day(frm);
	},

	branch(frm) {
		auto_load_data(frm);
		show_previous_day(frm);
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
		if (frm.doc.date && row.shift_date !== frm.doc.date) {
			frappe.model.set_value(cdt, cdn, "shift_date", frm.doc.date);
		}
		// per-row OT lock (row editor + grid cells); v16 grid_form has no set_df_property
		const grid_row = frm.fields_dict.attendance_details.grid.get_row(cdn);
		if (grid_row && grid_row.toggle_editable) {
			OT_FIELDS.forEach((f) => grid_row.toggle_editable(f, !!row.ot_eligible));
		}
		show_ot_edited(frm, row);
	},

	short_leave(frm, cdt, cdn) {
		recalc_times(frm, cdt, cdn);
	},

	short_leave_min(frm, cdt, cdn) {
		recalc_times(frm, cdt, cdn);
	},

	in_time(frm, cdt, cdn) {
		recalc_times(frm, cdt, cdn);
	},

	out_time(frm, cdt, cdn) {
		recalc_times(frm, cdt, cdn);
	},

	out_next_day(frm, cdt, cdn) {
		recalc_times(frm, cdt, cdn);
	},

	ot_hours(frm, cdt, cdn) {
		guard_ot_value(frm, cdt, cdn, "ot_hours");
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
				const prev_calc = { ot_hours: row.calc_ot };

				frappe.model.set_value(cdt, cdn, {
					in_time: m.in_time || "",
					out_time: m.out_time || "",
					out_next_day: m.out_next_day ? 1 : 0,
					auto_in_time: m.in_time || "",
					auto_out_time: m.out_time || "",
					worked_hours: m.worked_hours || 0,
					shift_hours: m.shift_hours || 0,
					ot_eligible: m.ot_eligible || 0,
					...figures(m),
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
				update_summary(frm);

				if (m.warning) {
					frappe.show_alert({ message: m.warning, indicator: "orange" });
				}
			},
		});
	},
});

// Manual IN / OUT / OUT next day edit -> server recalculates (no time math here)
function recalc_times(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || row.__slhrm_recalc || !row.employee || !frm.doc.date) return;
	const prev_calc = { ot_hours: row.calc_ot };
	const was_next_day = !!row.out_next_day;
	frappe.call({
		method: "slhrm.api.calc_attendance_times",
		args: {
			employee: row.employee, date: frm.doc.date, shift: row.shift || "",
			in_time: row.in_time || "", out_time: row.out_time || "", out_next_day: row.out_next_day ? 1 : 0,
			short_leave: row.short_leave ? 1 : 0, short_leave_min: cint(row.short_leave_min),
		},
		callback(r) {
			const m = r.message;
			if (!m) return;
			row.__slhrm_recalc = true;  // our own set_value calls must not trigger another round
			const values = {
				shift_date: frm.doc.date,
				out_next_day: m.out_next_day,
				worked_hours: m.worked_hours,
				shift_hours: m.shift_hours,
				ot_eligible: m.ot_eligible,
				...figures(m),
			};
			if (row.in_time && row.out_time && row.attendance_status === "Absent") {
				values.attendance_status = "Present";
			}
			if (!row.punch_source) values.attendance_source = "Manual";
			frappe.model.set_value(cdt, cdn, values).then(() => {
				OT_FIELDS.forEach((f) => {
					const untouched = !row[f] || flt(row[f]) === flt(prev_calc[f]);
					if (!m.ot_eligible) frappe.model.set_value(cdt, cdn, f, 0);
					else if (untouched) frappe.model.set_value(cdt, cdn, f, flt(m[CALC_FOR[f]]));
				});
				row.__slhrm_recalc = false;
				update_summary(frm);
				if (m.out_next_day && !was_next_day) {
					frappe.show_alert({ message: __("OUT is before IN: OUT +1 (next day) ticked."), indicator: "blue" });
				}
				if (m.warning) frappe.show_alert({ message: m.warning, indicator: "orange" }, 8);
			});
		},
	});
}

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
					shift_date: frm.doc.date,
					in_time: m.in_time || "",
					out_time: m.out_time || "",
					out_next_day: m.out_next_day ? 1 : 0,
					auto_in_time: m.in_time || "",
					auto_out_time: m.out_time || "",
					worked_hours: m.worked_hours || 0,
					shift_hours: m.shift_hours || 0,
					ot_eligible: m.ot_eligible || 0,
					...figures(m),
					ot_hours: m.ot_eligible ? m.calc_ot || 0 : 0,
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

// ── Previous day's marker (night shifts of that day may reach into this day) ──

function show_previous_day(frm) {
	if (!frm.doc.date || !frm.doc.branch) {
		frm.set_intro("");
		return;
	}
	frappe.call({
		method: "slhrm.api.marker_previous_day",
		args: { branch: frm.doc.branch, date: frm.doc.date, company: frm.doc.company || "" },
		callback(r) {
			const p = r.message;
			if (!p) return;
			const day = frappe.datetime.str_to_user(p.date);
			if (p.status === "Submitted") {
				frm.set_intro(__("Previous day {0}: marker {1} submitted.", [day, p.name]), "green");
			} else {
				frm.set_intro(__("Previous day {0}: {1}. Night shifts from that day may claim punches from this day — submit it first.",
					[day, p.status === "Draft" ? __("marker {0} is still a draft", [p.name]) :
						p.status === "Cancelled" ? __("marker {0} is cancelled", [p.name]) : __("no marker")]), "orange");
			}
		},
	});
}

// ── Summary counter (recalc on status / time change; server recounts on save) ──

function update_summary(frm) {
	const rows = frm.doc.attendance_details || [];
	let present = 0,
		absent = 0,
		late_in = 0,
		early_out = 0;
	rows.forEach((row) => {
		if (row.attendance_status === "Present") present++;
		else if (row.attendance_status === "Absent") absent++;
		if (cint(row.late_in_min) && !cint(row.late_in_excused)) late_in++;
		if (cint(row.early_out_min) && !cint(row.early_out_excused)) early_out++;
	});
	if (frm.doc.docstatus !== 0) return;
	frm.set_value("total_employees", rows.length);
	frm.set_value("present_count", present);
	frm.set_value("absent_count", absent);
	frm.set_value("late_in_count", late_in);
	frm.set_value("early_out_count", early_out);
}

// row editor: "OT edited by <user>" beside the OT field when OT differs from OT (calculated)
function show_ot_edited(frm, row) {
	const grid_row = frm.fields_dict.attendance_details.grid.get_row(row.name);
	const field = grid_row && grid_row.grid_form && grid_row.grid_form.fields_dict && grid_row.grid_form.fields_dict.ot_hours;
	if (!field || !field.set_description) return;
	if (row.ot_edited_by) {
		const when = row.ot_edited_on ? frappe.datetime.str_to_user(row.ot_edited_on) : "";
		field.set_description(__("Edited by {0} {1} — OT (calculated) {2} h", [frappe.utils.escape_html(row.ot_edited_by), when, flt(row.calc_ot)]));
	} else {
		field.set_description(__("= OT (calculated). HR Manager / Attendance Supervisor can change it."));
	}
}
