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
                    ot_eligible: emp.ot_eligible,
                    normal_ot_hours: emp.normal_ot_hours,
                    normal_ot_rate: emp.normal_ot_rate,
                    normal_ot_amount: emp.normal_ot_amount,
                    double_ot_hours: emp.double_ot_hours,
                    double_ot_rate: emp.double_ot_rate,
                    double_ot_amount: emp.double_ot_amount,
                    ot_amount: emp.ot_amount,
                    structure_earning_total: emp.structure_earning_total,
                    structure_deduction_total: emp.structure_deduction_total,
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

            var s = data.summary || {};
            frm.set_value('total_employees', s.total_employees || 0);
            frm.set_value('employees_with_ssa', s.employees_with_ssa || 0);
            frm.set_value('total_ot_amount', s.total_ot_amount || 0);
            frm.set_value('total_normal_ot_amount', s.total_normal_ot_amount || 0);
            frm.set_value('total_double_ot_amount', s.total_double_ot_amount || 0);
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


// ── Display helpers ──────────────────────────────────────────────
// All pay amounts come from the server (slhrm.payroll_pay / slhrm.overtime). The JS only
// displays them; it never applies the pay rule itself.

function component_data(frm) {
    // Fresh load: server-provided columns/amounts. After reload: rebuilt from the saved
    // earnings/deductions lines (display only).
    if (frm._salary_components && frm._salary_components.length) {
        return { components: frm._salary_components, amounts: frm._component_amounts || {} };
    }
    var components = [], seen = {}, amounts = {};
    [['earnings', frm.doc.earnings || []], ['deductions', frm.doc.deductions || []]].forEach(function(pair) {
        pair[1].forEach(function(line) {
            if (!line.salary_component) return;
            if (!seen[line.salary_component]) {
                seen[line.salary_component] = 1;
                components.push({ name: line.salary_component, type: pair[0] });
            }
            var emp = amounts[line.employee] = amounts[line.employee] || {};
            emp[line.salary_component] = flt(emp[line.salary_component] || 0) + flt(line.amount);
        });
    });
    return { components: components, amounts: amounts };
}


function refresh_doc_totals(frm) {
    // Aggregates the server-computed row values for the summary (server recomputes on save).
    var t = { ot: 0, normal: 0, double: 0, gross: 0, ded: 0, net: 0 };
    (frm.doc.employees || []).forEach(function(e) {
        t.ot += flt(e.ot_amount); t.normal += flt(e.normal_ot_amount); t.double += flt(e.double_ot_amount);
        t.gross += flt(e.total_earning); t.ded += flt(e.total_deduction); t.net += flt(e.net_pay);
    });
    frm.set_value('total_ot_amount', t.ot);
    frm.set_value('total_normal_ot_amount', t.normal);
    frm.set_value('total_double_ot_amount', t.double);
    frm.set_value('total_gross_pay', t.gross);
    frm.set_value('total_deductions', t.ded);
    frm.set_value('total_net_pay', t.net);
}


function can_edit_ot(frm) {
    // OT hours/rates are permlevel 1 (HR Manager / System Manager); server enforces too
    return frm.doc.docstatus === 0 && !!(frm.perm && frm.perm[1] && frm.perm[1].write);
}


