frappe.pages['slhrm-dashboard'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'SLHRM Dashboard',
        single_column: true
    });
    
    let html = `
    <div style="padding: 20px;">
        <div class="row" style="margin-bottom: 20px;">
            <div class="col-sm-3">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold;" id="total-employees">-</div>
                    <div style="opacity: 0.9;">Total Employees</div>
                </div>
            </div>
            <div class="col-sm-3">
                <div style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; padding: 20px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold;" id="today-present">-</div>
                    <div style="opacity: 0.9;">Present Today</div>
                </div>
            </div>
            <div class="col-sm-3">
                <div style="background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); color: white; padding: 20px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold;" id="today-absent">-</div>
                    <div style="opacity: 0.9;">Absent Today</div>
                </div>
            </div>
            <div class="col-sm-3">
                <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 20px; border-radius: 10px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold;" id="month-present">-</div>
                    <div style="opacity: 0.9;">Present (30 Days)</div>
                </div>
            </div>
        </div>
        
        <div class="row" style="margin-bottom: 20px;">
            <div class="col-sm-6">
                <div style="background: white; border: 1px solid #e0e0e0; border-radius: 10px; padding: 20px;">
                    <h5 style="margin-top: 0;">Today's Summary</h5>
                    <div id="today-summary"><div class="text-muted">Loading...</div></div>
                </div>
            </div>
            <div class="col-sm-6">
                <div style="background: white; border: 1px solid #e0e0e0; border-radius: 10px; padding: 20px;">
                    <h5 style="margin-top: 0;">30-Day Summary</h5>
                    <div id="month-summary"><div class="text-muted">Loading...</div></div>
                </div>
            </div>
        </div>
        
        <div style="background: white; border: 1px solid #e0e0e0; border-radius: 10px; padding: 20px;">
            <h5 style="margin-top: 0;">Recent Attendance</h5>
            <div id="recent-attendance"><div class="text-muted">Loading...</div></div>
        </div>
        
        <div style="margin-top: 20px; text-align: center;">
            <a href="/app/attendance-dashboard/new" class="btn btn-primary btn-sm">
                <i class="fa fa-plus"></i> Add Attendance Record
            </a>
            <a href="/app/attendance-dashboard" class="btn btn-default btn-sm" style="margin-left: 10px;">
                <i class="fa fa-list"></i> View All Records
            </a>
        </div>
    </div>`;
    
    page.body.html(html);
    
    frappe.call({
        method: 'slhrm.page.slhrm_dashboard.slhrm_dashboard.get_dashboard_stats',
        callback: function(r) {
            if (r.message) {
                let data = r.message;
                $('#total-employees').text(data.total_employees);
                $('#today-present').text(data.today.present);
                $('#today-absent').text(data.today.absent);
                $('#month-present').text(data.month.present);
                
                let todayHtml = '<table class="table table-bordered" style="margin-bottom: 0;">';
                todayHtml += '<tr><td>Present</td><td class="text-right"><span class="indicator-pill green">' + data.today.present + '</span></td></tr>';
                todayHtml += '<tr><td>Absent</td><td class="text-right"><span class="indicator-pill red">' + data.today.absent + '</span></td></tr>';
                todayHtml += '<tr><td>Half Day</td><td class="text-right"><span class="indicator-pill orange">' + data.today.half_day + '</span></td></tr>';
                todayHtml += '<tr><td>On Leave</td><td class="text-right"><span class="indicator-pill blue">' + data.today.on_leave + '</span></td></tr>';
                todayHtml += '<tr><td>Holiday</td><td class="text-right"><span class="indicator-pill gray">' + data.today.holiday + '</span></td></tr>';
                todayHtml += '</table>';
                $('#today-summary').html(todayHtml);
                
                let monthHtml = '<table class="table table-bordered" style="margin-bottom: 0;">';
                monthHtml += '<tr><td>Present</td><td class="text-right"><span class="indicator-pill green">' + data.month.present + '</span></td></tr>';
                monthHtml += '<tr><td>Absent</td><td class="text-right"><span class="indicator-pill red">' + data.month.absent + '</span></td></tr>';
                monthHtml += '<tr><td>Half Day</td><td class="text-right"><span class="indicator-pill orange">' + data.month.half_day + '</span></td></tr>';
                monthHtml += '<tr><td>On Leave</td><td class="text-right"><span class="indicator-pill blue">' + data.month.on_leave + '</span></td></tr>';
                monthHtml += '<tr><td>Holiday</td><td class="text-right"><span class="indicator-pill gray">' + data.month.holiday + '</span></td></tr>';
                monthHtml += '</table>';
                $('#month-summary').html(monthHtml);
                
                if (data.recent && data.recent.length > 0) {
                    let recentHtml = '<table class="table table-striped"><thead><tr><th>Employee</th><th>Date</th><th>Status</th><th>Check In</th><th>Check Out</th><th>Hours</th></tr></thead><tbody>';
                    data.recent.forEach(function(row) {
                        let statusClass = 'gray';
                        if (row.status === 'Present') statusClass = 'green';
                        else if (row.status === 'Absent') statusClass = 'red';
                        else if (row.status === 'Half Day') statusClass = 'orange';
                        recentHtml += '<tr><td>' + (row.employee_name || row.employee) + '</td><td>' + row.date + '</td><td><span class="indicator-pill ' + statusClass + '">' + row.status + '</span></td><td>' + (row.check_in || '-') + '</td><td>' + (row.check_out || '-') + '</td><td>' + (row.working_hours || '-') + '</td></tr>';
                    });
                    recentHtml += '</tbody></table>';
                    $('#recent-attendance').html(recentHtml);
                } else {
                    $('#recent-attendance').html('<div class="text-muted">No attendance records found. <a href="/app/attendance-dashboard/new">Create your first record</a></div>');
                }
            }
        }
    });
};
