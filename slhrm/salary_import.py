# slhrm/salary_import.py
"""Salary package import (v0.2.2): HR fills an xlsx, SLHRM creates / updates Employee Salary Packages on the
current "Standard Staff Structure" version; each package creates its effective-dated SSA (Phase 1.5 rules).

    bench --site … execute slhrm.salary_import.make_template --kwargs '{"path": "/home/rajerp/cc-tmp/salary_import_template.xlsx"}'
    bench --site … execute slhrm.salary_import.run --kwargs '{"file": "/path/file.xlsx", "dry_run": 1}'
Desk: Employee Salary Package list → "Import Salary Packages" (HR Manager / System Manager): upload (private) →
preview_import (dry run) → apply_import → the uploaded file is deleted.

Never invents salaries: the template's amount columns are empty; a row without Basic Salary is skipped and listed.
Idempotent: a row equal to the employee's package (amounts, Effective From, structure, APIT exempt) → "unchanged",
nothing saved. A changed amount with a new Effective From → new SSA from that date; earlier SSAs stay (package rules).
"""
import io
from datetime import date, datetime

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate

SHEET = "Salary Packages"
COL_EMPLOYEE, COL_NAME, COL_BRANCH, COL_DESIGNATION = "Employee ID", "Name", "Branch", "Designation"
AMOUNT_COLUMNS = ("Basic Salary", "Base Allowance", "Vehicle Allowance")  # column header = Salary Component
COL_EFFECTIVE, COL_APIT = "Effective From", "APIT Exempt"
COLUMNS = (COL_EMPLOYEE, COL_NAME, COL_BRANCH, COL_DESIGNATION, *AMOUNT_COLUMNS, COL_EFFECTIVE, COL_APIT)
DEFAULT_EFFECTIVE = "2026-10-01"
ROLES = ("HR Manager", "System Manager")
YES, NO = ("yes", "y", "1", "true"), ("no", "n", "0", "false")


def structure():
    from slhrm.salary_setup import _active_structure

    name = _active_structure()
    if not name:
        frappe.throw(_("No submitted Standard Staff Structure found. Run slhrm.salary_setup.apply first."))
    return name


# ── template ────────────────────────────────────────────────────


