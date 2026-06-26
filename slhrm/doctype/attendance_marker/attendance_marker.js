// slhrm/slhrm/doctype/attendance_marker/attendance_marker.js

frappe.ui.form.on('Attendance Marker', {
    setup(frm) {
        // Set default company on new documents
        if (frm.is_new() && !frm.doc.company) {
            frm.set_value('company', frappe.defaults.get_default('company'));
        }
    },

    refresh(frm) {
        // Show company as read-only instead of hiding - allows multi-company setups
        frm.set_df_property('company', 'read_only', 1);
        update_summary(frm);
    },

    date(frm) {
        auto_load_data(frm);
    },

    branch(frm) {
        auto_load_data(frm);
    }
});

frappe.ui.form.on('Attendance Marker Detail', {
    attendance_status(frm, cdt, cdn) {
        update_summary(frm);
    },

    attendance_details_remove(frm) {
        update_summary(frm);
    },

    overtime_hours(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        // Auto-fill actual_overtime when overtime_hours changes (if not already set)
        if (!row.actual_overtime || row.actual_overtime === 0) {
            frappe.model.set_value(cdt, cdn, 'actual_overtime', row.overtime_hours || 0);
        }
    },

    override_overtime(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        var grid = frm.fields_dict.attendance_details.grid;
        var grid_row = grid && grid.get_row(cdn);
        if (grid_row && grid_row.grid_form) {
            grid_row.grid_form.set_df_property('overtime_hours', 'read_only', row.override_overtime ? 0 : 1);
        }
    },

    shift(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (!row.employee || !frm.doc.date || !row.shift) return;

        frappe.call({
            method: 'slhrm.api.recalc_attendance_row',
            args: {
                employee: row.employee,
                date: frm.doc.date,
                shift: row.shift
            },
            callback: function(r) {
                if (!r.message) return;
                var m = r.message;
                frappe.model.set_value(cdt, cdn, 'in_time', m.in_time || '');
                frappe.model.set_value(cdt, cdn, 'out_time', m.out_time || '');
                frappe.model.set_value(cdt, cdn, 'auto_in_time', m.in_time || '');
                frappe.model.set_value(cdt, cdn, 'auto_out_time', m.out_time || '');
                frappe.model.set_value(cdt, cdn, 'worked_hours', m.worked_hours || 0);
                frappe.model.set_value(cdt, cdn, 'overtime_hours', m.overtime_hours || 0);
                frappe.model.set_value(cdt, cdn, 'actual_overtime', m.overtime_hours || 0);
                frappe.model.set_value(cdt, cdn, 'shift_hours', m.shift_hours || 0);
                frappe.model.set_value(cdt, cdn, 'attendance_status',
                    m.punch_count > 0 ? 'Present' : 'Absent');

                if (m.warning) {
                    frappe.show_alert({message: m.warning, indicator: 'orange'});
                }
            }
        });
    }
});

// ── Auto-load employees + punches when date & branch are set ──

function auto_load_data(frm) {
    if (!frm.doc.date || !frm.doc.branch) return;
    if (frm._loading) return;
    frm._loading = true;

    frappe.call({
        method: 'slhrm.api.load_attendance_data',
        args: {
            date: frm.doc.date,
            branch: frm.doc.branch,
            device_id: frm.doc.device_id || ''
        },
        callback: function(r) {
            frm._loading = false;
            if (!r.message) {
                frappe.msgprint('No data found.');
                return;
            }

            var data = r.message;
            var matched = data.matched || {};
            var punch_count = 0;
            var warnings = [];

            // ── Populate attendance details ──
            frm.clear_table('attendance_details');
            data.employees.forEach(function(emp) {
                var m = matched[emp.name] || {};
                frm.add_child('attendance_details', {
                    employee: emp.name,
                    employee_name: emp.employee_name,
                    department: emp.department,
                    shift: emp.default_shift || '',
                    attendance_status: (m.punch_count > 0) ? 'Present' : 'Absent',
                    attendance_source: (m.punch_count > 0) ? 'Biometric' : 'Manual',
                    in_time: m.in_time || '',
                    out_time: m.out_time || '',
                    auto_in_time: m.in_time || '',
                    auto_out_time: m.out_time || '',
                    worked_hours: m.worked_hours || 0,
                    overtime_hours: m.overtime_hours || 0,
                    actual_overtime: m.overtime_hours || 0,
                    shift_hours: m.shift_hours || 0
                });

                if (m.warning) {
                    warnings.push(emp.employee_name + ': ' + m.warning);
                }
            });

            // ── Populate punch references ──
            frm.clear_table('punch_references');
            data.punch_logs.forEach(function(log) {
                punch_count++;
                frm.add_child('punch_references', {
                    employee: log.employee,
                    punch_log: log.name,
                    punch_time: log.punch_time,
                    punch_sequence: punch_count,
                    used_as: log.punch_type
                });
            });

            frm.refresh_field('attendance_details');
            frm.refresh_field('punch_references');

            // ── Update summary counts ──
            var present = 0, absent = 0;
            data.employees.forEach(function(e) {
                if (matched[e.name] && matched[e.name].punch_count > 0) {
                    present++;
                } else {
                    absent++;
                }
            });

            frm.set_value('total_employees', data.employees.length);
            frm.set_value('present_count', present);
            frm.set_value('absent_count', absent);

            frappe.show_alert({
                message: present + ' present, ' + absent + ' absent, ' + punch_count + ' punches loaded.',
                indicator: 'green'
            });

            // Show single-punch warnings
            if (warnings.length) {
                frappe.msgprint({
                    title: __('Warnings'),
                    indicator: 'orange',
                    message: warnings.join('<br>')
                });
            }
        },
        error: function() {
            frm._loading = false;
        }
    });
}

// ── Summary counter (recalc on status change) ──

function update_summary(frm) {
    if (!frm.doc.attendance_details || !frm.doc.attendance_details.length) {
        frm.set_value('total_employees', 0);
        frm.set_value('present_count', 0);
        frm.set_value('absent_count', 0);
        return;
    }
    var total = frm.doc.attendance_details.length;
    var present = 0, absent = 0;
    frm.doc.attendance_details.forEach(function(row) {
        if (row.attendance_status === 'Present') present++;
        else if (row.attendance_status === 'Absent') absent++;
    });
    frm.set_value('total_employees', total);
    frm.set_value('present_count', present);
    frm.set_value('absent_count', absent);
}
