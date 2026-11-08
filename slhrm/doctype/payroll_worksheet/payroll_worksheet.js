// slhrm/doctype/payroll_worksheet/payroll_worksheet.js
//
// Salary numbers come from HRMS's own Salary Slip calculation (in-memory preview on the server,
// never saved) + OT. This file only displays server values; it does no pay math.

const ROW_FIELDS = [
    'employee', 'employee_name', 'designation', 'salary_structure', 'base',
    'total_working_days', 'payment_days', 'lwp_days', 'present_days', 'absent_days', 'leave_days',
    'ot_eligible', 'normal_ot_hours', 'normal_ot_rate', 'normal_ot_amount',
    'double_ot_hours', 'double_ot_rate', 'double_ot_amount', 'ot_amount',
    'structure_gross', 'structure_deduction', 'loan_deduction',
    'additional_earning_total', 'additional_deduction_total',
    'total_earning', 'total_deduction', 'net_pay', 'row_error'
];
const SALARY_FIELDS = ROW_FIELDS.filter(f => ![
    'employee', 'ot_eligible', 'normal_ot_hours', 'normal_ot_rate', 'double_ot_hours', 'double_ot_rate'
].includes(f));
const OT_INPUTS = ['normal_ot_hours', 'normal_ot_rate', 'double_ot_hours', 'double_ot_rate'];
const JOB_TIMEOUT_MS = 15 * 60 * 1000;
const MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November', 'December'];
const NO_SSA_PATTERN = /No active .*Salary Structure Assignment/;

frappe.ui.form.on('Payroll Worksheet', {
    setup(frm) {
        if (frm.is_new() && !frm.doc.company) {
            frappe.db.get_single_value('SLHRM Settings', 'default_company').then(val => {
                if (val) frm.set_value('company', val);
            });
        }
    },

    onload(frm) {
        apply_new_defaults(frm);
        init_period_state(frm);
    },

    refresh(frm) {
        apply_new_defaults(frm);
        if (frm.doc.company) {
            frm.set_df_property('company', 'read_only', 1);
        }
        render_payroll_table(frm);

        if (frm.doc.docstatus === 0 && (frm.doc.employees || []).length) {
            frm.add_custom_button(__('Refresh Salary Data'), () => refresh_salary_data(frm));
        }
        if (frm.doc.docstatus === 1 && !frm.doc.payroll_entry) {
            frm.add_custom_button(__('Create Payroll Entry'), function() {
                frappe.confirm(__('Create a Payroll Entry for this worksheet?'), function() {
                    frm.call('create_payroll_entry').then(() => frm.reload_doc());
                });
            }, __('Actions'));
        }
        if (frm.doc.payroll_entry) {
            frm.add_custom_button(__('View Payroll Entry'), function() {
                frappe.set_route('Form', 'Payroll Entry', frm.doc.payroll_entry);
            }, __('Actions'));
        }
    },

    company(frm) {
        if (frm.doc.company) {
            frappe.db.get_value('Company', frm.doc.company, 'default_currency', r => {
                if (r && r.default_currency) frm.set_value('currency', r.default_currency);
            });
        }
    },

    branch(frm) { on_period_change(frm); },
    payroll_month(frm) { on_period_change(frm); },
    payroll_year(frm) { on_period_change(frm); },

    posting_date(frm) {
        // the user edited it (not our automatic end-date value) -> stop following the month
        if (frm.doc.posting_date && frm.doc.posting_date !== frm._auto_posting_date) {
            frm._posting_date_touched = true;
        }
    }
});


// ── Period defaults (Phase 1.3a) ───────────────────────────────────

function default_period(today_str) {
    // Previous month of `today_str` (YYYY-MM-DD); January -> December of the prior year.
    const [y, m] = today_str.split('-').map(Number);
    const year = m === 1 ? y - 1 : y;
    const month = m === 1 ? 12 : m - 1;
    return { year: year, month: String(month).padStart(2, '0') };
}


