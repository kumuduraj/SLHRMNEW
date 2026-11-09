"""Employee Salary Package — one per employee; every amount change is EFFECTIVE-DATED.

Each change creates a new submitted Salary Structure Assignment (SSA) from `effective_from`, carrying
a snapshot of the package rows (`slhrm_package_components`). HRMS gives a slip the SSA with the latest
from_date <= the slip's start date, and slhrm.overrides.salary_slip applies THAT SSA's snapshot — so
earlier periods keep their own SSA and amounts.

- SSAs with from_date < effective_from are never cancelled; only an SSA with the exact same from_date is
  replaced (cancelled + recreated).
- Blocked when a submitted Salary Slip or submitted Payroll Worksheet of the employee covers
  effective_from or any later period.
- SSA.base = SUM of the package's earning overrides (intended, Raj 2026-11-08).
"""
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, cint, flt, get_first_day, getdate, today

SNAPSHOT_FIELD = "slhrm_package_components"
SNAPSHOT_KEYS = ("salary_component", "salary_component_type", "amount", "override", "depends_on_payment_days")


def first_day_of_next_month(date=None):
    return get_first_day(add_months(getdate(date or today()), 1))


def package_snapshot(rows):
    """Normalised, comparable list of the package rows (stored on each SSA)."""
    out = []
    for r in rows or []:
        g = r.get if isinstance(r, dict) else (lambda k, _r=r: getattr(_r, k, None))
        out.append({
            "salary_component": g("salary_component"),
            "salary_component_type": g("salary_component_type"),
            "amount": flt(g("amount"), 2),
            "override": cint(g("override")),
            "depends_on_payment_days": cint(g("depends_on_payment_days")),
        })
    return sorted(out, key=lambda x: x["salary_component"] or "")


def load_snapshot(value):
    if not value:
        return None
    try:
        return package_snapshot(json.loads(value))
    except Exception:
        return None