function render_payroll_table(frm) {
    var employees = frm.doc.employees || [];
    var currency = frm.doc.currency || 'LKR';
    var wrapper = frm.fields_dict.salary_component_html;
    if (!wrapper) return;

    if (!employees.length) {
        wrapper.$wrapper.html('<p class="text-muted" style="padding:10px;">Select Branch, Month and Year to load payroll data.</p>');
        return;
    }

    var data = component_data(frm);
    var earnings = data.components.filter(function(c) { return c.type === 'earnings'; });
    var deductions = data.components.filter(function(c) { return c.type === 'deductions'; });
    var amount_of = function(emp, comp) { return flt((data.amounts[emp] || {})[comp] || 0); };
    var ot_editable = can_edit_ot(frm);
    var esc = frappe.utils.escape_html;

    var html = '<div style="overflow-x:auto; margin: 5px 0;">';
    html += '<table class="table table-bordered table-sm" style="font-size: 12px; border-collapse:collapse;">';

    // Header row 1
    html += '<thead><tr style="background:#1a237e; color:white;">';
    html += '<th rowspan="2" style="min-width:40px; position:sticky; left:0; background:#1a237e; z-index:2; text-align:center;">#</th>';
    html += '<th rowspan="2" style="min-width:150px; position:sticky; left:40px; background:#1a237e; z-index:2;">Employee</th>';
    ['Days', 'Present', 'Absent', 'Leave'].forEach(function(h) {
        html += '<th rowspan="2" style="min-width:50px; text-align:center;">' + h + '</th>';
    });
    html += '<th colspan="3" style="background:#4a148c; text-align:center;">NORMAL OT</th>';
    html += '<th colspan="3" style="background:#880e4f; text-align:center;">DOUBLE OT</th>';
    if (earnings.length) html += '<th colspan="' + earnings.length + '" style="background:#1b5e20; text-align:center;">EARNINGS</th>';
    if (deductions.length) html += '<th colspan="' + deductions.length + '" style="background:#b71c1c; text-align:center;">DEDUCTIONS</th>';
    html += '<th rowspan="2" style="min-width:90px; position:sticky; right:200px; background:#0d47a1; z-index:2; text-align:right;">Total Earn</th>';
    html += '<th rowspan="2" style="min-width:90px; position:sticky; right:100px; background:#0d47a1; z-index:2; text-align:right;">Total Ded</th>';
    html += '<th rowspan="2" style="min-width:100px; position:sticky; right:0; background:#1b5e20; z-index:2; text-align:right; font-weight:bold;">Net Pay</th>';
    html += '</tr>';

    // Header row 2
    html += '<tr style="background:#283593; color:white;">';
    ['Hrs', 'Rate', 'Amount'].forEach(function(t) { html += '<th style="min-width:70px; background:#6a1b9a; text-align:center; font-size:11px;">' + t + '</th>'; });
    ['Hrs', 'Rate', 'Amount'].forEach(function(t) { html += '<th style="min-width:70px; background:#ad1457; text-align:center; font-size:11px;">' + t + '</th>'; });
    earnings.forEach(function(c) { html += '<th style="min-width:110px; background:#2e7d32; text-align:center; font-size:11px;">' + esc(c.name) + '</th>'; });
    deductions.forEach(function(c) { html += '<th style="min-width:110px; background:#c62828; text-align:center; font-size:11px;">' + esc(c.name) + '</th>'; });
    html += '</tr></thead><tbody>';

    var col_totals = {};
    employees.forEach(function(emp, idx) {
        var bg = idx % 2 === 0 ? '#ffffff' : '#f5f5f5';
        var ot_cell = function(field, value) {
            if (!ot_editable || !emp.ot_eligible) {
                return '<td class="text-right" title="' + (emp.ot_eligible ? '' : __('Not eligible for overtime')) + '">' + flt(value, 2) + '</td>';
            }
            return '<td style="padding:2px;"><input type="number" min="0" step="0.01" class="ot-input" data-row="' + emp.name + '" data-field="' + field + '" value="' + flt(value, 2) + '" style="width:100%; text-align:right; border:1px solid #d1c4e9; border-radius:3px; padding:4px 6px; font-size:12px; background:#f3e5f5;"></td>';
        };

        html += '<tr style="background:' + bg + ';">';
        html += '<td style="position:sticky; left:0; background:' + bg + '; z-index:1; text-align:center;">' + (idx + 1) + '</td>';
        html += '<td style="position:sticky; left:40px; background:' + bg + '; z-index:1;"><strong>' + esc(emp.employee_name || emp.employee) + '</strong></td>';
        html += '<td class="text-center">' + (emp.total_working_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.present_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.absent_days || 0) + '</td>';
        html += '<td class="text-center">' + (emp.leave_days || 0) + '</td>';
        html += ot_cell('normal_ot_hours', emp.normal_ot_hours);
        html += ot_cell('normal_ot_rate', emp.normal_ot_rate);
        html += '<td class="text-right">' + format_currency(emp.normal_ot_amount || 0, currency) + '</td>';
        html += ot_cell('double_ot_hours', emp.double_ot_hours);
        html += ot_cell('double_ot_rate', emp.double_ot_rate);
        html += '<td class="text-right">' + format_currency(emp.double_ot_amount || 0, currency) + '</td>';
        earnings.concat(deductions).forEach(function(c) {
            var amt = amount_of(emp.employee, c.name);
            col_totals[c.name] = flt(col_totals[c.name] || 0) + amt;
            html += '<td class="text-right">' + format_currency(amt, currency) + '</td>';
        });
        html += '<td class="text-right" style="position:sticky; right:200px; background:#e3f2fd; z-index:1; font-weight:500;">' + format_currency(emp.total_earning || 0, currency) + '</td>';
        html += '<td class="text-right" style="position:sticky; right:100px; background:#ffebee; z-index:1; font-weight:500;">' + format_currency(emp.total_deduction || 0, currency) + '</td>';
        html += '<td class="text-right" style="position:sticky; right:0; background:#c8e6c9; z-index:1; font-weight:bold;">' + format_currency(emp.net_pay || 0, currency) + '</td>';
        html += '</tr>';
    });

    // Totals row (document totals are server values)
    html += '<tr style="font-weight:bold; background:#e8eaf6;">';
    html += '<td colspan="2" style="position:sticky; left:0; background:#e8eaf6; z-index:1;">TOTAL</td>';
    html += '<td colspan="4"></td>';
    html += '<td colspan="2"></td><td class="text-right">' + format_currency(frm.doc.total_normal_ot_amount || 0, currency) + '</td>';
    html += '<td colspan="2"></td><td class="text-right">' + format_currency(frm.doc.total_double_ot_amount || 0, currency) + '</td>';
    earnings.concat(deductions).forEach(function(c) {
        html += '<td class="text-right">' + format_currency(col_totals[c.name] || 0, currency) + '</td>';
    });
    html += '<td class="text-right" style="position:sticky; right:200px; background:#90caf9; z-index:1;">' + format_currency(frm.doc.total_gross_pay || 0, currency) + '</td>';
    html += '<td class="text-right" style="position:sticky; right:100px; background:#ef9a9a; z-index:1;">' + format_currency(frm.doc.total_deductions || 0, currency) + '</td>';
    html += '<td class="text-right" style="position:sticky; right:0; background:#a5d6a7; z-index:1;">' + format_currency(frm.doc.total_net_pay || 0, currency) + '</td>';
    html += '</tr></tbody></table></div>';
    html += '<p class="text-muted small">' + __('Gross = structure earnings (Basic = base) + OT + Additional Salary. Amounts are calculated on the server.') + '</p>';

    wrapper.$wrapper.html(html);

    // OT inline edit -> server recalculates the row (slhrm.api.calc_worksheet_row)
    wrapper.$wrapper.find('.ot-input').on('change', function() {
        var cdn = $(this).data('row');
        var field = $(this).data('field');
        var value = Math.max(0, flt($(this).val()));
        var row = locals['Payroll Worksheet Employee'][cdn];
        if (!row || !row.ot_eligible) return;
        var args = {
            employee: row.employee, start_date: frm.doc.start_date, end_date: frm.doc.end_date,
            normal_ot_hours: row.normal_ot_hours, double_ot_hours: row.double_ot_hours,
            normal_ot_rate: row.normal_ot_rate, double_ot_rate: row.double_ot_rate,
            loan_deduction: row.loan_deduction || 0
        };
        args[field] = value;
        frappe.call({
            method: 'slhrm.api.calc_worksheet_row',
            args: args,
            callback: function(r) {
                if (!r.message) return;
                var values = Object.assign({}, r.message);
                values[field] = value;
                frappe.model.set_value(row.doctype, row.name, values).then(function() {
                    refresh_doc_totals(frm);
                    render_payroll_table(frm);
                });
            }
        });
    });
}