function period_label(frm) {
    return (MONTH_NAMES[parseInt(frm.doc.payroll_month)] || '') + ' ' + (frm.doc.payroll_year || '');
}


function apply_new_defaults(frm) {
    if (!frm.is_new() || frm._defaults_applied) return;
    frm._defaults_applied = true;
    const p = default_period(frappe.datetime.get_today());
    frm._reverting = true;  // no load / confirm while setting defaults
    Promise.all([
        frm.doc.payroll_year ? null : frm.set_value('payroll_year', p.year),
        frm.doc.payroll_month ? null : frm.set_value('payroll_month', p.month)
    ]).then(() => {
        frm._reverting = false;
        set_dates(frm);
    });
}


function init_period_state(frm) {
    // existing docs: a posting date different from the end date was set by hand
    if (!frm.is_new() && frm.doc.posting_date && frm.doc.posting_date !== frm.doc.end_date) {
        frm._posting_date_touched = true;
    }
    if ((frm.doc.employees || []).length) remember_period(frm);
}


function remember_period(frm) {
    frm._loaded_period = {
        branch: frm.doc.branch, payroll_month: frm.doc.payroll_month, payroll_year: frm.doc.payroll_year
    };
}


function on_period_change(frm) {
    if (frm._reverting) return;
    set_dates(frm);
    const has_rows = (frm.doc.employees || []).length > 0;
    if (frm.doc.docstatus === 0 && has_rows && frm._loaded_period) {
        frappe.confirm(
            __('Reload employees for {0}?', [period_label(frm)]),
            () => auto_load_payroll(frm),
            () => revert_period(frm)
        );
        return;
    }
    auto_load_payroll(frm);
}


function revert_period(frm) {
    const old = frm._loaded_period;
    if (!old) return;
    frm._reverting = true;
    Promise.all(Object.keys(old).map(f => frm.doc[f] !== old[f] ? frm.set_value(f, old[f]) : null)).then(() => {
        frm._reverting = false;
        set_dates(frm);
    });
}


function all_rows_without_ssa(rows) {
    return rows.length > 0 && rows.every(r => NO_SSA_PATTERN.test(r.row_error || ''));
}


// ── Loading (sync, or background job for large branches) ──────────

function auto_load_payroll(frm) {
    if (!frm.doc.branch || !frm.doc.payroll_month || !frm.doc.payroll_year || !frm.doc.company) return;
    if (frm.doc.docstatus !== 0 || frm._loading) return;
    frm._loading = true;
    frappe.call({
        method: 'slhrm.api.load_payroll_data',
        args: {
            branch: frm.doc.branch, company: frm.doc.company,
            payroll_month: frm.doc.payroll_month, payroll_year: frm.doc.payroll_year
        },
        freeze: true,
        freeze_message: __('Calculating salaries (HRMS preview)…'),
        callback: r => handle_result(frm, r.message, 'load'),
        error: () => { frm._loading = false; }
    });
}


function refresh_salary_data(frm) {
    if (frm._loading) return;
    frm._loading = true;
    const rows = (frm.doc.employees || []).map(r => {
        const o = { employee: r.employee };
        OT_INPUTS.forEach(f => { o[f] = r[f] || 0; });
        return o;
    });
    frappe.call({
        method: 'slhrm.api.refresh_salary_data',
        args: {
            company: frm.doc.company, payroll_month: frm.doc.payroll_month,
            payroll_year: frm.doc.payroll_year, rows: JSON.stringify(rows)
        },
        freeze: true,
        freeze_message: __('Refreshing salary data (HRMS preview)…'),
        callback: r => handle_result(frm, r.message, 'refresh'),
        error: () => { frm._loading = false; }
    });
}


function handle_result(frm, message, mode) {
    if (!message) {
        frm._loading = false;
        frappe.msgprint(__('No data found.'));
        return;
    }
    if (message.job) {
        run_background_job(frm, message.job, message.total, payload => apply_payload(frm, payload, mode));
        return;
    }
    apply_payload(frm, message, mode);
}