def make_template(path=None, effective_from=DEFAULT_EFFECTIVE):
    """xlsx with one row per Active employee (amounts EMPTY) + an Instructions sheet. Returns the path."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    path = path or "/home/rajerp/cc-tmp/salary_import_template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(list(COLUMNS))
    bold, info = Font(bold=True), PatternFill("solid", fgColor="EEEEEE")
    for c in ws[1]:
        c.font = bold
        c.alignment = Alignment(wrap_text=True, vertical="center")
    emps = frappe.get_all("Employee", filters={"status": "Active"},
                          fields=["name", "employee_name", "branch", "designation"], order_by="branch asc, employee_name asc")
    eff = getdate(effective_from)
    for e in emps:
        ws.append([e.name, e.employee_name, e.branch or "", e.designation or "", None, None, None, eff, "No"])
    yn = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    ws.add_data_validation(yn)
    last = ws.max_row
    for r in range(2, last + 1):
        for col in "BCD":
            ws[f"{col}{r}"].fill = info
        for col in "EFG":
            ws[f"{col}{r}"].number_format = "#,##0.00"
        ws[f"H{r}"].number_format = "yyyy-mm-dd"
        yn.add(f"I{r}")
    for col, width in zip("ABCDEFGHI", (14, 32, 14, 22, 14, 14, 14, 14, 11)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "E2"

    ins = wb.create_sheet("Instructions")
    for line in (
        ["Salary package import — instructions"],
        [],
        ["1. Fill Basic Salary, Base Allowance and Vehicle Allowance (monthly, LKR) for each employee. Leave a row's Basic Salary EMPTY to skip that employee."],
        ["2. Base Allowance / Vehicle Allowance empty = 0."],
        ["3. Effective From must be the 1st of a month (prefilled " + eff.isoformat() + "). A later change: put the new amount and a NEW Effective From — earlier months keep the old amounts."],
        ["4. APIT Exempt: Yes / No (sets the employee's APIT exemption)."],
        ["5. Do not change Employee ID. Name, Branch and Designation are for reference only (grey) — they are not imported."],
        ["6. Desk: Employee Salary Package list → Import Salary Packages → upload → check the preview → Apply. The file is deleted after Apply."],
        ["7. Importing the same file again changes nothing (rows that already match are 'unchanged')."],
        [],
        ["Structure: " + structure() + " — Basic Salary, Base Allowance, Vehicle Allowance come from this file; Overtime, Other Allowance and all deductions come from the worksheet / Additional Salary / statutory rules."],
    ):
        ins.append(line)
    ins["A1"].font = Font(bold=True, size=13)
    ins.column_dimensions["A"].width = 140
    wb.save(path)
    print(f"template: {path} ({len(emps)} active employees)")
    return path


# ── reading + parsing ───────────────────────────────────────────


def _content(file):
    """Bytes of the xlsx: a private File url (Desk upload) or a local path (bench execute only)."""
    file = cstr(file).strip()
    if file.startswith(("/private/files/", "/files/")):
        name = frappe.db.get_value("File", {"file_url": file}, "name")
        if not name:
            frappe.throw(_("File {0} not found.").format(file))
        f = frappe.get_doc("File", name)
        if not cint(f.is_private):
            frappe.throw(_("Salary files must be uploaded as private files."))
        return f.get_content()
    if frappe.request:
        frappe.throw(_("Upload the file first."))
    with open(file, "rb") as fh:
        return fh.read()


def read_rows(file):
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(_content(file)), data_only=True, read_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head_idx = next((i for i, r in enumerate(rows) if any(cstr(v).strip().lower() == COL_EMPLOYEE.lower() for v in r)), None)
    if head_idx is None:
        frappe.throw(_("Header row with '{0}' not found.").format(COL_EMPLOYEE))
    header = {cstr(v).strip().lower(): j for j, v in enumerate(rows[head_idx]) if cstr(v).strip()}
    missing = [c for c in (COL_EMPLOYEE, AMOUNT_COLUMNS[0], COL_EFFECTIVE) if c.lower() not in header]
    if missing:
        frappe.throw(_("Missing column(s): {0}").format(", ".join(missing)))
    out = []
    for i, r in enumerate(rows[head_idx + 1:], start=head_idx + 2):
        get = lambda col, _r=r: _r[header[col.lower()]] if col.lower() in header and header[col.lower()] < len(_r) else None  # noqa: E731
        values = {c: get(c) for c in COLUMNS}
        if all(v in (None, "") for v in values.values()):
            continue
        out.append(frappe._dict(row=i, **{c: values[c] for c in COLUMNS}))
    return out


def _amount(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return flt(v, 2)
    s = cstr(v).replace(",", "").strip()
    try:
        return flt(float(s), 2)
    except ValueError:
        raise ValueError(_("not a number: {0}").format(v))


def _date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return getdate(cstr(v).strip())
    except Exception:
        raise ValueError(_("not a date: {0}").format(v))


def _yes_no(v):
    s = cstr(v).strip().lower()
    if not s:
        return None
    if s in YES:
        return 1
    if s in NO:
        return 0
    raise ValueError(_("APIT Exempt must be Yes or No, not {0}").format(v))


# ── run ─────────────────────────────────────────────────────────


def _package_amounts(doc):
    return {r.salary_component: flt(r.amount, 2) for r in doc.components if r.salary_component in AMOUNT_COLUMNS and r.override}


def _build_package(emp, amounts, eff, struct):
    """(doc, existing?) — the employee's package with the file's amounts (not saved)."""
    name = frappe.db.exists("Employee Salary Package", {"employee": emp.name})
    if name:
        doc = frappe.get_doc("Employee Salary Package", name)
    else:
        doc = frappe.new_doc("Employee Salary Package")
        doc.employee = emp.name
        doc.company = emp.company
        doc.payroll_frequency = "Monthly"
    doc.salary_structure = struct
    doc.effective_from = eff
    have = {r.salary_component: r for r in doc.components}
    for comp in AMOUNT_COLUMNS:
        row = have.get(comp) or doc.append("components", {"salary_component": comp})
        row.salary_component_type = "Earning"
        row.amount = flt(amounts.get(comp) or 0, 2)
        row.override = 1
        row.depends_on_payment_days = 0
    return doc, bool(name)


def run(file, dry_run=True):
    """Validate (dry_run) or apply the xlsx. Returns {structure, dry_run, rows, skipped, totals, counts}."""
    dry = cint(dry_run)
    struct = structure()
    data = read_rows(file)
    results, seen = [], {}
    for d in data:
        res = frappe._dict(row=d.row, employee=cstr(d.get(COL_EMPLOYEE)).strip(), employee_name="", branch="",
                           action="", ssa="", message="", **{c: None for c in AMOUNT_COLUMNS}, effective_from=None, apit_exempt=None)
        results.append(res)
        errors = []
        emp = frappe.db.get_value("Employee", res.employee, ["name", "employee_name", "status", "company", "branch",
                                                             "slhrm_apit_exempt"], as_dict=True) if res.employee else None
        if not res.employee:
            errors.append(_("Employee ID missing"))
        elif not emp:
            errors.append(_("Employee {0} not found").format(res.employee))
        else:
            res.employee_name, res.branch = emp.employee_name, emp.branch
            if emp.status != "Active":
                errors.append(_("Employee is {0}, not Active").format(emp.status))
        if res.employee and res.employee in seen:
            errors.append(_("Employee also on row {0}").format(seen[res.employee]))
        seen.setdefault(res.employee, d.row)
        for col in AMOUNT_COLUMNS:
            try:
                res[col] = _amount(d.get(col))
                if res[col] is not None and res[col] < 0:
                    errors.append(_("{0} cannot be negative").format(col))
            except ValueError as e:
                errors.append(f"{col}: {e}")
        try:
            res.effective_from = _date(d.get(COL_EFFECTIVE))
            if not res.effective_from:
                errors.append(_("Effective From missing"))
            elif res.effective_from.day != 1:
                errors.append(_("Effective From {0} is not the 1st of a month").format(res.effective_from))
        except ValueError as e:
            errors.append(f"{COL_EFFECTIVE}: {e}")
        try:
            res.apit_exempt = _yes_no(d.get(COL_APIT))
        except ValueError as e:
            errors.append(cstr(e))
        if errors:
            res.action, res.message = "error", "; ".join(errors)
            continue
        if res["Basic Salary"] is None:
            res.action, res.message = "skipped", _("Basic Salary empty")
            continue

        amounts = {c: flt(res[c] or 0, 2) for c in AMOUNT_COLUMNS}
        doc, existing = _build_package(emp, amounts, res.effective_from, struct)
        apit_change = res.apit_exempt is not None and cint(emp.slhrm_apit_exempt) != res.apit_exempt
        if existing:
            before = frappe.get_doc("Employee Salary Package", doc.name)
            same = (_package_amounts(before) == amounts and getdate(before.effective_from) == res.effective_from
                    and before.salary_structure == struct)
            if same and not apit_change:
                res.action, res.ssa, res.message = "unchanged", _("no change"), ""
                continue
        res.action = "update" if existing else "create"
        frappe.flags.mute_messages = True
        try:
            frappe.db.savepoint("slhrm_salary_import")
            doc.validate()  # package rules (Effective From, components, period open, SSA plan) — reads only
            plan = getattr(doc, "_ssa_plan", None)
            res.ssa = (_("replace SSA from {0}") if plan and plan.replace else _("new SSA from {0}")).format(res.effective_from) \
                if plan else _("no SSA change")
            if apit_change:
                res.message = _("APIT Exempt → {0}").format(_("Yes") if res.apit_exempt else _("No"))
            if not dry:
                doc.save()
                if apit_change:
                    e = frappe.get_doc("Employee", emp.name)
                    e.slhrm_apit_exempt = res.apit_exempt
                    e.save()
                frappe.db.release_savepoint("slhrm_salary_import")
        except Exception as e:
            frappe.db.rollback(save_point="slhrm_salary_import")
            res.action, res.ssa = "error", ""
            res.message = frappe.utils.strip_html(cstr(e))[:300] or type(e).__name__
        finally:
            frappe.flags.mute_messages = False
    if not dry:
        frappe.db.commit()

    totals = {}
    for r in results:
        if r.action in ("create", "update", "unchanged"):
            t = totals.setdefault(r.branch or "-", {"branch": r.branch or "-", "employees": 0, **{c: 0.0 for c in AMOUNT_COLUMNS}, "total": 0.0})
            t["employees"] += 1
            for c in AMOUNT_COLUMNS:
                t[c] += flt(r[c])
                t["total"] += flt(r[c])
    counts = {}
    for r in results:
        counts[r.action] = counts.get(r.action, 0) + 1
    return {"structure": struct, "dry_run": bool(dry), "rows": results,
            "skipped": [r for r in results if r.action == "skipped"],
            "totals": sorted(totals.values(), key=lambda t: t["branch"]), "counts": counts}


# ── Desk endpoints (HR Manager / System Manager) ────────────────


def _check():
    frappe.only_for(ROLES)
    frappe.has_permission("Employee Salary Package", "create", throw=True)


@frappe.whitelist(methods=["POST"])
def preview_import(file_url):
    _check()
    return run(file_url, dry_run=True)


@frappe.whitelist(methods=["POST"])
def apply_import(file_url):
    _check()
    out = run(file_url, dry_run=False)
    _delete_upload(file_url)
    return out


@frappe.whitelist(methods=["POST"])
def discard_import(file_url):
    _check()
    _delete_upload(file_url)
    return {"ok": True}


def _delete_upload(file_url):
    """The uploaded salary file holds pay data: delete it (only a private file the session user uploaded)."""
    name = frappe.db.get_value("File", {"file_url": file_url, "is_private": 1, "owner": frappe.session.user}, "name")
    if name:
        frappe.delete_doc("File", name, ignore_permissions=True, delete_permanently=True)
