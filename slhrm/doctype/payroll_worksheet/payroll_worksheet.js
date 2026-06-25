frappe.ui.form.on('Payroll Worksheet', {
    setup(frm) {
        if (frm.is_new() && !frm.doc.company) {
            frappe.db.get_single_value('SLHRM Settings', 'default_company').then(val => {
                if (val) frm.set_value('company', val);
            });
        }

        if (!frm.doc.payroll_year) {
            frm.set_value('payroll_year', new Date().getFullYear());
        }
    },

    refresh(frm) {
        if (frm.doc.company) {
            frm.set_df_property('company', 'read_only', 1);
        }

        render_payroll_table(frm);

        if (frm.doc.docstatus === 1 && !frm.doc.payroll_entry) {
            frm.add_custom_button(
                __('Create Payroll Entry'),
                function() {
                    frappe.confirm(
                        __('Create a Payroll Entry for this worksheet?'),
                        function() {
                            frm.call('create_payroll_entry').then(() => {
                                frm.reload_doc();
                            });
                        }
                    );
                },
                __('Actions')
            );
        }

        if (frm.doc.payroll_entry) {
            frm.add_custom_button(
                __('View Payroll Entry'),
                function() {
                    frappe.set_route('Form', 'Payroll Entry', frm.doc.payroll_entry);
                },
                __('Actions')
            );
        }
    },

    company(frm) {
        if (frm.doc.company) {
            frappe.db.get_value('Company', frm.doc.company, 'default_currency', r => {
                if (r && r.default_currency) {
                    frm.set_value('currency', r.default_currency);
                }
            });
        }
    },

    branch(frm) {
        set_dates(frm);
        auto_load_payroll(frm);
    },

    payroll_month(frm) {
        set_dates(frm);
        auto_load_payroll(frm);
    },

    payroll_year(frm) {
        set_dates(frm);
        auto_load_payroll(frm);
    }
});


function auto_load_payroll(frm) {
    if (!frm.doc.branch || !frm.doc.payroll_month || !frm.doc.payroll_year) return;
    if (!frm.doc.company) return;
    if (frm.doc.docstatus !== 0) return;
    if (frm._loading) return;
    frm._loading = true;

    frappe.call({
        method: 'slhrm.api.load_payroll_data',
        args: {
            branch: frm.doc.branch,
            company: frm.doc.company,
            payroll_month: frm.doc.payroll_month,
            payroll_year: frm.doc.payroll_year
        },
        callback: function(r) {
            frm._loading = false;
            if (!r.message) {
                frappe.msgprint(__('No data found.'));
                return;
            }

            var data = r.message;

            frm.clear_table('employees');
            (data.employees || []).forEach(function(emp) {
                frm.add_child('employees', {
                    employee: emp.employee,
                    employee_name: emp.employee_name,
                    designation: emp.designation,
                    salary_structure: emp.salary_structure,
                    base: emp.base,
                    total_working_days: emp.total_working_days,
                    present_days: emp.present_days,
                    absent_days: emp.absent_days,
                    leave_days: emp.leave_days,
                    ot_hours: emp.ot_hours,
                    ot_rate: emp.ot_rate,
                    ot_amount: emp.ot_amount,
                    additional_earning_total: emp.additional_earning_total,
                    additional_deduction_total: emp.additional_deduction_total,
                    loan_deduction: emp.loan_deduction,
                    total_earning: emp.total_earning,
                    total_deduction: emp.total_deduction,
                    net_pay: emp.net_pay
                });
            });

            frm.clear_table('earnings');
            (data.earnings || []).forEach(function(e) {
                frm.add_child('earnings', {
                    employee: e.employee,
                    employee_name: e.employee_name,
                    salary_component: e.salary_component,
                    amount: e.amount,
                    additional_salary: e.additional_salary || '',
                    source_type: e.source_type || 'Salary Structure'
                });
            });

            frm.clear_table('deductions');
            (data.deductions || []).forEach(function(d) {
                frm.add_child('deductions', {
                    employee: d.employee,
                    employee_name: d.employee_name,
                    salary_component: d.salary_component || '',
                    amount: d.amount,
                    source_type: d.source_type || 'Additional Salary',
                    reference_name: d.reference_name || ''
                });
            });

            frm.refresh_field('employees');
            frm.refresh_field('earnings');
            frm.refresh_field('deductions');

            frm._salary_components = data.salary_components || [];
            frm._component_amounts = data.component_amounts || {};
            frm._edit_cache = {};

            var s = data.summary || {};
            frm.set_value('total_employees', s.total_employees || 0);
            frm.set_value('employees_with_ssa', s.employees_with_ssa || 0);
            frm.set_value('total_ot_amount', s.total_ot_amount || 0);
            frm.set_value('total_gross_pay', s.total_gross_pay || 0);
            frm.set_value('total_deductions', s.total_deductions || 0);
            frm.set_value('total_net_pay', s.total_net_pay || 0);

            render_payroll_table(frm);

            var with_ssa = data.employees.filter(e => e.salary_structure).length;
            var without_ssa = data.employees.length - with_ssa;

            frappe.show_alert({
                message: data.employees.length + ' employees loaded — '
                    + with_ssa + ' with salary structure'
                    + (without_ssa > 0 ? ', ' + without_ssa + ' missing' : ''),
                indicator: without_ssa > 0 ? 'orange' : 'green'
            });

            if (data.warnings && data.warnings.length) {
                frappe.msgprint({
                    title: __('Warnings'),
                    indicator: 'orange',
                    message: data.warnings.join('<br>')
                });
            }
        },
        error: function() {
            frm._loading = false;
        }
    });
}