class EmployeeSalaryPackage(Document):
    def onload(self):
        self.set_onload("assignment_history", get_assignment_history(self.employee) if self.employee else [])

    def validate(self):
        if not self.effective_from:
            self.effective_from = first_day_of_next_month()
        self.validate_components()
        self.calculate_totals()
        self.warn_dropped_overrides()
        self._ssa_plan = self.plan_ssa()
        if self._ssa_plan:
            self.validate_period_is_open(getdate(self.effective_from))

    # ── components ────────────────────────────────────────────────

    def validate_components(self):
        if not self.components:
            frappe.throw(
                _("Salary components table is empty. Click 'Load Components' to populate."),
                title=_("No Components"),
            )

        seen = set()
        for row in self.components:
            if flt(row.amount) < 0:
                frappe.throw(
                    _("Row {0}: Amount for '{1}' cannot be negative.").format(row.idx, row.salary_component)
                )
            if row.salary_component in seen:
                frappe.throw(
                    _("Row {0}: Duplicate salary component '{1}'.").format(row.idx, row.salary_component)
                )
            seen.add(row.salary_component)

        has_earning = any(
            row.salary_component_type == "Earning" and row.override and flt(row.amount) > 0
            for row in self.components
        )
        if not has_earning:
            frappe.throw(
                _("At least one Earning component must have an amount greater than zero."),
                title=_("No Earnings"),
            )

    def calculate_totals(self):
        self.total_earning = sum(
            flt(row.amount) for row in self.components
            if row.salary_component_type == "Earning" and row.override
        )
        self.total_deduction = sum(
            flt(row.amount) for row in self.components
            if row.salary_component_type == "Deduction" and row.override
        )
        self.net_total = flt(self.total_earning) - flt(self.total_deduction)

    def warn_dropped_overrides(self):
        """Never zero or drop an existing override silently: list them in the save message."""
        before = self.get_doc_before_save()
        if not before:
            return
        now = {r.salary_component: r for r in self.components}
        lost = []
        for r in before.components:
            if not (r.override and flt(r.amount) > 0):
                continue
            cur = now.get(r.salary_component)
            if not cur:
                lost.append(_("{0}: {1} → removed").format(r.salary_component, frappe.format_value(r.amount, {"fieldtype": "Currency"})))
            elif not cur.override or flt(cur.amount) == 0:
                lost.append(_("{0}: {1} → {2}").format(
                    r.salary_component, frappe.format_value(r.amount, {"fieldtype": "Currency"}),
                    _("structure value") if not cur.override else frappe.format_value(0, {"fieldtype": "Currency"})))
        if lost:
            frappe.msgprint("<br>".join(lost), title=_("Overrides removed or zeroed"), indicator="orange")

    # ── effective-dated SSA ───────────────────────────────────────

    def plan_ssa(self):
        """None if the SSA in force on effective_from already matches; else what to create/replace."""
        eff = getdate(self.effective_from)
        snapshot = package_snapshot(self.components)
        base = flt(self.total_earning)
        in_force = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": self.employee, "docstatus": 1, "from_date": ("<=", eff)},
            ["name", "from_date", "base", "salary_structure", "slhrm_managed", SNAPSHOT_FIELD],
            as_dict=True, order_by="from_date desc",
        )
        if (in_force and cint(in_force.slhrm_managed) and flt(in_force.base) == base
                and in_force.salary_structure == self.salary_structure
                and load_snapshot(in_force.get(SNAPSHOT_FIELD)) == snapshot):
            return None
        same_date = in_force.name if in_force and getdate(in_force.from_date) == eff else None
        return frappe._dict(effective_from=eff, base=base, snapshot=snapshot, replace=same_date)

    def validate_period_is_open(self, eff):
        slips = frappe.get_all(
            "Salary Slip",
            filters={"employee": self.employee, "docstatus": 1, "end_date": (">=", eff)},
            fields=["name", "start_date", "end_date"], order_by="start_date",
        )
        sheets = []
        parents = frappe.get_all(
            "Payroll Worksheet Employee",
            filters={"employee": self.employee, "parenttype": "Payroll Worksheet"}, pluck="parent",
        )
        if parents:
            sheets = frappe.get_all(
                "Payroll Worksheet",
                filters={"name": ("in", list(set(parents))), "docstatus": 1, "end_date": (">=", eff)},
                fields=["name", "start_date", "end_date"], order_by="start_date",
            )
        if not (slips or sheets):
            return
        fmt = lambda d: frappe.format_value(d, {"fieldtype": "Date"})  # noqa: E731
        lines = [_("Salary Slip {0} ({1} – {2})").format(s.name, fmt(s.start_date), fmt(s.end_date)) for s in slips]
        lines += [_("Payroll Worksheet {0} ({1} – {2})").format(w.name, fmt(w.start_date), fmt(w.end_date)) for w in sheets]
        frappe.throw(
            _("Effective From {0} falls in (or before) a period that is already paid for {1}:").format(
                fmt(eff), self.employee_name or self.employee)
            + "<br>" + "<br>".join(lines)
            + "<br>" + _("Choose an Effective From after these periods, or cancel them first."),
            title=_("Period closed"),
        )

    def on_update(self):
        plan = getattr(self, "_ssa_plan", None)
        if plan:
            if plan.replace:
                self._cancel_ssa(plan.replace)
            name = self._create_ssa(plan.base, plan.effective_from, plan.snapshot)
            frappe.msgprint(
                _("Salary Structure Assignment <b>{0}</b> {1}: base {2}, effective {3}.").format(
                    name,
                    _("replaced {0}").format(plan.replace) if plan.replace else _("created"),
                    frappe.format_value(plan.base, {"fieldtype": "Currency"}),
                    frappe.format_value(plan.effective_from, {"fieldtype": "Date"}),
                )
                + ("<br>" + _("Earlier assignments are kept for their periods.") if not plan.replace else ""),
                title=_("Salary Structure Assignment"), indicator="green",
            )
        self._refresh_current()

    def _refresh_current(self):
        """current_ssa = the SSA in force today (else the earliest future one)."""
        fields = ["name", "base"]
        cur = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": self.employee, "docstatus": 1, "from_date": ("<=", today())},
            fields, as_dict=True, order_by="from_date desc",
        ) or frappe.db.get_value(
            "Salary Structure Assignment", {"employee": self.employee, "docstatus": 1},
            fields, as_dict=True, order_by="from_date asc",
        )
        self.db_set("current_ssa", cur.name if cur else None, update_modified=False)
        self.db_set("current_ssa_base", flt(cur.base) if cur else 0, update_modified=False)
        self.db_set("ssa_status", "Active" if cur else "Not Created", update_modified=False)

    def _cancel_ssa(self, ssa_name):
        ssa = frappe.get_doc("Salary Structure Assignment", ssa_name)
        if getdate(ssa.from_date) != getdate(self.effective_from):  # never an earlier period's SSA
            frappe.throw(_("Refusing to cancel {0}: its From Date is not the Effective From.").format(ssa_name))
        if ssa.docstatus == 1:
            ssa.flags.ignore_permissions = True
            ssa.cancel()

    def _create_ssa(self, base, from_date, snapshot):
        ssa = frappe.new_doc("Salary Structure Assignment")
        ssa.employee = self.employee
        ssa.salary_structure = self.salary_structure
        ssa.company = self.company
        ssa.from_date = from_date
        ssa.base = base
        ssa.slhrm_managed = 1
        ssa.slhrm_package_link = self.name
        ssa.set(SNAPSHOT_FIELD, json.dumps(snapshot))
        if self.income_tax_slab:
            ssa.income_tax_slab = self.income_tax_slab
        ssa.flags.ignore_permissions = True
        ssa.insert()
        ssa.submit()
        return ssa.name

    def on_trash(self):
        existing = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": self.employee, "slhrm_managed": 1, "docstatus": 1},
            "name", order_by="from_date desc",
        )
        if existing:
            ssa = frappe.get_doc("Salary Structure Assignment", existing)
            ssa.flags.ignore_permissions = True
            ssa.cancel()
            frappe.msgprint(
                _("SSA {0} cancelled because the Employee Salary Package was deleted.").format(existing),
                indicator="orange",
            )