function run_background_job(frm, key, total, on_done) {
    // Locks the form (freeze) while the server builds previews; progress via realtime.
    frappe.dom.freeze(__('Calculating salaries: 0 / {0}', [total]));
    let finished = false;
    const finish = () => {
        finished = true;
        frappe.realtime.off('slhrm_payroll_progress', handler);
        frappe.dom.unfreeze();
        frm._loading = false;
    };
    const handler = data => {
        if (!data || data.key !== key || finished) return;
        if (data.status === 'done') {
            frappe.call('slhrm.api.get_payroll_job_result', { key: key }).then(r => {
                finish();
                if (r.message) on_done(r.message);
            }, finish);
        } else if (data.status === 'failed') {
            finish();
            frappe.msgprint({ title: __('Failed'), indicator: 'red', message: __('Salary calculation failed. See Error Log.') });
        } else if (data.done !== undefined) {
            $('.freeze-message').text(__('Calculating salaries: {0} / {1}', [data.done, data.total]));
        }
    };
    frappe.realtime.on('slhrm_payroll_progress', handler);
    setTimeout(() => {
        if (!finished) {
            finish();
            frappe.msgprint(__('Salary calculation is taking too long. Try Refresh Salary Data again later.'));
        }
    }, JOB_TIMEOUT_MS);
}


function apply_payload(frm, data, mode) {
    frm._loading = false;
    const rows = data.employees || [];

    if (mode === 'load') {
        remember_period(frm);
        frm.clear_table('employees');
        rows.forEach(emp => {
            const child = {};
            ROW_FIELDS.forEach(f => { child[f] = emp[f]; });
            frm.add_child('employees', child);
        });
    } else {
        const by_emp = {};
        rows.forEach(e => { by_emp[e.employee] = e; });
        (frm.doc.employees || []).forEach(row => {
            const e = by_emp[row.employee];
            if (!e) return;
            SALARY_FIELDS.forEach(f => { row[f] = e[f]; });
            ['ot_eligible', 'normal_ot_amount', 'double_ot_amount', 'ot_amount'].forEach(f => { row[f] = e[f]; });
            if (!e.ot_eligible) OT_INPUTS.forEach(f => { row[f] = 0; });
        });
    }

    frm.clear_table('earnings');
    (data.earnings || []).forEach(e => frm.add_child('earnings', {
        employee: e.employee, employee_name: e.employee_name, salary_component: e.salary_component,
        amount: e.amount, additional_salary: e.additional_salary || '', source_type: e.source_type
    }));
    frm.clear_table('deductions');
    (data.deductions || []).forEach(d => frm.add_child('deductions', {
        employee: d.employee, employee_name: d.employee_name, salary_component: d.salary_component,
        amount: d.amount, source_type: d.source_type, reference_name: d.reference_name || ''
    }));

    frm._salary_components = data.salary_components || [];
    frm.refresh_field('employees');
    frm.refresh_field('earnings');
    frm.refresh_field('deductions');
    refresh_doc_totals(frm);
    render_payroll_table(frm);

    if (all_rows_without_ssa(rows)) {
        frappe.msgprint({
            title: __('No salary assignments'), indicator: 'orange',
            message: __('No salary assignments for {0}. Check the month or create Salary Structure Assignments.', [period_label(frm)])
        });
        return;
    }
    const errors = rows.filter(r => r.row_error).length;
    frappe.show_alert({
        message: __('{0} employees calculated', [rows.length - errors]) + (errors ? ', ' + __('{0} with errors', [errors]) : ''),
        indicator: errors ? 'orange' : 'green'
    });
    if (data.warnings && data.warnings.length) {
        frappe.msgprint({ title: __('Warnings'), indicator: 'orange', message: data.warnings.join('<br>') });
    }
}