function set_dates(frm) {
    var year = frm.doc.payroll_year;
    var month = parseInt(frm.doc.payroll_month);
    if (!year || !month) return;

    var start = new Date(year, month - 1, 1);
    var end = new Date(year, month, 0);

    frm.set_value('start_date', frappe.datetime.obj_to_str(start));
    frm.set_value('end_date', frappe.datetime.obj_to_str(end));

    var names = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                 'July', 'August', 'September', 'October', 'November', 'December'];
    frm.set_value('month_name', names[month] || '');
}


function get_val(frm, emp_id, comp_name) {
    var key = emp_id + '|' + comp_name;
    if (frm._edit_cache && frm._edit_cache[key] !== undefined) {
        return frm._edit_cache[key];
    }
    var amounts = frm._component_amounts || {};
    var emp_amounts = amounts[emp_id] || {};
    return emp_amounts[comp_name] || 0;
}


function set_val(frm, emp_id, comp_name, value) {
    if (!frm._edit_cache) frm._edit_cache = {};
    var key = emp_id + '|' + comp_name;
    frm._edit_cache[key] = flt(value);
}


function sync_child_tables(frm) {
    if (!frm._edit_cache) return;

    var components = frm._salary_components || [];
    var earnings = components.filter(function(c) { return c.type === 'earnings'; });
    var deductions = components.filter(function(c) { return c.type === 'deductions'; });
    var employees = frm.doc.employees || [];

    frm.clear_table('earnings');
    employees.forEach(function(emp) {
        earnings.forEach(function(c) {
            var amt = get_val(frm, emp.employee, c.name);
            if (amt !== 0) {
                frm.add_child('earnings', {
                    employee: emp.employee,
                    employee_name: emp.employee_name,
                    salary_component: c.name,
                    amount: amt,
                    source_type: 'Salary Structure'
                });
            }
        });
    });

    frm.clear_table('deductions');
    employees.forEach(function(emp) {
        deductions.forEach(function(c) {
            var amt = get_val(frm, emp.employee, c.name);
            if (amt !== 0) {
                frm.add_child('deductions', {
                    employee: emp.employee,
                    employee_name: emp.employee_name,
                    salary_component: c.name,
                    amount: amt,
                    source_type: 'Salary Structure'
                });
            }
        });
    });

    frm.refresh_field('earnings');
    frm.refresh_field('deductions');
}


function recalc_totals(frm) {
    var components = frm._salary_components || [];
    var employees = frm.doc.employees || [];
    var earnings = components.filter(function(c) { return c.type === 'earnings'; });
    var deductions = components.filter(function(c) { return c.type === 'deductions'; });

    var grand_earn = 0, grand_ded = 0, grand_ot = 0;

    employees.forEach(function(emp) {
        var row_earn = 0, row_ded = 0;
        earnings.forEach(function(c) { row_earn += get_val(frm, emp.employee, c.name); });
        deductions.forEach(function(c) { row_ded += get_val(frm, emp.employee, c.name); });
        grand_earn += row_earn;
        grand_ded += row_ded;
        grand_ot += flt(emp.ot_amount || 0);
    });

    frm.set_value('total_ot_amount', grand_ot);
    frm.set_value('total_gross_pay', grand_earn);
    frm.set_value('total_deductions', grand_ded);
    frm.set_value('total_net_pay', grand_earn - grand_ded);
}