def get_assignment_history(employee):
    rows = frappe.get_all(
        "Salary Structure Assignment",
        filters={"employee": employee, "docstatus": ("in", (1, 2))},
        fields=["name", "from_date", "base", "docstatus", "salary_structure", "slhrm_managed", "modified"],
        order_by="from_date desc, creation desc",
    )
    in_force = frappe.db.get_value(
        "Salary Structure Assignment",
        {"employee": employee, "docstatus": 1, "from_date": ("<=", today())}, "name", order_by="from_date desc",
    )
    for r in rows:
        r.status = ("Cancelled" if r.docstatus == 2 else "In force today" if r.name == in_force
                    else "Future" if getdate(r.from_date) > getdate(today()) else "Earlier period")
    return rows


def _structure_rows(salary_structure):
    structure = frappe.get_doc("Salary Structure", salary_structure)
    out = []
    for table, typ in (("earnings", "Earning"), ("deductions", "Deduction")):
        for row in structure.get(table):
            comp = frappe.get_cached_doc("Salary Component", row.salary_component)
            is_formula = cint(row.amount_based_on_formula)
            out.append({
                "salary_component": row.salary_component,
                "salary_component_type": typ,
                # formula rows: no number to put in -> structure formula applies (override 0), never "0 overridden"
                "amount": 0 if is_formula else flt(row.amount),
                "override": 0 if is_formula else 1,
                "default_formula": row.formula or "",
                "default_amount": flt(row.amount),
                "depends_on_payment_days": cint(comp.depends_on_payment_days),
            })
    return out


@frappe.whitelist()
def plan_load_components(salary_structure, components=None):
    """What 'Load Components' would do — nothing is written.

    keep:   rows already in the package (amounts untouched)
    add:    structure components missing from the package (amount = structure default)
    remove: package rows no longer in the structure (the user decides)
    """
    if not salary_structure:
        frappe.throw(_("Please select a Salary Structure."))
    frappe.has_permission("Employee Salary Package", "write", throw=True)
    current = json.loads(components) if isinstance(components, str) else (components or [])
    struct = _structure_rows(salary_structure)
    in_struct = {r["salary_component"] for r in struct}
    have = {r.get("salary_component") for r in current}
    return {
        "keep": [
            {k: r.get(k) for k in ("salary_component", "salary_component_type", "amount", "override")}
            for r in current if r.get("salary_component") in in_struct
        ],
        "add": [r for r in struct if r["salary_component"] not in have],
        "remove": [
            {k: r.get(k) for k in ("salary_component", "salary_component_type", "amount", "override")}
            for r in current if r.get("salary_component") not in in_struct
        ],
    }


@frappe.whitelist()
def get_active_ssa_structure(employee):
    if not employee:
        frappe.throw(_("Please select an Employee."))

    return frappe.db.get_value(
        "Salary Structure Assignment",
        filters={"employee": employee, "docstatus": 1},
        fieldname=["salary_structure", "base", "from_date", "income_tax_slab"],
        order_by="from_date desc",
        as_dict=True,
    )