function set_dates(frm) {
    const year = frm.doc.payroll_year;
    const month = parseInt(frm.doc.payroll_month);
    if (!year || !month) return;
    const end_date = frappe.datetime.obj_to_str(new Date(year, month, 0));
    frm.set_value('start_date', frappe.datetime.obj_to_str(new Date(year, month - 1, 1)));
    frm.set_value('end_date', end_date);
    frm.set_value('month_name', MONTH_NAMES[month] || '');
    if (!frm._posting_date_touched || !frm.doc.posting_date) {
        frm._auto_posting_date = end_date;
        frm.set_value('posting_date', end_date);
    }
}


// ── Display helpers (server values only) ───────────────────────────

function component_data(frm) {
    // Component columns from the stored preview lines (works after reload too).
    const components = [], seen = {}, amounts = {};
    [['earnings', frm.doc.earnings || []], ['deductions', frm.doc.deductions || []]].forEach(pair => {
        pair[1].forEach(line => {
            if (!line.salary_component) return;
            if (!seen[line.salary_component]) {
                seen[line.salary_component] = 1;
                components.push({ name: line.salary_component, type: pair[0] });
            }
            const emp = amounts[line.employee] = amounts[line.employee] || {};
            emp[line.salary_component] = flt(emp[line.salary_component] || 0) + flt(line.amount);
        });
    });
    return { components, amounts };
}