function render_payroll_table(frm) {
    var components = frm._salary_components || [];
    var employees = frm.doc.employees || [];
    var currency = frm.doc.currency || 'LKR';

    var wrapper = frm.fields_dict.salary_component_html;
    if (!wrapper) return;

    if (!components.length || !employees.length) {
        wrapper.$wrapper.html('<p class="text-muted" style="padding:10px;">Select Branch, Month and Year to load payroll data.</p>');
        return;
    }

    var earnings = components.filter(function(c) { return c.type === 'earnings'; });
    var deductions = components.filter(function(c) { return c.type === 'deductions'; });

    var html = '<div style="overflow-x:auto; margin: 5px 0;">';
    html += '<table class="table table-bordered table-sm" id="payroll-single-table" style="font-size: 12px; border-collapse:collapse;">';

    // ── Header Row 1: group headers ──
    html += '<thead>';
    html += '<tr style="background:#1a237e; color:white;">';
    html += '<th rowspan="2" style="min-width:40px; position:sticky; left:0; background:#1a237e; z-index:2; text-align:center;">#</th>';
    html += '<th rowspan="2" style="min-width:150px; position:sticky; left:40px; background:#1a237e; z-index:2;">Employee</th>';
    html += '<th rowspan="2" style="min-width:50px; text-align:center;">Days</th>';
    html += '<th rowspan="2" style="min-width:50px; text-align:center;">Present</th>';
    html += '<th rowspan="2" style="min-width:50px; text-align:center;">Absent</th>';
    html += '<th rowspan="2" style="min-width:45px; text-align:center;">Leave</th>';
    html += '<th rowspan="2" style="min-width:45px; text-align:center;">OT Hrs</th>';
    html += '<th colspan="' + earnings.length + '" style="background:#1b5e20; text-align:center;">EARNINGS</th>';
    html += '<th colspan="' + deductions.length + '" style="background:#b71c1c; text-align:center;">DEDUCTIONS</th>';
    html += '<th rowspan="2" style="min-width:90px; position:sticky; right:200px; background:#0d47a1; z-index:2; text-align:right;">Total Earn</th>';
    html += '<th rowspan="2" style="min-width:90px; position:sticky; right:100px; background:#0d47a1; z-index:2; text-align:right;">Total Ded</th>';
    html += '<th rowspan="2" style="min-width:100px; position:sticky; right:0; background:#1b5e20; z-index:2; text-align:right; font-weight:bold;">Net Pay</th>';
    html += '</tr>';

    // Header Row 2: full component names
    html += '<tr style="background:#283593; color:white;">';
    earnings.forEach(function(c) {
        html += '<th style="min-width:120px; background:#2e7d32; text-align:center; font-size:11px;">' + c.name + '</th>';
    });
    deductions.forEach(function(c) {
        html += '<th style="min-width:120px; background:#c62828; text-align:center; font-size:11px;">' + c.name + '</th>';
    });
    html += '</tr>';
    html += '</thead>';

    // ── Body ──
    html += '<tbody>';
    var totals_earn = {};
    var totals_ded = {};
    var grand_earn = 0, grand_ded = 0, grand_net = 0;

    earnings.forEach(function(c) { totals_earn[c.name] = 0; });
    deductions.forEach(function(c) { totals_ded[c.name] = 0; });

    employees.forEach(function(emp, idx) {
        var row_earn = 0, row_ded = 0;
        var bg = idx % 2 === 0 ? '#ffffff' : '#f5f5f5';

        html += '<tr data-emp="' + emp.employee + '" style="background:' + bg + ';">';
        html += '<td style="position:sticky; left:0; background:' + bg + '; z-index:1; text-align:center;">' + (idx + 1) + '</td>';
        html += '<td style="position:sticky; left:40px; background:' + bg + '; z-index:1;"><strong>' + (emp.employee_name || emp.employee) + '</strong></td>';
        html += '<td class="text-center">' + (emp.total_working_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.present_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.absent_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.leave_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.ot_hours || 0) + '</td>';

        // Earning amounts (editable)
        earnings.forEach(function(c) {
            var amt = get_val(frm, emp.employee, c.name);
            row_earn += amt;
            totals_earn[c.name] += amt;
            html += '<td style="text-align:right; padding:2px;">';
            html += '<input type="number" class="comp-input" data-emp="' + emp.employee + '" data-comp="' + c.name + '" ';
            html += 'value="' + flt(amt, 2) + '" style="width:100%; text-align:right; border:1px solid #c8e6c9; border-radius:3px; padding:4px 6px; font-size:12px; background:#f1f8e9;">';
            html += '</td>';
        });

        // Deduction amounts (editable)
        deductions.forEach(function(c) {
            var amt = get_val(frm, emp.employee, c.name);
            row_ded += amt;
            totals_ded[c.name] += amt;
            html += '<td style="text-align:right; padding:2px;">';
            html += '<input type="number" class="comp-input" data-emp="' + emp.employee + '" data-comp="' + c.name + '" ';
            html += 'value="' + flt(amt, 2) + '" style="width:100%; text-align:right; border:1px solid #ffcdd2; border-radius:3px; padding:4px 6px; font-size:12px; background:#fce4ec;">';
            html += '</td>';
        });

        var net = row_earn - row_ded;
        grand_earn += row_earn;
        grand_ded += row_ded;
        grand_net += net;

        html += '<td class="text-right row-earn" style="position:sticky; right:200px; background:#e3f2fd; z-index:1; font-weight:500; min-width:100px;">' + format_currency(row_earn, currency) + '</td>';
        html += '<td class="text-right row-ded" style="position:sticky; right:100px; background:#ffebee; z-index:1; font-weight:500; min-width:100px;">' + format_currency(row_ded, currency) + '</td>';
        html += '<td class="text-right row-net" style="position:sticky; right:0; background:#c8e6c9; z-index:1; font-weight:bold; min-width:110px;">' + format_currency(net, currency) + '</td>';
        html += '</tr>';
    });

    // Totals row
    html += '<tr style="font-weight:bold; background:#e8eaf6;">';
    html += '<td colspan="2" style="position:sticky; left:0; background:#e8eaf6; z-index:1;">TOTAL</td>';
    html += '<td colspan="5"></td>';
    earnings.forEach(function(c) {
        html += '<td class="text-right col-total-earn" data-comp="' + c.name + '" style="background:#c8e6c9;">' + format_currency(totals_earn[c.name], currency) + '</td>';
    });
    deductions.forEach(function(c) {
        html += '<td class="text-right col-total-ded" data-comp="' + c.name + '" style="background:#ffcdd2;">' + format_currency(totals_ded[c.name], currency) + '</td>';
    });
    html += '<td class="text-right grand-earn" style="position:sticky; right:200px; background:#90caf9; z-index:1;">' + format_currency(grand_earn, currency) + '</td>';
    html += '<td class="text-right grand-ded" style="position:sticky; right:100px; background:#ef9a9a; z-index:1;">' + format_currency(grand_ded, currency) + '</td>';
    html += '<td class="text-right grand-net" style="position:sticky; right:0; background:#a5d6a7; z-index:1; font-weight:bold;">' + format_currency(grand_net, currency) + '</td>';
    html += '</tr>';

    html += '</tbody></table></div>';

    wrapper.$wrapper.html(html);

    // Bind input change events
    wrapper.$wrapper.find('.comp-input').on('change', function() {
        var emp_id = $(this).data('emp');
        var comp_name = $(this).data('comp');
        var new_val = flt($(this).val());

        set_val(frm, emp_id, comp_name, new_val);

        // Recalculate this row
        var $row = $(this).closest('tr');
        var row_earn = 0, row_ded = 0;
        $row.find('.comp-input').each(function() {
            var cn = $(this).data('comp');
            var is_earning = earnings.some(function(c) { return c.name === cn; });
            var v = flt($(this).val());
            if (is_earning) row_earn += v;
            else row_ded += v;
        });
        var net = row_earn - row_ded;
        $row.find('.row-earn').text(format_currency(row_earn, currency));
        $row.find('.row-ded').text(format_currency(row_ded, currency));
        $row.find('.row-net').text(format_currency(net, currency));

        // Recalculate column totals
        earnings.forEach(function(c) {
            var col_total = 0;
            wrapper.$wrapper.find('.comp-input[data-comp="' + c.name + '"]').each(function() {
                col_total += flt($(this).val());
            });
            wrapper.$wrapper.find('.col-total-earn[data-comp="' + c.name + '"]').text(format_currency(col_total, currency));
        });
        deductions.forEach(function(c) {
            var col_total = 0;
            wrapper.$wrapper.find('.comp-input[data-comp="' + c.name + '"]').each(function() {
                col_total += flt($(this).val());
            });
            wrapper.$wrapper.find('.col-total-ded[data-comp="' + c.name + '"]').text(format_currency(col_total, currency));
        });

        // Recalculate grand totals
        var grand_earn = 0, grand_ded = 0;
        wrapper.$wrapper.find('.row-earn').each(function() { grand_earn += flt($(this).text().replace(/[^0-9.\-]/g, '')); });
        wrapper.$wrapper.find('.row-ded').each(function() { grand_ded += flt($(this).text().replace(/[^0-9.\-]/g, '')); });
        var grand_net = grand_earn - grand_ded;
        wrapper.$wrapper.find('.grand-earn').text(format_currency(grand_earn, currency));
        wrapper.$wrapper.find('.grand-ded').text(format_currency(grand_ded, currency));
        wrapper.$wrapper.find('.grand-net').text(format_currency(grand_net, currency));

        // Update doc summary fields
        frm.set_value('total_gross_pay', grand_earn);
        frm.set_value('total_deductions', grand_ded);
        frm.set_value('total_net_pay', grand_net);

        sync_child_tables(frm);
    });
}
