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

        update_summary(frm);
        render_component_table(frm);

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


frappe.ui.form.on('Payroll Worksheet Employee', {
    ot_hours(frm, cdt, cdn) {
        recalc_row(frm, cdt, cdn);
    },

    ot_rate(frm, cdt, cdn) {
        recalc_row(frm, cdt, cdn);
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
            console.log('SLHRM salary_components:', frm._salary_components);
            console.log('SLHRM component_amounts:', frm._component_amounts);

            var s = data.summary || {};
            frm.set_value('total_employees', s.total_employees || 0);
            frm.set_value('total_ot_amount', s.total_ot_amount || 0);
            frm.set_value('total_gross_pay', s.total_gross_pay || 0);
            frm.set_value('total_deductions', s.total_deductions || 0);
            frm.set_value('total_net_pay', s.total_net_pay || 0);

            render_component_table(frm);

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

function recalc_row(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    row.ot_amount = flt(row.ot_hours) * flt(row.ot_rate);
    row.total_earning = flt(row.base) + flt(row.ot_amount) + flt(row.additional_earning_total);
    row.total_deduction = flt(row.additional_deduction_total) + flt(row.loan_deduction);
    row.net_pay = flt(row.total_earning) - flt(row.total_deduction);
    frm.refresh_field('employees');
    update_summary(frm);
}

function update_summary(frm) {
    if (!frm.doc.employees || !frm.doc.employees.length) {
        frm.set_value('total_employees', 0);
        frm.set_value('total_ot_amount', 0);
        frm.set_value('total_gross_pay', 0);
        frm.set_value('total_deductions', 0);
        frm.set_value('total_net_pay', 0);
        return;
    }
    var ot = 0, gross = 0, ded = 0, net = 0;
    frm.doc.employees.forEach(function(row) {
        ot += flt(row.ot_amount);
        gross += flt(row.total_earning);
        ded += flt(row.total_deduction);
        net += flt(row.net_pay);
    });
    frm.set_value('total_employees', frm.doc.employees.length);
    frm.set_value('total_ot_amount', ot);
    frm.set_value('total_gross_pay', gross);
    frm.set_value('total_deductions', ded);
    frm.set_value('total_net_pay', net);
}


function render_component_table(frm) {
    var components = frm._salary_components || [];
    var amounts = frm._component_amounts || {};
    var employees = frm.doc.employees || [];

    var wrapper = frm.fields_dict.salary_component_html;
    if (!components.length || !employees.length) {
        if (wrapper) wrapper.$wrapper.html('<p class="text-muted" style="padding:10px;">No salary components found. Ensure Salary Structure Assignments have base amounts set.</p>');
        return;
    }

    var earnings = components.filter(function(c) { return c.type === 'earnings'; });
    var deductions = components.filter(function(c) { return c.type === 'deductions'; });

    var html = '<div style="overflow-x:auto; margin-top: 10px;">';
    html += '<table class="table table-bordered table-sm" style="font-size: 12px;">';

    // Header row
    html += '<thead><tr style="background: #f0f4f7;">';
    html += '<th style="min-width:40px; position:sticky; left:0; background:#f0f4f7; z-index:1;">#</th>';
    html += '<th style="min-width:150px; position:sticky; left:40px; background:#f0f4f7; z-index:1;">Employee</th>';
    html += '<th style="min-width:60px;">Working Days</th>';
    html += '<th style="min-width:60px;">Present</th>';
    html += '<th style="min-width:60px;">Absent</th>';
    html += '<th style="min-width:60px;">Leave</th>';
    html += '<th style="min-width:50px;">OT Hrs</th>';

    // Earning columns (green header)
    earnings.forEach(function(c) {
        html += '<th style="min-width:100px; background:#d4edda; color:#155724; text-align:right;">' + c.abbr + '<br><small>' + c.name + '</small></th>';
    });

    // Deduction columns (red header)
    deductions.forEach(function(c) {
        html += '<th style="min-width:100px; background:#f8d7da; color:#721c24; text-align:right;">' + c.abbr + '<br><small>' + c.name + '</small></th>';
    });

    // Summary columns
    html += '<th style="min-width:100px; background:#cce5ff; text-align:right;">Total Earn</th>';
    html += '<th style="min-width:100px; background:#f8d7da; text-align:right;">Total Ded</th>';
    html += '<th style="min-width:100px; background:#d4edda; font-weight:bold; text-align:right;">Net Pay</th>';
    html += '</tr></thead>';

    // Body rows
    html += '<tbody>';
    var totals_earn = {};
    var totals_ded = {};
    var grand_earn = 0, grand_ded = 0, grand_net = 0;

    earnings.forEach(function(c) { totals_earn[c.name] = 0; });
    deductions.forEach(function(c) { totals_ded[c.name] = 0; });

    employees.forEach(function(emp, idx) {
        var emp_amounts = amounts[emp.employee] || {};
        var row_earn = 0, row_ded = 0;

        html += '<tr>';
        html += '<td style="position:sticky; left:0; background:white; z-index:1;">' + (idx + 1) + '</td>';
        html += '<td style="position:sticky; left:40px; background:white; z-index:1;"><strong>' + (emp.employee_name || emp.employee) + '</strong></td>';
        html += '<td class="text-center">' + (emp.total_working_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.present_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.absent_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.leave_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.ot_hours || 0) + '</td>';

        // Earning amounts
        earnings.forEach(function(c) {
            var amt = flt(emp_amounts[c.name] || 0);
            row_earn += amt;
            totals_earn[c.name] += amt;
            html += '<td class="text-right">' + format_currency(amt, frm.doc.currency) + '</td>';
        });

        // Deduction amounts
        deductions.forEach(function(c) {
            var amt = flt(emp_amounts[c.name] || 0);
            row_ded += amt;
            totals_ded[c.name] += amt;
            html += '<td class="text-right">' + format_currency(amt, frm.doc.currency) + '</td>';
        });

        var net = row_earn - row_ded;
        grand_earn += row_earn;
        grand_ded += row_ded;
        grand_net += net;

        html += '<td class="text-right" style="background:#e8f4fd;">' + format_currency(row_earn, frm.doc.currency) + '</td>';
        html += '<td class="text-right" style="background:#fde8e8;">' + format_currency(row_ded, frm.doc.currency) + '</td>';
        html += '<td class="text-right" style="background:#d4edda; font-weight:bold;">' + format_currency(net, frm.doc.currency) + '</td>';
        html += '</tr>';
    });

    // Totals row
    html += '<tr style="font-weight:bold; background:#f0f4f7;">';
    html += '<td colspan="2" style="position:sticky; left:0; background:#f0f4f7; z-index:1;">TOTAL</td>';
    html += '<td colspan="4"></td>';
    html += '<td></td>';

    earnings.forEach(function(c) {
        html += '<td class="text-right">' + format_currency(totals_earn[c.name], frm.doc.currency) + '</td>';
    });
    deductions.forEach(function(c) {
        html += '<td class="text-right">' + format_currency(totals_ded[c.name], frm.doc.currency) + '</td>';
    });
    html += '<td class="text-right" style="background:#cce5ff;">' + format_currency(grand_earn, frm.doc.currency) + '</td>';
    html += '<td class="text-right" style="background:#f8d7da;">' + format_currency(grand_ded, frm.doc.currency) + '</td>';
    html += '<td class="text-right" style="background:#d4edda;">' + format_currency(grand_net, frm.doc.currency) + '</td>';
    html += '</tr>';

    html += '</tbody></table></div>';

    var wrapper = frm.fields_dict.salary_component_html;
    if (wrapper) {
        wrapper.$wrapper.html(html);
    }
}