function refresh_doc_totals(frm) {
    // Aggregates server-computed row values for the summary (server recomputes on save).
    const t = { ot: 0, normal: 0, double: 0, gross: 0, ded: 0, net: 0 };
    (frm.doc.employees || []).forEach(e => {
        t.ot += flt(e.ot_amount); t.normal += flt(e.normal_ot_amount); t.double += flt(e.double_ot_amount);
        t.gross += flt(e.total_earning); t.ded += flt(e.total_deduction); t.net += flt(e.net_pay);
    });
    frm.set_value('total_employees', (frm.doc.employees || []).length);
    frm.set_value('employees_with_ssa', (frm.doc.employees || []).filter(e => e.salary_structure).length);
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
    const employees = frm.doc.employees || [];
    const currency = frm.doc.currency || 'LKR';
    const wrapper = frm.fields_dict.salary_component_html;
    if (!wrapper) return;
    if (!employees.length) {
        wrapper.$wrapper.html('<p class="text-muted" style="padding:10px;">' + __('Select Branch, Month and Year to load payroll data.') + '</p>');
        return;
    }

    const data = component_data(frm);
    const earnings = data.components.filter(c => c.type === 'earnings');
    const deductions = data.components.filter(c => c.type === 'deductions');
    const amount_of = (emp, comp) => flt((data.amounts[emp] || {})[comp] || 0);
    const ot_editable = can_edit_ot(frm);
    const esc = frappe.utils.escape_html;
    const errors = employees.filter(e => e.row_error).length;
    const no_ssa_at_all = all_rows_without_ssa(employees);

    let html = '';
    if (no_ssa_at_all) {
        html += '<div class="alert alert-warning" style="margin:5px 0;">' +
            __('No salary assignments for {0}. Check the month or create Salary Structure Assignments.', [period_label(frm)]) + '</div>';
    } else if (errors) {
        html += '<div class="alert alert-danger" style="margin:5px 0;">' +
            __('{0} row(s) could not be calculated (red). Submit is blocked until they are fixed — then use Refresh Salary Data.', [errors]) + '</div>';
    }
    html += '<div style="overflow-x:auto; margin: 5px 0;">';
    html += '<table class="table table-bordered table-sm" style="font-size: 12px; border-collapse:collapse;">';

    html += '<thead><tr style="background:#1a237e; color:white;">';
    html += '<th rowspan="2" style="min-width:40px; position:sticky; left:0; background:#1a237e; z-index:2; text-align:center;">#</th>';
    html += '<th rowspan="2" style="min-width:160px; position:sticky; left:40px; background:#1a237e; z-index:2;">' + __('Employee') + '</th>';
    [__('Working Days'), __('Payment Days'), __('LWP')].forEach(h => {
        html += '<th rowspan="2" style="min-width:60px; text-align:center;">' + h + '</th>';
    });
    html += '<th colspan="3" style="background:#4a148c; text-align:center;">' + __('NORMAL OT') + '</th>';
    html += '<th colspan="3" style="background:#880e4f; text-align:center;">' + __('DOUBLE OT') + '</th>';
    if (earnings.length) html += '<th colspan="' + earnings.length + '" style="background:#1b5e20; text-align:center;">' + __('EARNINGS (HRMS)') + '</th>';
    if (deductions.length) html += '<th colspan="' + deductions.length + '" style="background:#b71c1c; text-align:center;">' + __('DEDUCTIONS (HRMS)') + '</th>';
    html += '<th rowspan="2" style="min-width:90px; position:sticky; right:200px; background:#0d47a1; z-index:2; text-align:right;">' + __('Total Earn') + '</th>';
    html += '<th rowspan="2" style="min-width:90px; position:sticky; right:100px; background:#0d47a1; z-index:2; text-align:right;">' + __('Total Ded') + '</th>';
    html += '<th rowspan="2" style="min-width:100px; position:sticky; right:0; background:#1b5e20; z-index:2; text-align:right; font-weight:bold;">' + __('Net Pay') + '</th>';
    html += '</tr><tr style="background:#283593; color:white;">';
    ['Hrs', 'Rate', 'Amount'].forEach(t => { html += '<th style="min-width:70px; background:#6a1b9a; text-align:center; font-size:11px;">' + __(t) + '</th>'; });
    ['Hrs', 'Rate', 'Amount'].forEach(t => { html += '<th style="min-width:70px; background:#ad1457; text-align:center; font-size:11px;">' + __(t) + '</th>'; });
    earnings.forEach(c => { html += '<th style="min-width:110px; background:#2e7d32; text-align:center; font-size:11px;">' + esc(c.name) + '</th>'; });
    deductions.forEach(c => { html += '<th style="min-width:110px; background:#c62828; text-align:center; font-size:11px;">' + esc(c.name) + '</th>'; });
    html += '</tr></thead><tbody>';

    const col_totals = {};
    employees.forEach((emp, idx) => {
        const show_error = emp.row_error && !no_ssa_at_all;
        const bg = show_error ? '#ffebee' : (idx % 2 === 0 ? '#ffffff' : '#f5f5f5');
        const ot_cell = (field, value) => {
            if (!ot_editable || !emp.ot_eligible) {
                return '<td class="text-right" title="' + (emp.ot_eligible ? '' : __('Not eligible for overtime')) + '">' + flt(value, 2) + '</td>';
            }
            return '<td style="padding:2px;"><input type="number" min="0" step="0.01" class="ot-input" data-row="' + emp.name + '" data-field="' + field + '" value="' + flt(value, 2) + '" style="width:100%; text-align:right; border:1px solid #d1c4e9; border-radius:3px; padding:4px 6px; font-size:12px; background:#f3e5f5;"></td>';
        };

        html += '<tr style="background:' + bg + ';"' + (show_error ? ' title="' + esc(emp.row_error) + '"' : '') + '>';
        html += '<td style="position:sticky; left:0; background:' + bg + '; z-index:1; text-align:center;">' + (idx + 1) + '</td>';
        html += '<td style="position:sticky; left:40px; background:' + bg + '; z-index:1;"><strong>' + esc(emp.employee_name || emp.employee) + '</strong>';
        if (show_error) html += '<div style="color:#c62828; font-size:11px; white-space:normal;">' + esc(emp.row_error) + '</div>';
        html += '</td>';
        html += '<td class="text-center">' + flt(emp.total_working_days) + '</td>';
        html += '<td class="text-center">' + flt(emp.payment_days) + '</td>';
        html += '<td class="text-center">' + flt(emp.lwp_days) + '</td>';
        html += ot_cell('normal_ot_hours', emp.normal_ot_hours);
        html += ot_cell('normal_ot_rate', emp.normal_ot_rate);
        html += '<td class="text-right">' + format_currency(emp.normal_ot_amount || 0, currency) + '</td>';
        html += ot_cell('double_ot_hours', emp.double_ot_hours);
        html += ot_cell('double_ot_rate', emp.double_ot_rate);
        html += '<td class="text-right">' + format_currency(emp.double_ot_amount || 0, currency) + '</td>';
        earnings.concat(deductions).forEach(c => {
            const amt = amount_of(emp.employee, c.name);
            col_totals[c.name] = flt(col_totals[c.name] || 0) + amt;
            html += '<td class="text-right">' + format_currency(amt, currency) + '</td>';
        });
        html += '<td class="text-right" style="position:sticky; right:200px; background:#e3f2fd; z-index:1; font-weight:500;">' + format_currency(emp.total_earning || 0, currency) + '</td>';
        html += '<td class="text-right" style="position:sticky; right:100px; background:#ffebee; z-index:1; font-weight:500;">' + format_currency(emp.total_deduction || 0, currency) + '</td>';
        html += '<td class="text-right" style="position:sticky; right:0; background:#c8e6c9; z-index:1; font-weight:bold;">' + format_currency(emp.net_pay || 0, currency) + '</td>';
        html += '</tr>';
    });

    html += '<tr style="font-weight:bold; background:#e8eaf6;">';
    html += '<td colspan="2" style="position:sticky; left:0; background:#e8eaf6; z-index:1;">' + __('TOTAL') + '</td>';
    html += '<td colspan="3"></td>';
    html += '<td colspan="2"></td><td class="text-right">' + format_currency(frm.doc.total_normal_ot_amount || 0, currency) + '</td>';
    html += '<td colspan="2"></td><td class="text-right">' + format_currency(frm.doc.total_double_ot_amount || 0, currency) + '</td>';
    earnings.concat(deductions).forEach(c => {
        html += '<td class="text-right">' + format_currency(col_totals[c.name] || 0, currency) + '</td>';
    });
    html += '<td class="text-right" style="position:sticky; right:200px; background:#90caf9; z-index:1;">' + format_currency(frm.doc.total_gross_pay || 0, currency) + '</td>';
    html += '<td class="text-right" style="position:sticky; right:100px; background:#ef9a9a; z-index:1;">' + format_currency(frm.doc.total_deductions || 0, currency) + '</td>';
    html += '<td class="text-right" style="position:sticky; right:0; background:#a5d6a7; z-index:1;">' + format_currency(frm.doc.total_net_pay || 0, currency) + '</td>';
    html += '</tr></tbody></table></div>';
    html += '<p class="text-muted small">' +
        __('Salary columns are HRMS Salary Slip previews (structure, payment days / LWP, Additional Salary, package overrides) — calculated on the server, never saved. Gross = HRMS gross + Normal OT + Double OT.') +
        '<br>' + __('Tax/statutory components are calculated on the final Salary Slip including OT.') + '</p>';

    wrapper.$wrapper.html(html);

    // OT inline edit -> server recalculates OT + totals (no preview rebuild)
    wrapper.$wrapper.find('.ot-input').on('change', function() {
        const cdn = $(this).data('row');
        const field = $(this).data('field');
        const value = Math.max(0, flt($(this).val()));
        const row = locals['Payroll Worksheet Employee'][cdn];
        if (!row || !row.ot_eligible) return;
        const args = {
            employee: row.employee, structure_gross: row.structure_gross || 0,
            structure_deduction: row.structure_deduction || 0, loan_deduction: row.loan_deduction || 0
        };
        OT_INPUTS.forEach(f => { args[f] = row[f] || 0; });
        args[field] = value;
        frappe.call({
            method: 'slhrm.api.calc_worksheet_row',
            args: args,
            callback: r => {
                if (!r.message) return;
                const values = Object.assign({}, r.message);
                values[field] = value;
                frappe.model.set_value(row.doctype, row.name, values).then(() => {
                    refresh_doc_totals(frm);
                    render_payroll_table(frm);
                });
            }
        });
    });
}
