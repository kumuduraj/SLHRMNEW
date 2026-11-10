"""v0.0.15: Biometric Device "Served Branches" — every existing device serves its own branch."""
import frappe


def execute():
    for name in frappe.get_all("Biometric Device", pluck="name"):
        d = frappe.get_doc("Biometric Device", name)
        if d.branch and d.branch not in [r.branch for r in d.get("served_branches") or []]:
            d.append("served_branches", {"branch": d.branch})
            d.flags.ignore_permissions = True
            d.save()
