frappe.ui.form.on("Attendance Dashboard", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.trigger("show_stats");
        }
    },

    show_stats(frm) {
        frappe.call({
            method: "slhrm.doctype.attendance_dashboard.attendance_dashboard.get_attendance_stats",
            args: {
                employee: frm.doc.employee,
                from_date: frappe.datetime.add_days(frm.doc.date, -30),
                to_date: frm.doc.date,
            },
            callback(r) {
                if (r.message) {
                    let stats = r.message;
                    let html = `
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 10px 0;">
                            <div style="background: #e8f5e9; padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 24px; font-weight: bold; color: #2e7d32;">${stats.present}</div>
                                <div style="color: #666;">Present</div>
                            </div>
                            <div style="background: #ffebee; padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 24px; font-weight: bold; color: #c62828;">${stats.absent}</div>
                                <div style="color: #666;">Absent</div>
                            </div>
                            <div style="background: #fff3e0; padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 24px; font-weight: bold; color: #ef6c00;">${stats.half_day}</div>
                                <div style="color: #666;">Half Day</div>
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 10px 0;">
                            <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 24px; font-weight: bold; color: #1565c0;">${stats.on_leave}</div>
                                <div style="color: #666;">On Leave</div>
                            </div>
                            <div style="background: #f3e5f5; padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 24px; font-weight: bold; color: #7b1fa2;">${stats.total_hours.toFixed(1)}</div>
                                <div style="color: #666;">Total Hours</div>
                            </div>
                            <div style="background: #e8eaf6; padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 24px; font-weight: bold; color: #283593;">${stats.avg_hours}</div>
                                <div style="color: #666;">Avg Hours</div>
                            </div>
                        </div>
                    `;
                    frm.dashboard.add_comment(html, true);
                }
            },
        });
    },
});