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
    'total_earning', 'total_deduction', 'net_pay', 'row_error', 'components_json'
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
        apply_new_defaults(frm);
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
        if (!frm.is_new() && (frm.doc.employees || []).length) {
            frm.add_custom_button(__('Download Excel'), () => {
                if (frm.is_dirty()) {
                    frappe.msgprint(__('Save the worksheet first — Excel is built from the saved rows.'));
                    return;
                }
                window.open('/api/method/slhrm.api.download_worksheet_xlsx?name=' + encodeURIComponent(frm.doc.name));
            });
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
    // Previous month for a NEW worksheet. Called from setup, onload and refresh; runs once per new doc
    // (flag = doc name, because Frappe reuses `frm` for the next new doc).
    // frappe.model.create_new pre-fills a required Select with its first option, so payroll_month
    // arrives as "01" (and payroll_year as 0) — those are Frappe's placeholders, not a user choice;
    // the form is not rendered yet, so the user cannot have changed them.
    if (!frm.doc || !frm.is_new() || frm.__slhrm_period_defaulted === frm.doc.name) return;
    frm.__slhrm_period_defaulted = frm.doc.name;
    const p = default_period(frappe.datetime.get_today());
    const month_is_placeholder = !frm.doc.payroll_month || frm.doc.payroll_month === '01';
    const year_is_placeholder = !cint(frm.doc.payroll_year);
    if (!month_is_placeholder && !year_is_placeholder) return;  // e.g. route options / duplicate
    frm._reverting = true;  // no auto-load / confirm while the defaults go in
    frm.set_value({ payroll_year: p.year, payroll_month: p.month }).then(() => {  // year + month together
        set_dates(frm);
        frm._reverting = false;
        if (frm.doc.branch) auto_load_payroll(frm);  // first load uses the defaulted period
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


// ── Table layout (mirror of slhrm/payroll_table.py build_table — keep in step) ──
// Values come only from the stored HRMS preview breakdown (row.components_json) and the row's
// OT / total fields; the JS adds column sums for the totals row, nothing else.

const NO_TOTAL = ['normal_ot_rate', 'double_ot_rate', 'total_working_days', 'payment_days', 'lwp_days'];  // money + hours only

function parse_breakdown(row) {
    let b = {};
    try { b = row.components_json ? JSON.parse(row.components_json) : {}; } catch (e) { b = {}; }
    return { earnings: b.earnings || [], deductions: b.deductions || [], employer: b.employer || [], base_component: b.base_component || null,
             apit_component: b.apit_component || null, fixed_columns: b.fixed_columns || {} };
}


function build_table(rows) {
    rows = rows || [];
    const parsed = rows.map(parse_breakdown);
    const apit_comps = [];
    parsed.forEach(b => { if (b.apit_component && !apit_comps.includes(b.apit_component)) apit_comps.push(b.apit_component); });
    const union = kind => {
        const seen = [], bases = [], fixed = [];
        parsed.forEach(b => {
            (b.fixed_columns[kind] || []).forEach(c => { if (!fixed.includes(c)) fixed.push(c); });
            b[kind].forEach(l => { if (!seen.includes(l.component)) seen.push(l.component); });
            if (kind === 'earnings' && b.base_component && !bases.includes(b.base_component)) bases.push(b.base_component);
        });
        if (kind === 'deductions') {  // APIT may appear only through worksheet OT
            apit_comps.forEach(c => { if (!seen.includes(c) && !fixed.includes(c) && rows.some(r => flt(r.apit_amount))) seen.push(c); });
        }
        const first = bases.filter(c => seen.includes(c) || fixed.includes(c));
        const head = first.concat(fixed.filter(c => !first.includes(c)));
        return head.concat(seen.filter(c => !head.includes(c)));
    };
    const earn = union('earnings'), ded = union('deductions'), emp = [];
    parsed.forEach(b => b.employer.forEach(l => { if (!emp.includes(l.component)) emp.push(l.component); }));
    const has_loan = rows.some(r => flt(r.loan_deduction) > 0);
    const tip = c => c + ' — Salary Structure / Additional Salary';

    let groups = [
        { key: 'info', label: '', columns: [
            { key: 'idx', label: '#', type: 'int' }, { key: 'employee_name', label: 'Employee', type: 'text' },
            { key: 'total_working_days', label: 'Working Days', type: 'float' },
            { key: 'payment_days', label: 'Payment Days', type: 'float' }, { key: 'lwp_days', label: 'LWP', type: 'float' }] },
        { key: 'earnings', label: 'EARNINGS', columns: earn.map(c => ({ key: 'E::' + c, label: c, type: 'currency', tooltip: tip(c) })) },
        { key: 'normal_ot', label: 'NORMAL OT', columns: [
            { key: 'normal_ot_hours', label: 'Hrs', type: 'float' }, { key: 'normal_ot_rate', label: 'Rate', type: 'currency' },
            { key: 'normal_ot_amount', label: 'Amount', type: 'currency' }] },
        { key: 'double_ot', label: 'DOUBLE OT', columns: [
            { key: 'double_ot_hours', label: 'Hrs', type: 'float' }, { key: 'double_ot_rate', label: 'Rate', type: 'currency' },
            { key: 'double_ot_amount', label: 'Amount', type: 'currency' }] },
        { key: 'gross', label: '', columns: [{ key: 'total_earning', label: 'GROSS', type: 'currency' }] },
        { key: 'deductions', label: 'DEDUCTIONS', columns: ded.map(c => ({ key: 'D::' + c, label: c, type: 'currency', tooltip: tip(c) }))
            .concat(has_loan ? [{ key: 'loan_deduction', label: 'Loan', type: 'currency' }] : []) },
        { key: 'total_ded', label: '', columns: [{ key: 'total_deduction', label: 'TOTAL DED', type: 'currency' }] },
        { key: 'net', label: '', columns: [{ key: 'net_pay', label: 'NET PAY', type: 'currency' }] },
        { key: 'employer', label: 'EMPLOYER', collapsible: 1, columns: emp.map(c => ({
            key: 'ER::' + c, label: c, type: 'currency', tooltip: c + ' — employer contribution (statistical, not in net pay)' })) }
    ].filter(g => g.columns.length);
    const columns = [];
    groups.forEach(g => g.columns.forEach(c => columns.push(Object.assign({ group: g.key }, c))));

    const out_rows = rows.map((r, i) => {
        const cells = { idx: i + 1, employee_name: r.employee_name || r.employee, employee: r.employee, row_error: r.row_error || '', name: r.name };
        ['total_working_days', 'payment_days', 'lwp_days', 'normal_ot_hours', 'normal_ot_rate', 'normal_ot_amount',
         'double_ot_hours', 'double_ot_rate', 'double_ot_amount', 'total_earning', 'total_deduction', 'net_pay', 'loan_deduction']
            .forEach(k => { cells[k] = flt(r[k]); });
        const b = parsed[i];
        [['E', 'earnings'], ['D', 'deductions']].forEach(([p, kind]) => b[kind].forEach(l => {
            const key = p + '::' + l.component;
            cells[key] = flt(cells[key] || 0) + flt(l.amount);
        }));
        if (b.apit_component && r.apit_amount !== undefined && r.apit_amount !== null
            && (flt(r.apit_amount) || ('D::' + b.apit_component) in cells)) {
            cells['D::' + b.apit_component] = flt(r.apit_amount);  // APIT incl. worksheet OT
        }
        b.employer.forEach(l => { const key = 'ER::' + l.component; cells[key] = flt(cells[key] || 0) + flt(l.amount); });
        return cells;
    });
    const totals = {};
    columns.forEach(c => {
        if ((c.type === 'currency' || c.type === 'float') && !NO_TOTAL.includes(c.key)) {
            totals[c.key] = flt(out_rows.reduce((s, r) => s + flt(r[c.key] || 0), 0), 2);
        }
    });
    return { groups, columns, rows: out_rows, totals };
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


const GROUP_STYLE = {
    info: '#1a237e', earnings: '#1b5e20', normal_ot: '#4a148c', double_ot: '#880e4f', gross: '#0d47a1',
    deductions: '#b71c1c', total_ded: '#0d47a1', net: '#1b5e20', employer: '#e65100'
};


// EMPLOYER group toggle: per user, in this browser (localStorage `slhrm_pw_employer` = {user: 0|1});
// default collapsed. Storage can throw (private mode, blocked) -> fall back to the in-memory value.
const EMPLOYER_KEY = 'slhrm_pw_employer';

function employer_expanded(frm) {
    try {
        const m = JSON.parse(localStorage.getItem(EMPLOYER_KEY) || '{}');
        if (frappe.session.user in m) return !!m[frappe.session.user];
    } catch (e) { /* storage unavailable */ }
    return !!frm._show_employer;
}

function set_employer_expanded(frm, value) {
    frm._show_employer = !!value;
    try {
        const m = JSON.parse(localStorage.getItem(EMPLOYER_KEY) || '{}');
        m[frappe.session.user] = value ? 1 : 0;
        localStorage.setItem(EMPLOYER_KEY, JSON.stringify(m));
    } catch (e) { /* storage unavailable: in-memory only */ }
}

// number cells never wrap; the table scrolls horizontally inside .pw-scroll
const TABLE_CSS = '<style>' +
    '.pw-table td.pw-num, .pw-table th.pw-num { white-space: nowrap; text-align: right; }' +
    '.pw-table td.pw-money { min-width: 110px; }' +
    '.pw-table td.pw-num:not(.pw-money) { min-width: 56px; }' +
    '.pw-table { width: auto; min-width: 100%; }' +
    '.pw-table td.pw-name { white-space: nowrap; }' +  // one line per row; the error text below wraps
    '</style>';

function cell_class(c) {
    return [c.type !== 'text' ? 'pw-num' : '', c.type === 'currency' ? 'pw-money' : '',
            c.key === 'employee_name' ? 'pw-name' : '',
            c.group === 'employer' ? 'pw-er' : ''].filter(Boolean).join(' ');
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

    const t = build_table(employees);
    const show_employer = employer_expanded(frm);
    // decide by GROUP key: only t.columns carry c.group, the g.columns used for headers do not
    const in_view = group_key => group_key !== 'employer' || show_employer;
    const cols = t.columns.filter(c => in_view(c.group));
    const ot_editable = can_edit_ot(frm);
    const esc = frappe.utils.escape_html;
    const errors = employees.filter(e => e.row_error).length;
    const no_ssa_at_all = all_rows_without_ssa(employees);
    const fmt = (v, c) => {
        if (v === undefined || v === null || v === '') return c.type === 'currency' || c.type === 'float' ? '-' : '';
        if (c.type === 'currency') return format_currency(v, currency);
        return esc(String(v));
    };
    const sticky_left = (c, bg, z) => c.key === 'idx' ? 'position:sticky; left:0; z-index:' + z + '; background:' + bg + ';'
        : c.key === 'employee_name' ? 'position:sticky; left:36px; z-index:' + z + '; background:' + bg + '; min-width:170px;' : '';

    let html = TABLE_CSS;
    if (no_ssa_at_all) {
        html += '<div class="alert alert-warning" style="margin:5px 0;">' +
            __('No salary assignments for {0}. Check the month or create Salary Structure Assignments.', [period_label(frm)]) + '</div>';
    } else if (errors) {
        html += '<div class="alert alert-danger" style="margin:5px 0;">' +
            __('{0} row(s) could not be calculated (red). Submit is blocked until they are fixed — then use Refresh Salary Data.', [errors]) + '</div>';
    }
    if (t.groups.some(g => g.key === 'employer')) {
        html += '<div style="margin:4px 0;"><a class="toggle-employer" style="cursor:pointer;">' +
            (show_employer ? '▾ ' + __('Hide employer contributions') : '▸ ' + __('Show employer contributions (EPF / ETF)')) + '</a></div>';
    }
    html += '<div class="pw-scroll" style="overflow:auto; max-height:70vh; margin:5px 0; border:1px solid #d1d8dd;">';
    html += '<table class="table table-bordered table-sm pw-table" style="font-size:12px; border-collapse:separate; border-spacing:0; margin:0;">';

    // header row 1: groups (sticky)
    html += '<thead><tr>';
    t.groups.filter(g => in_view(g.key)).forEach(g => {
        const n = g.columns.length;
        const bg = GROUP_STYLE[g.key] || '#1a237e';
        if (g.key === 'info') {
            g.columns.forEach(c => {
                html += '<th rowspan="2" style="position:sticky; top:0; color:white; text-align:center; z-index:4; background:' + bg + ';' + sticky_left(c, bg, 5) + '">' + esc(c.label) + '</th>';
            });
        } else if (!g.label) {
            g.columns.forEach(c => {
                html += '<th rowspan="2" style="position:sticky; top:0; z-index:3; color:white; text-align:right; min-width:95px; background:' + bg + ';">' + esc(c.label) + '</th>';
            });
        } else {
            html += '<th colspan="' + n + '"' + (g.key === 'employer' ? ' class="pw-er"' : '') + ' style="position:sticky; top:0; z-index:3; color:white; text-align:center; background:' + bg + ';">' + esc(g.label) + '</th>';
        }
    });
    html += '</tr><tr>';
    t.groups.filter(g => g.label && g.key !== 'info' && in_view(g.key)).forEach(g => g.columns.forEach(c => {
        const bg = GROUP_STYLE[g.key];
        html += '<th' + (g.key === 'employer' ? ' class="pw-er"' : '') + ' title="' + esc(c.tooltip || '') + '" style="position:sticky; top:28px; z-index:3; color:white; text-align:center; font-size:11px; min-width:' + (c.key.indexOf('::') > 0 ? 110 : 70) + 'px; background:' + bg + '; opacity:0.92;">' + esc(c.label) + '</th>';
    }));
    html += '</tr></thead><tbody>';

    t.rows.forEach((r, i) => {
        const show_error = r.row_error && !no_ssa_at_all;
        const bg = show_error ? '#ffebee' : (i % 2 === 0 ? '#ffffff' : '#f7f7f7');
        html += '<tr' + (show_error ? ' title="' + esc(r.row_error) + '"' : '') + '>';
        cols.forEach(c => {
            const v = r[c.key];
            const style = 'background:' + bg + ';' + sticky_left(c, bg, 2) + (c.type === 'text' || c.type === 'int' ? '' : 'text-align:right;');
            const emp = employees[i];
            if (OT_INPUTS.includes(c.key) && ot_editable && emp.ot_eligible) {
                html += '<td style="padding:2px;' + style + '"><input type="number" min="0" step="0.01" class="ot-input" data-row="' + emp.name + '" data-field="' + c.key + '" value="' + flt(v, 2) + '" style="width:100%; min-width:64px; text-align:right; border:1px solid #d1c4e9; border-radius:3px; padding:3px 5px; font-size:12px; background:#f3e5f5;"></td>';
            } else if (c.key === 'employee_name') {
                html += '<td class="' + cell_class(c) + '" style="' + style + '"><strong>' + esc(v || '') + '</strong>' +
                    (show_error ? '<div style="color:#c62828; font-size:11px; white-space:normal;">' + esc(r.row_error) + '</div>' : '') + '</td>';
            } else {
                const strong = ['total_earning', 'total_deduction', 'net_pay'].includes(c.key);
                html += '<td class="' + cell_class(c) + '" style="' + style + (strong ? 'font-weight:600;' : '') + '">' + fmt(v, c) + '</td>';
            }
        });
        html += '</tr>';
    });

    html += '<tr style="font-weight:bold;">';
    cols.forEach(c => {
        const bg = '#e8eaf6';
        const style = 'background:' + bg + ';' + sticky_left(c, bg, 2) + (c.type === 'text' || c.type === 'int' ? '' : 'text-align:right;');
        const v = c.key === 'employee_name' ? __('TOTAL') : (c.key in t.totals ? t.totals[c.key] : '');
        html += '<td class="' + cell_class(c) + '" style="' + style + '">' + (c.key === 'employee_name' ? v : (v === '' ? '' : fmt(v, c))) + '</td>';
    });
    html += '</tr></tbody></table></div>';
    html += '<p class="text-muted small">' +
        __('Salary columns are HRMS Salary Slip previews (structure, payment days / LWP, Additional Salary, package overrides) — calculated on the server, never saved. Gross = HRMS gross + Normal OT + Double OT. "-" = component not on that employee\'s slip.') +
        '<br>' + __('Tax/statutory components are calculated on the final Salary Slip including OT.') + '</p>';

    wrapper.$wrapper.html(html);

    wrapper.$wrapper.find('.toggle-employer').on('click', () => {
        set_employer_expanded(frm, !employer_expanded(frm));
        render_payroll_table(frm);
    });

    // OT inline edit -> server recalculates OT + totals (no preview rebuild)
    wrapper.$wrapper.find('.ot-input').on('change', function() {
        const cdn = $(this).data('row');
        const field = $(this).data('field');
        const value = Math.max(0, flt($(this).val()));
        const row = locals['Payroll Worksheet Employee'][cdn];
        if (!row || !row.ot_eligible) return;
        const args = {
            employee: row.employee, structure_gross: row.structure_gross || 0,
            structure_deduction: row.structure_deduction || 0, loan_deduction: row.loan_deduction || 0,
            apit_taxable_base: row.apit_taxable_base || 0, apit_preview: row.apit_preview || 0,
            start_date: frm.doc.start_date || ''
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
