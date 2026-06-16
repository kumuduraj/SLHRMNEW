// slhrm/slhrm/public/js/slhrm.js
// Frappe v16 desk fixes — runs AFTER desk.bundle.js loads

// 1. Ensure sidebar_item_map exists before Frappe reads it
(function () {
    if (localStorage.getItem("sidebar_item_map") === null) {
        localStorage.setItem("sidebar_item_map", "{}");
    }
})();

$(document).ready(function () {
    // 2. Guard sidebar.setup() against undefined workspace_title
    if (frappe.ui?.Sidebar?.prototype?.setup) {
        var _origSetup = frappe.ui.Sidebar.prototype.setup;
        frappe.ui.Sidebar.prototype.setup = function (workspace_title) {
            if (workspace_title == null) return;
            return _origSetup.call(this, workspace_title);
        };
    }

    // 3. Skip divider items in add_app_item() to prevent GET /undefined
    if (frappe.ui?.SidebarHeader?.prototype?.add_app_item) {
        var _origAddAppItem = frappe.ui.SidebarHeader.prototype.add_app_item;
        frappe.ui.SidebarHeader.prototype.add_app_item = function (item) {
            if (item.is_divider || (!item.icon && !item.icon_url)) return;
            return _origAddAppItem.call(this, item);
        };
    }

    // 4. Inject section icons into workspace sidebar (namespaced localStorage)
    var ICONS = {
        "Time & Attendance": '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><path d="m9 16 2 2 4-4"/>',
        "Employee": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
        "Recruitment": '<rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
        "Leaves": '<path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/>',
        "Payroll": '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
        "Expense & Travel": '<path d="M2 17a5 5 0 0 0 10 0c0-2.76-2.5-5-5-3l5-6"/><path d="M12 17a5 5 0 0 0 10 0c0-2.76-2.5-5-5-3l5-6"/><rect width="18" height="12" x="3" y="11" rx="2"/>',
        "Performance": '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
        "Training": '<path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
        "Settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0 .73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43-.25a2 2 0 0 1 1-1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 .73 2.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    };

    function inject_section_icons() {
        var found = false;
        try {
            document.querySelectorAll(".section-break .sidebar-item-label").forEach(function (label) {
                var section_name = label.textContent.trim();
                var svg_content = ICONS[section_name];
                if (!svg_content) return;
                var anchor = label.closest(".item-anchor") || label.closest(".sidebar-item") || label.parentElement;
                if (anchor && anchor.querySelector(".section-icon")) return;

                var icon_span = document.createElement("span");
                icon_span.className = "section-icon";
                icon_span.style.cssText = "display:inline-flex;margin-right:6px;vertical-align:middle;flex-shrink:0;";
                icon_span.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + svg_content + '</svg>';
                label.parentNode.insertBefore(icon_span, label);
                found = true;
            });
        } catch (e) {}
        return found;
    }

    var attempts = 0;
    var maxAttempts = 20;
    var timer = setInterval(function () {
        attempts++;
        if (inject_section_icons() || attempts >= maxAttempts) {
            clearInterval(timer);
        }
    }, 300);

    var observer = new MutationObserver(function () {
        inject_section_icons();
    });
    observer.observe(document.body, { childList: true, subtree: true });
});
