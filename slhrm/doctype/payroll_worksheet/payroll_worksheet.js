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
                    additional_salary: e.additional_salary
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

            var s = data.summary || {};
            frm.set_value('total_employees', s.total_employees || 0);
            frm.set_value('total_ot_amount', s.total_ot_amount || 0);
            frm.set_value('total_gross_pay', s.total_gross_pay || 0);
            frm.set_value('total_deductions', s.total_deductions || 0);
            frm.set_value('total_net_pay', s.total_net_pay || 0);

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
