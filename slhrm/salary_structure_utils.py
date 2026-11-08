# slhrm/salary_structure_utils.py
"""Small read-only helpers about Salary Structures (HRMS doctypes, read via the API)."""
import frappe
from frappe import _
from frappe.utils import cint, flt


def get_formula_base_components(salary_structure):
    """Earning components of a structure whose formula is exactly `base` (the SSA base),
    in structure order."""
    if not salary_structure:
        return []
    rows = frappe.get_all(
        "Salary Detail",
        filters={"parent": salary_structure, "parenttype": "Salary Structure", "parentfield": "earnings"},
        fields=["salary_component", "formula", "amount_based_on_formula"],
        order_by="idx asc",
    )
    return [r.salary_component for r in rows if (r.formula or "").strip().lower() == "base"]


def resolve_base_component(salary_structure, components):
    """(component, amount) that becomes the SSA base for an Employee Salary Package.

    - exactly one structure earning with formula `base` -> that component
    - otherwise exactly one package row must have is_base_component ticked
    The component must be an Earning row of the package with an amount > 0.
    """
    auto = get_formula_base_components(salary_structure)
    ticked = [r for r in components if cint(r.get("is_base_component"))]

    if len(auto) == 1:
        component = auto[0]
        others = [r.salary_component for r in ticked if r.salary_component != component]
        if others:
            frappe.throw(
                _("{0} is the base component of Salary Structure {1} (formula 'base'); untick "
                  "'Is Base Component' on {2}.").format(component, salary_structure, ", ".join(others)),
                title=_("Base Component"),
            )
    else:
        if len(ticked) != 1:
            reason = (_("no earning uses formula 'base'") if not auto
                      else _("several earnings use formula 'base' ({0})").format(", ".join(auto)))
            frappe.throw(
                _("Salary Structure {0}: {1}. Tick 'Is Base Component' on exactly one earning row "
                  "(currently {2}).").format(salary_structure, reason, len(ticked)),
                title=_("Base Component"),
            )
        component = ticked[0].salary_component

    row = next((r for r in components if r.salary_component == component), None)
    if not row:
        frappe.throw(_("Base component {0} must be one of the package components.").format(component),
                     title=_("Base Component"))
    if row.get("salary_component_type") and row.salary_component_type != "Earning":
        frappe.throw(_("Base component {0} must be an Earning.").format(component), title=_("Base Component"))
    if flt(row.amount) <= 0:
        frappe.throw(_("Base component {0} needs an amount greater than zero.").format(component),
                     title=_("Base Component"))
    return component, flt(row.amount)
