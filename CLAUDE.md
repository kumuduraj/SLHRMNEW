# SLHRM — working notes

Frappe v16 app (ERPNext + HRMS) by Evonet: biometric attendance, payroll add-ons, and an
employee PWA at `/slhrm`. Repo: github.com/kumuduraj/SLHRMNEW (branch `master`).

## HARD RULE — NO CORE CHANGES
frappe, erpnext and hrms will be upgraded later; SLHRM must survive that untouched.
- Never edit anything under `apps/frappe`, `apps/erpnext`, `apps/hrms`. No monkey-patching of their modules.
- No `override_doctype_class`, no `override_whitelisted_methods` on hrms/frappe methods.
- Extend only via: slhrm fixtures (Custom Field / Property Setter, module `SLHRM`, fieldnames
  prefixed `slhrm_`), `doc_events`, slhrm whitelisted APIs, slhrm DocTypes, standard docs created
  through the API (Additional Salary etc.), and the SLHRM PWA (our own code).
- Never reuse an hrms/frappe fieldname for a custom field. If hrms may add a field later, use an
  `slhrm_`-prefixed field instead, so an upgrade can't collide with it.
- Never modify core-owned records (other apps' workspaces, sidebars, pages, desktop icons) and never
  run raw SQL against core tables. SLHRM's own desk records ship as app JSON (see Layout).
- Before finishing any task, paste `git -C apps/frappe status --short`, `git -C apps/erpnext status --short`
  and `git -C apps/hrms status --short`; all must be clean.

## HARD RULE — BIOMETRIC DEVICES ARE READ-ONLY, ALWAYS (Raj, 2026-11-09, permanent)
- Never change anything on any biometric device: no clear (attendance/data), no set time, no user /
  fingerprint / face / card changes, no enable/disable, no restart/poweroff/unlock/voice, no config.
- Applies to EVERY device (HRM's and the old tool's on hr.gillsinternational.com), every session, every
  script, every command — tests included. Throwaway tests use fake connections only.
- Code: the agent makes pyzk calls only via `device_call()` (allowlist `ALLOWED_DEVICE_CALLS`, explicit
  `FORBIDDEN_DEVICE_CALLS`; refused before the connection is touched); `ReadOnlyDevice` exposes nothing else.
  Unit tests assert every forbidden method raises and every pyzk method is classified. Never import pyzk in a
  helper script — use the agent. Wrong clock / users on a device → tell Raj; it's fixed on site.

## Session rule — root vs rajerp (Raj, 2026-11-11, standing for all SLHRM sessions)
- Start every task with `id`.
- **`id` is root:** allowed, but run EVERY command via `sudo -u rajerp -H bash -lc '…'`. Never write, create or move
  any file as root. Never run python / bench / git directly as root — not even read-only, and never from inside an
  app folder (a root `python3` in `apps/frappe/frappe` imported frappe's `types` package and wrote root-owned
  `__pycache__/*.pyc` there, 2026-11-10).
- **`id` is rajerp:** run commands directly.
- Task start: create a rajerp-owned marker (`touch ~/cc-tmp/task_start_<date>_<task>` as rajerp). Task end:
  `find /home/rajerp -newer <marker> ! -user rajerp -not -path '*/frappe-bench/logs/*'` must print nothing; if it
  does, replace the file with a rajerp-owned copy (or remove a stray cache file as rajerp) or report it.

## Production
- Bench `/home/rajerp/GILLSHR`, user `rajerp`, site `hrm.gillsinternational.com`.
- App checkout: `/home/rajerp/GILLSHR/apps/slhrm` (production mode under supervisor).
- Run every bench/git command as `rajerp`, e.g. `sudo -u rajerp -H bash -lc 'cd /home/rajerp/GILLSHR && ...'`.

## Workflow
1. Edit in a dev clone (`/home/rajerp/dev/SLHRMNEW`), one conventional commit per change, push to `master`.
2. On prod: `git -C apps/slhrm pull` → `bench --site hrm.gillsinternational.com migrate` →
   `bench build --app slhrm` → `clear-cache` + `clear-website-cache` → restart.
- **Never edit `apps/slhrm` directly. Never run git as root** (root-owned files break later pulls).
- No changes to frappe/erpnext/hrms core. No nginx changes are needed for SLHRM.
- **Before every commit: `tools/check.sh`** must print `CHECK PASSED` (pyflakes: 0 undefined names in
  `slhrm/`, 0 findings in changed `.py` files; every `slhrm` module imports). pyflakes lives in the
  bench venv (`/home/rajerp/GILLSHR/env/bin/pip install pyflakes`). Legacy files with old unused
  imports are cleaned when a phase touches them.
- **Smoke tests CALL every whitelisted endpoint touched in the phase** (throwaway data or minimal args)
  — importing a module proves nothing about code inside its functions.
- **Every deploy report includes** `git -C apps/<app> status --short` for frappe, erpnext, hrms **and**
  slhrm, plus prod HEAD vs `upstream/master` — no exceptions.
- **Restart (Raj, 2026-11-09):** after a SUCCESSFUL deploy you may restart ONLY this bench yourself:
  `supervisorctl restart GILLSHR-web: GILLSHR-workers:` — then confirm every GILLSHR process
  (gunicorn master + workers, schedule, short/long workers, socketio) started after the restart.
  Never restart, stop or reload any other bench (AgroPublic, Gills, frappe-bench, frappe-bench-promo, …),
  nginx, redis or the server. If the restart fails, stop and tell Raj.

## Layout
- The live Python package is `slhrm/`. The repo root holds only packaging files
  (`pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`), `SLHRM-PWA/`, `SLHRM-AGENT/` and `slhrm/`.
  **Never recreate root-level duplicates** of `api.py`, `hooks.py`, `install.py`, `public/` etc.
- Module folder `slhrm/slhrm/` (module "SLHRM") holds committed symlinks
  `doctype`, `fixtures`, `page`, `print_format`, `public`, `workspace`, `workspace_sidebar` → `../`.
- Desk records are standard app files synced by `bench migrate` (bump `modified` when editing):
  Workspace `slhrm/workspace/slhrm/slhrm.json`, Page `slhrm/page/slhrm_dashboard/slhrm_dashboard.json`
  (module folder), Workspace Sidebar `slhrm/workspace_sidebar/slhrm.json` and Desktop Icon
  `slhrm/desktop_icon/slhrm.json` (app-level folders), Print Format
  `slhrm/print_format/payroll_worksheet/payroll_worksheet.json` (module folder). A standard record
  without its JSON file is deleted by Frappe's orphan cleanup on migrate.
- Every doctype folder needs an `__init__.py`.
- Patches: `slhrm/patches/vX_Y_Z/*.py`, registered in `slhrm/patches.txt`.
- Version: `slhrm/__init__.py` `__version__`; `hooks.app_version` imports it. Keep
  `pyproject.toml` / `setup.py` / `setup.cfg` in step.

## Rules
- **Custom Fields / Property Setters live in `slhrm/fixtures/*.json` only** (module `SLHRM`,
  name `<DocType>-<fieldname>`). No `after_migrate` / `after_install` creators.
- Remove old fields or doctypes with a patch, not ad-hoc code in hooks.
- Every path in `app_include_js` / `app_include_css` must exist under `slhrm/public/`.
  Form scripts belong in the doctype folder, not in `public/js` (unless wired via `doctype_js`).
- Device endpoints (`device_ingest`, `device_heartbeat`, legacy `device_punch`, `device_punch_bulk`) are
  `allow_guest`; they must call `_validate_device_api_key()` first, and that check must fail closed
  (disabled/unset/wrong → 403). New endpoints pass `header_only=True` (key only in `X-Device-Key`).
- `install.execute` / `install.after_migrate` only ensure the SLHRM Module Def, the "Attendance Supervisor" role
  (v0.2.0) and the Custom DocPerm base copy (v0.2.1) via the API. Keep them idempotent and API-based; no raw SQL, no
  file writes into the app.
- Custom fields carry the `slhrm_` prefix (Employee: `slhrm_biometric_section`,
  `slhrm_biometric_device_id`, `slhrm_biometric_device_name`, `slhrm_epf_no` = EPF No., after Employee
  Number — HRMS v16 Employee has no EPF/provident-fund field). Check that every `insert_after`
  anchor exists in the current core JSON.

## Overtime (OT) flow
`Attendance Marker` → `Payroll Worksheet` → `Additional Salary` → `Salary Slip`
- **`slhrm/overtime.py` is the only OT math** (pure functions: `early_late_minutes`, `excused`, `calculate_ot_hours`,
  `calculate_ot_rate`, `calculate_ot_amount`; v0.2.0 rule, see the v0.2.0 section; the OT RATE is still SLHRM Settings
  default_ot_rate). Never compute OT
  anywhere else — the worksheet JS calls `slhrm.api.calc_worksheet_row`. Unit tests: `slhrm/tests/test_overtime.py`
  (UnitTestCase only; run with `CI=1 bench --site … run-tests --app slhrm --module
  slhrm.tests.test_overtime --skip-before-tests` — do not set `allow_tests` on production).
- ONE OT type since v0.2.0 (Normal / Double removed).
  HRMS v16 resolves holidays only via **Holiday List Assignment** (employee, else company);
  `Employee.holiday_list` is ignored.
- **Worksheet = HRMS Salary Slip preview + OT. Never duplicate HRMS pay math.**
  `slhrm/payroll_preview.build_preview` builds an in-memory Salary Slip with HRMS's own methods
  (`get_working_days_details` → `check_sal_struct` → `make_salary_slip(structure, slip)`), applies
  `overrides.salary_slip.apply_salary_rules` (same entry point as the real slip's hook) and
  returns its earnings/deductions/gross/net/payment days/LWP. **The preview must never write:** no
  insert/save/commit, no `slip.validate()` (check_existing throws), no `get_emp_and_working_day_details`
  (loan accrual writes when lending is installed); every preview runs inside a savepoint that is rolled
  back. `slhrm/payroll_pay.py`: gross = preview gross + OT; deductions = preview
  deductions (+ loan); net = gross − deductions. Additional Salary is already inside the preview
  (display totals only); the worksheet's own OT Additional Salary is dropped from previews.
- OT edits (`calc_worksheet_row`, `_recalculate_all`) never rebuild previews; "Refresh Salary Data"
  does (keeps OT edits). >100 employees → background job (`run_payroll_job`, realtime
  `slhrm_payroll_progress`, result via `get_payroll_job_result`). Rows with `row_error` block submit.
- Tax components use gross INCLUDING OT on the final slip, so the worksheet shows them without OT
  (UI note says so). EPF/ETF count OT only if the OT component is flagged `slhrm_epf_applicable`
  (not the default) — if one is ever flagged, the worksheet (OT dropped from the preview) would differ.
- Eligibility: `Employee.slhrm_ot_eligible`. Always re-read on the server; ineligible → 0 everywhere.
- Marker (`slhrm/attendance.py`): punches = Biometric Punch Log for all + Employee Checkin for
  `slhrm_allow_app_checkin`; window = shift start − `shift_match_window_before` … shift end +
  `ot_punch_window_after`. **One punch → one employee-day (v0.0.16):** the window is cut at the midpoint between
  the previous day's shift end and this shift's start (and this end / next start); neighbour shifts = submitted
  marker row of D−1 / D+1, else `default_shift`. Truly overlapping shifts → no automatic IN/OUT, warning
  "Overlapping shifts" (HR enters times). Punches used by another date's submitted marker are skipped.
  **Overnight:** row field `out_next_day` ("OUT next day"; loader ticks it when the OUT punch is after midnight,
  server whenever OUT < IN). IN = shift date + in_time, OUT = (D+1 if ticked) + out_time — `attendance.combine` /
  `span_hours` everywhere (worked hours, OT, HRMS Attendance on submit). Manual edits: `slhrm.api.calc_attendance_times`
  (no writes); > 16 h → warning, not blocked. Known limit: an IN after midnight (late start of a night shift) is
  still on the shift date (accepted limit, Raj 2026-11-10).
  **Mark days in order**: D+1 only knows D's night shift from D's SUBMITTED marker (or default_shift). Saving /
  submitting a marker whose previous day (same branch) is not submitted shows a warning (never blocks); the form
  shows the previous day's status (`slhrm.api.marker_previous_day`). Marker grid: Employee Name only (the
  Employee link is in the row editor); short labels Shift / IN / OUT / OUT +1 / Hrs / Late In / Early Out / OT (v0.2.0)
  with the full meaning in each field's description (Frappe v16 has no grid-only label; row editors copy grid.docfields), grid
  columns sum to 10 (Employee Name 2, others 1); per-row OT lock = `grid_row.toggle_editable` (v16 has no
  `grid_form.set_df_property`).
- Shift Types (2026-11-10, hours first so the grid shows the hours; no employee assigned yet): 03-12 Dawn,
  06-15 Early, 08-17 Day, 10-19 Morning, 12-21 Noon, 15-24 Evening (ends 00:00 next day), 21-06 Night; all auto
  attendance 0, no holiday list (Company Holiday List Assignment applies). HRMS ships Shift Type without
  allow_rename: rename only while nothing references a shift, with `frappe.rename_doc(..., merge=False, force=True)`. Rows keep `calc_ot` (server-computed) and approved
  `ot_hours` (v0.2.0, one OT type).
- Worksheet sums submitted markers' approved hours (`slhrm/payroll_ot.py`), rates from overtime.py.
  On submit: one Additional Salary per employee with OT (SLHRM Settings ot_component,
  `ref_doctype`/`ref_docname` = the worksheet). On cancel: blocked if a submitted Salary Slip uses it,
  else the Additional Salary is cancelled + deleted. `load_payroll_data` excludes Additional Salary
  with `ref_doctype = 'Payroll Worksheet'` (no double count).
- **Permlevel 1** = OT hours/rates on Marker Detail and Worksheet Employee: read for HR roles, write only
  HR Manager / System Manager. Frappe resets level-1 child fields only for *existing* docs and only
  *before* `validate`, so the controllers enforce it themselves (new rows → calculated values,
  existing rows → stored values, for users without level-1 write).
- Employee Salary Package overrides (`overrides/salary_slip.py`) must never include the OT components.
- **Employee Salary Package: SSA.base = SUM of all package earning overrides — intended (Raj,
  2026-11-08).** Don't change it. Since v0.0.9 EPF/ETF no longer use `base` (see EPF / ETF below).
- **Worksheet table** (component columns, OT, Gross, deductions, Total Ded, Net, EMPLOYER group) is
  defined once in `slhrm/payroll_table.py` (print format jinja method `worksheet_table`, Excel
  `download_worksheet_xlsx`) and mirrored by `build_table` in `payroll_worksheet.js` — change both.
  Rows render from `components_json` (stored HRMS preview breakdown), never recomputed.
  Desk table: EMPLOYER group collapsed by default; toggle per user in localStorage `slhrm_pw_employer`
  (`{user: 0|1}`, try/catch). Group visibility is decided by the GROUP key for header row 1, header
  row 2, body and totals alike. Number cells (`pw-num`, currency `pw-money`) are nowrap + right-aligned;
  the table scrolls inside `.pw-scroll`. Print format: `white-space: nowrap` on all cells.
- **Statistical components** (statistical_component / do_not_include_in_total, e.g. employer EPF 12%,
  ETF 3%): HRMS v16 evaluates them but never adds slip rows, and resets `slip.data` per pass. The
  preview re-runs HRMS's own `add_structure_component()` on a copy of the context to read them. They
  appear ONLY in the EMPLOYER group — never in Total Ded / Net.

## Employee Salary Package (v0.0.10) — effective dating
- Every amount change applies from **Effective From** (reqd; **must be the 1st of a month** — validated on
  save, Raj 2026-11-09; default first day of next month — the form
  re-defaults it on the first amount change of an edit unless the user picked a date). On save the
  package creates a NEW submitted SSA from that date with a snapshot of its rows
  (`SSA.slhrm_package_components`, fixture). SSAs with an earlier from_date are never cancelled; only an
  SSA with the exact same from_date is replaced. No change vs the SSA in force on that date → no new SSA.
- **Overrides are dated**: `overrides.salary_slip.apply_package_overrides` applies the snapshot of the
  SSA the slip uses (HRMS `set_salary_structure_assignment`: latest submitted SSA with
  from_date <= the slip's START date — a mid-month Effective From therefore applies from the next
  period). A non-package SSA → no overrides. Never read the package's live rows for a slip
  (only legacy SSAs without a snapshot; patch v0_0_10 backfilled them).
- Blocked (message names them) when a submitted Salary Slip or submitted Payroll Worksheet of the
  employee ends on/after Effective From.
- "Assignment history" on the form: all SSAs (from_date, base, in force / future / earlier / cancelled).
- **Load Components never replaces amounts** (`plan_load_components`, no writes): keeps existing rows,
  adds structure components missing from the package (amount = structure default; formula rows
  override 0 = structure formula), lists rows not in the structure as "Remove?" for the user to tick.
  The dialog lists kept / added / removable rows with amounts. Saving a package that zeroes or drops
  an existing override shows an "Overrides removed or zeroed" message.

## Salary structure + APIT (v0.1.0)
- Setup: `bench --site … execute slhrm.salary_setup.apply` (`--kwargs '{"dry_run": 1}'` first). Idempotent; creates
  missing components, reuses existing ones (only depends_on_payment_days of Basic Salary / Base Allowance and SLHRM's
  own fields are set on them), fills SLHRM Settings (OT component Overtime, APIT component, APIT slabs) and updates
  "Standard Staff Structure" by cancel + amend when no SSA uses it (else "<name> v2"). Frappe names an amendment
  "<name>-1", "-2"…; `_active_structure()` finds the newest. Once SSAs exist the structure is never amended again
  (v2 path). To tidy a chain nobody uses: clear amended_from, delete the cancelled versions, rename_doc back (2026-11-11).
- Earnings: Basic Salary, Base Allowance, Vehicle Allowance (package, 0 in the structure, dpd 0), Overtime
  (worksheet → Additional Salary; v0.2.0 renamed from Normal OT, Double OT retired), Other Allowance (Additional Salary). Deductions: Death Donation 200
  (structure, dpd 0), No Pay / Other Deduction / Salary Advance / Personal Loan (Additional Salary only),
  EPF Employee 8% (apply_epf), APIT (apply_apit). Statistical: EPF Employer 12%, ETF Employer 3%.
- **No Pay is entered manually** (Additional Salary) → Basic / Base Allowance do NOT depend on payment days (no double
  deduction). Payroll Settings payroll_based_on stays "Leave". Salary Component `slhrm_reduces_epf_base` (No Pay):
  subtracted from the EPF base AND the APIT taxable amount. OT is never in the EPF base.
- **APIT** (`slhrm/statutory.py`): taxable = all slip earnings (incl. OT, Other Allowance) − No Pay; progressive sum over
  SLHRM Settings "APIT Slabs" (child `SLHRM APIT Slab`; set with the latest effective_from ≤ period start), 2 dp;
  Employee `slhrm_apit_exempt` → 0. `apply_salary_rules` = package overrides → apply_epf → **apply_apit** (real slip
  before_save / before_submit + preview). Worksheet: preview APIT excludes worksheet OT; row `apit_amount` =
  APIT(apit_taxable_base + OT) replaces it in total_deduction (`payroll_pay.compose_pay`,
  `_recalculate_all`, `calc_worksheet_row`) → worksheet == final slip. Change slabs in SLHRM Settings, never in code. Slabs = annual table / 12 with EXACT thresholds
  (150,000 / 233,333.33 / 275,000 / 316,666.67 / 358,333.33; Raj 2026-11-10) so each full band yields 5,000 / 7,500 /
  10,000 / 12,500; reload with `salary_setup.replace_apit_slabs`.
- Worksheet columns: Additional Salary lines have their own component column (no "Additional" bucket); fixed columns
  (shown even when empty) = `salary_setup.WORKSHEET_FIXED_EARNINGS` / `WORKSHEET_FIXED_DEDUCTIONS`, stored per row in
  components_json.fixed_columns; the APIT cell = row apit_amount. Python `payroll_table.build_table` and JS mirror.

## EPF / ETF (v0.0.9, `slhrm/statutory.py`)
- **One entry point:** `overrides.salary_slip.apply_salary_rules(slip)` = package overrides →
  `statutory.apply_epf`. Hooked on Salary Slip `before_save` AND `before_submit` (submit runs
  validate + before_submit, never before_save, and HRMS validate resets rows) and called by the
  worksheet preview. Never call `apply_package_overrides` alone; never add another totals step after it.
- Salary Component fields (fixtures): `slhrm_epf_applicable` (earnings: final amount counts toward the
  EPF base), `slhrm_epf_rate` (deductions + statistical: % of the base).
- `epf_base` = sum of the FINAL (prorated, post-package) earning rows whose component is applicable.
  Rated deduction rows → `round(epf_base × rate / 100, 2)`; a rated deduction the structure lists but
  HRMS dropped as zero is added back. Rated statistical components → same value, returned as EMPLOYER
  lines, never in totals. Totals via HRMS `get_component_totals` / `set_net_pay` (no hand-rolled sums).
- **Structure formulas of rated components (EPF8/EPF12/ETF3 `base * 0.08` etc.) stay in the structure
  only so the rows exist; their values are ALWAYS replaced by apply_epf.** Changing such a formula has
  no effect — change `slhrm_epf_rate` instead.
- Flags: `salary_setup.apply` (BS/BA/VA applicable; EPF8 8, EPF12 12, ETF3 3) and
  `demo.data.set_epf_flags` (DEMO Basic/BRA; DEMO EPF 8/12/3) — idempotent, SLHRM fields only.
- Not mirrored into HRMS v16 `employer_contributions`: Payroll Entry books a JV for every row there
  (`make_employer_contribution_jv_entry`, needs per-component expense/liability accounts).

## DEMO data (`slhrm/demo/data.py`, bench execute only — never whitelisted)
- **Removed from production (hrm.gillsinternational.com) on 2026-11-09** (v0.0.11). The code stays for
  dev / test sites: `create()` refuses unless site_config has `"slhrm_allow_demo": 1` (absent = refused;
  never set it on production) and also refuses if non-DEMO Employees exist.
- **Tests on production use throwaway data only**: create the minimum records, run the check, delete
  them and print proof that each one is gone (plus no Error Log rows left behind). **Teardown via
  `slhrm.testing.delete_throwaway(doctype, name)`** (cancel + permanent delete, no "Deleted Document" copy and no
  "Deleted" Comment); the "counts before = after" proof MUST include `Deleted Document` and `Comment` (and Version).
  Name every test record with a marker (`T27-…`, `SLHRMT…`) so it can be told apart from real data.
  Every `delete_doc` enqueues `delete_dynamic_links` AFTER commit (it removes comments etc. linked to the deleted
  record): wait until the `default` queue is empty before taking the "after" counts. Bulk deletes (hundreds) in
  batches, waiting for the queue between batches — Frappe refuses new jobs above 550 queued ("QueueOverloaded");
  the 2026-11-10 trail purge (1,104 deletes) hit this and blocked a teardown for ~3 min.
- `...create`, `...report`, `...preview_payroll`, `...remove` (`--kwargs '{"dry_run": 1}'` lists every
  record, counts per doctype, and every record OUTSIDE the set that links into it).
- Every created doc is listed in the private File `slhrm_demo_manifest.json`; `remove()` deletes those
  plus records hooks/testing create for DEMO employees, DEMO branches or DEMO users (incl. HRMS PWA
  Notifications), and restores SLHRM Settings. `remove()` deletes with `force=1` (no link check) — run the
  dry run first.
- **Expected DEMO payroll, Oct 2026 (v0.0.9, confirmed by Raj 2026-11-08)** — reference for a dev site with
  the DEMO data; any change needs an explanation:

  | Emp | Pay days | Gross | EPF 8% | Employer 12% / 3% | Net |
  |---|---|---|---|---|---|
  | E01 | 25 | 193152 | 12280 | 18420 / 4605 | 180872 |
  | E02 | 25 | 138477 | 9880 | 14820 / 3705 | 128597 |
  | E03 | 23 (2 LWP) | 99516 | 5041.60 | 7562.40 / 1890.60 | 94474.40 |
  | E04 | 25 | 72943 | 4680 | 7020 / 1755 | 68263 |
  | E05 | 25 | 107896 | 5880 | 8820 / 2205 | 102016 |
  | E06 | 25 | 81827 | 5720 | 8580 / 2145 | 76107 |
  | E07 | 25 | 51000 | 3880 | 5820 / 1455 | 47120 |
  | E08 | 25 | 113075 | 7880 | 11820 / 2955 | 105195 |
  | E09 | 25 | 101368 | 7080 | 10620 / 2655 | 94288 |
  | E10 | 25 | 81000 | 6280 | 9420 / 2355 | 74720 |
  | E11 | 25 (package) | 128099 | **9080** | 13620 / 3405 | 119019 |
  | E12 | — | row error: no SSA | | | |

  E11 EPF = 8% of FINAL DEMO Basic + BRA (110000 + 3500). The pre-v0.0.9 9400 (formula on SSA base
  114000 + 3500) is obsolete.

## Employee logins + forced password change (v0.0.11, `slhrm/user_setup.py`)
- Employee `after_insert` → `user_setup.create_employee_user`. **Never a fixed password.** Outgoing email
  deliverable (enabled outgoing Email Account or `mail_server`, emails not muted) → User with
  `send_welcome_email=1` (Frappe set-password link). Otherwise → random 12-char password (`secrets`) +
  `User.slhrm_must_change_password = 1`, shown ONCE to the session user (msgprint in the response only:
  never Error Log / Comment / Version / log).
- **Data Import never shows a password**: Frappe's importer keeps `message_log` across successful rows
  and writes it into the Data Import Log of a later FAILED row. Imported employees get a random password
  nobody sees; HR uses Employee → Actions → **Issue Temporary Password**
  (`user_setup.issue_temporary_password`, HR Manager / System Manager, POST, only for users whose roles ⊆
  Employee / Employee Self Service / Desk User; never self / Administrator).
- No email on the employee → no user. Interactive: an alert. Data Import: ONE Info Comment on the Data
  Import ("SLHRM user creation summary"), rebuilt from the DB per row — no Error Log per employee.
- **Must change** = flag 1 AND `last_password_reset_date` empty. Frappe's own `update_password`
  (/update-password page, PWA ChangePassword) sets that date, so a real change ends it and the flag is
  cleared lazily. No core hook fires on a password change (it writes `__Auth` + `db.set_value`) — don't
  look for one. `clear_must_change_password` can't clear without a real change.
- Enforcement: `auth_hooks` → `enforce_password_change` (every request, AFTER cookie / token / API-key
  auth; `before_request` runs before token auth): GET `/desk`, `/app`, `/slhrm` → 302 `/update-password`
  (for `/slhrm` it sets Frappe's `redirect_after_login` so the user returns to the PWA); `/api/*` → 403
  "Password change required" except `ALLOWED_METHODS` (login, logout, update_password,
  test_password_strength, the two slhrm check/clear endpoints); `/private/files/*` → 403.
  `on_session_creation` can't redirect (`set_user_info` overwrites `home_page` after it) — the 302 on
  `/desk` does it. `extend_bootinfo` + `slhrm.js` redirect a Desk that booted anyway.
- Cache: `slhrm_must_change_pw` hash caches only "no change needed" (0); flag set → `_forget(user)`;
  User `on_update` → `_forget`.
- Prod has NO outgoing Email Account (only "Jobs", outgoing off) → every new login gets a temporary password.

## Biometric ingestion (Phase 2.0–2.2, v0.0.14)
- **Devices are READ-ONLY, always.** Agent `SLHRM-AGENT/slhrm_agent.py` (runs outside the bench, own venv
  `~/slhrm-agent/venv`, config `~/slhrm-agent/config.json` chmod 600 — never in the repo). Allowed pyzk calls
  only (`ALLOWED_DEVICE_CALLS`): connect, get_serialnumber, get_firmware_version, get_device_name,
  get_platform, get_mac, get_time, read_sizes, get_users, get_attendance, disconnect. Never clear / set_time /
  disable / restart / live_capture / any write. Comm password unknown: 0 then 111111, max 2 attempts, then ask.
- Every raw record stored once: `Biometric Punch Log.punch_key` = `serial|device user id|YYYY-MM-DD HH:MM:SS`
  (device time), **unique DB index**; the agent's SQLite queue uses the same key and re-reads the whole
  device log every pull (INSERT OR IGNORE). Confirmed only by the server's per-record result
  (`slhrm.biometric.ingest`: inserted / duplicate / unknown_employee / skipped_old / error; savepoint per record).
- **Cutoff 2026-11-01** (Raj): SLHRM Settings `biometric_start_date` → older records get `skipped_old` (not stored,
  confirmed by the agent); agent config `min_punch_date` (default for all devices, per-device override) → older
  records are never queued or sent, counted `skipped_old` per pull (log, `device_pull`, `status`). All rows before
  2026-11-01 were deleted on 2026-11-09 (backup `~/cc-tmp/punch_backup_pre_20261101.json.gz`, 600).
- **v0.2.1 supersedes the matching rules below — see "Device ids company-wide (v0.2.1)".**
  Unknown device users are STORED (`employee` empty, status Unmatched) and re-matched when
  the device id is set on the Employee (doc_events `on_update` → `slhrm.biometric.rematch`).
  **Matching scope = the device's SERVED BRANCHES** (v0.0.15): Biometric Device child table `served_branches`
  (`Biometric Device Branch`; the device's own branch is always added on save; `slhrm.biometric.served_branches`).
  DUTCHPUB device serves DUTCHPUB + FORTFUSION (2026-11-10; FORTFUSION has no device). No "anywhere" fallback:
  ids are unique per device scope, not globally (the same id 1 at DUTCHPUB and BRITISHPUB = two different people).
  Device without a branch → nothing matches.
  (a) the ONE Active employee of the served branches whose `slhrm_biometric_device_id` == device user id.
  (b) only if SLHRM Settings `match_device_user_by_employee_number` (ON since 2026-11-09): the ONE Active
  employee of the served branches whose `employee_number` == device user id (trimmed, case-insensitive) AND whose
  name contains the name on the device (`name_sanity`, whole words) → the id is saved on that Employee
  (`link_by_number`, Employee.save → Version). Not linked → Unmatched with `match_reason` ambiguous / conflict
  (id held by another active employee of the served branches, or the hit already has a different id) / name_mismatch.
  **Uniqueness**: Employee `validate` refuses a device id already held by another Active employee in the served
  branches of any device serving the employee's branch; saving a device whose served branches contain a duplicate
  id is refused (list shown).
  **Branch transfer** (Employee `validate` → `on_employee_validate`): changing `branch` clears the device id with a
  message to HR (unless the same save sets a new id, or one device serves both branches — then the id stays);
  punches already matched keep their link.
  `classify_by_number` is the only implementation (ingest, rematch, report, `employee_number_matching` review/apply,
  bench execute only). Never match by Employee name alone.
- `Biometric Device` (name = serial): branch, ip, timezone (punch times converted to the site tz), health
  from `device_heartbeat`. Ingest refuses unknown or disabled serials.
- IN/OUT pairing and OT are NOT decided at ingest (Attendance Marker / `slhrm.overtime`); the marker reads
  only rows with an employee. `punch_type` comes from the device punch state; the raw state is kept.
- **Device API key** lives ONLY in SLHRM Settings `device_api_key` (encrypted Password) and `~/slhrm-agent/config.json`
  `device_key` (chmod 600, owner rajerp). Never print it or put it in logs, the audit file, CLAUDE.md, git or ~/cc-tmp.
  Rotate: generate `secrets.token_urlsafe(32)` in one process → save on SLHRM Settings (device_api_enabled = 1) →
  write the config → verify no key 403 / wrong key 403 / agent heartbeat 200 (show only length + first 4 chars).
- Mapping screen: Script Report "Unmatched Device Users" (`slhrm/report/`, module symlink `slhrm/slhrm/report`);
  "Map to Employee" = `slhrm.biometric.map_device_user` (v0.2.1: any branch — another branch is matched as
  "other branch"; refuses an id held by anyone else); columns Employee No. Hit / Reason show rule (b) live; the dialog
  pre-fills the number hit. Report "Device Users Other Branch" lists other-branch matches.
- Agent scheduler (2026-11-09): rajerp crontab `*/5 … slhrm_agent.py --config ~/slhrm-agent/config.json run` (log
  `~/slhrm-agent/agent.log`); only devices with `enabled: true` in the config are read (DUTCHPUB). DUTCHPUB backfilled
  (27 975 records from 2025-11-04; re-send = all duplicate). `backfill --device N [--resend]` for new devices. Unit tests: `python3 -m unittest discover -s
  SLHRM-AGENT/tests`; server pure functions: `slhrm.tests.test_biometric`.
- Throwaway biometric tests use ids like `T4-1` (and throwaway devices / branches named `T23-…`), never plain numbers: a test employee with id `1` in DUTCHPUB
  would re-match real DUTCHPUB punches of device user 1.
- The old sync tool for hr.gillsinternational.com (`~/frappe-bench/biometric-attendance-sync-tool`) is NOT
  ours: never touch it or its devices (katunayaka_1, wattala_1).

## App check-in
- Allowed only when `Employee.slhrm_allow_app_checkin` and HR Settings
  `allow_employee_checkin_from_mobile_app` are both on. Enforced server-side by doc_events on Employee
  Checkin (`slhrm/overrides/employee_checkin.py`: before_insert + validate) — non-HR users may only
  check in for their own Employee. The PWA reads `slhrm.api.get_app_permissions` for visibility only.
- HRMS's own `Employee.allow_mobile_checkin` / `geolocation_capture` do not exist in v16; don't use them.

## PWA
- Source `SLHRM-PWA/` (Vue 3 + Ionic + frappe-ui 0.1.105). Build:
  `cd SLHRM-PWA && npm ci && npm run build` (`.npmrc` sets `legacy-peer-deps`).
- Output: `slhrm/public/frontend/` (served at `/assets/slhrm/frontend/`) and
  `slhrm/www/slhrm.html` (copied by a vite `closeBundle` plugin, rendered by `slhrm/www/slhrm.py`).
- **Commit the build output** — prod has no `node_modules`. Only one build's hashed files may exist
  (`emptyOutDir: true`; never copy builds on top of each other).
- Routes: `website_route_rules` `/slhrm` and `/slhrm/<path:app_page>` → `slhrm`; router
  `createWebHistory("/slhrm")`.
- Service worker: served by `slhrm.api.pwa_sw` with `Service-Worker-Allowed: /slhrm/`,
  registered with `scope: "/slhrm/"`; precache URLs are absolute (`modifyURLPrefix`).
- `frappe.boot` keys the PWA reads: `push_relay_server_url`, `lang`, `__messages`, `slhrm_formats`
  (`translations_hash` is optional). Add new keys in `slhrm/www/slhrm.py:get_boot`.
- The Employee role may not read System Settings: number/currency formats come from boot
  `slhrm_formats` (`get_formats`; PWA `data/formats.js` `bootFormats()`). Never fetch System Settings in the PWA.

## Lessons (Phase 0, v0.0.2)
- Stale root copies of api/hooks/install/public diverged from `slhrm/` → only `slhrm/` is code; no root duplicates.
- `bench version` crashed: no `__version__` → define it in `slhrm/__init__.py`, derive `app_version`.
- Doctype folders without `__init__.py` weren't importable → every doctype dir gets one.
- `app_include_js` pointed at a non-existent file (404 on every Desk load) → only include files that exist.
- Legacy SSA component editor (JS + 6 API methods + child DocType) was dead after Employee Salary Package → delete replaced designs via a patch, after grepping for callers.
- SSA fields came from an `after_migrate` creator, so a fresh install lacked them and ESP save failed → custom fields via fixtures only.
- Device API skipped auth when disabled, exposing guest punch writes → security checks fail closed, constant-time compare.
- PWA depended on a Docker nginx alias and a build outside `/assets/slhrm` → serve via Frappe www page + `/assets/slhrm/frontend`, commit the build.
- Hard-coded `/home/frappe/frappe-bench` path in `serve_pwa` → never hard-code bench paths; use `frappe.get_app_path()`.
- (v0.0.3) Employee `biometric_*` fields had no `slhrm_` prefix, and their section anchored to `column_break_4`, which ERPNext v16 doesn't have (it landed at idx 0) → prefix every custom field; verify anchors.
- (v0.0.3) Unanchored `.gitignore` scratch patterns (`check_*.py`, …) silently dropped a patch file, so migrate failed with ModuleNotFoundError → scratch patterns are root-anchored (`/check_*.py`); run `git status --ignored` before pushing new files.
- (v0.0.3) install.py deleted the core "Home" workspace and rebuilt the sidebar/page/icon with raw SQL on every migrate, and Frappe's orphan cleanup then deleted the SLHRM icon (no JSON) → ship desk records as app JSON; never touch core records.
- (v0.0.4) `.gitignore`: after every commit, `git status --short --ignored` must show no file you created.
- (v0.0.4) OT was one `actual_overtime` number computed in two places → one OT module (`overtime.py`), Normal/Double split, eligibility from Employee.
- (v0.0.4) `read_only` fields and client-sent values were trusted for OT → controllers recompute on the server; permlevel 1 for approval fields, enforced in `validate` (Frappe skips child resets on new docs).
- (v0.0.4) `load_attendance_data` / `load_payroll_data` had no permission check (any user could read punches/salaries) → every whitelisted data endpoint checks DocType permission.
- (v0.0.4) Mobile check-in relied on a non-existent Employee field and HRMS never checked on the server → app permissions are SLHRM fields enforced by doc_events.
- (v0.0.4) Marker submit/cancel wrote `processing_status` on every punch ref → only Biometric Punch Log refs carry it.
- (v0.0.4) Worksheet `on_submit` called a missing `_create_payroll_entry` → grep callers when renaming methods.
- (v0.0.6) A commit message passed as an inline heredoc inside `sudo -u rajerp bash -lc '...'` hit an apostrophe: bash truncated the message (8bb857f was pushed cut off, without Co-Authored-By) and turned `-> row_error` into a redirect that created a stray file → **commit messages via `git commit -F <file>`** (write the file first; never inline in a quoted shell string); check `git log -1 --format=%B` before pushing.
- (v0.0.6) Re-implementing HRMS salary math in SLHRM (structure formulas, proration, Additional Salary) drifted from the real slip (LWP, overrides) → the worksheet uses HRMS's own Salary Slip calculation as an unsaved preview; SLHRM only adds OT.
- (v0.0.5) The worksheet put structure components into `additional_earning_total` and added `base` on top, so gross counted base twice; structure amounts were also computed twice (with and without package overrides) and the JS recomputed totals itself → one pay module (`payroll_pay.py`), Additional Salary means Additional Salary only, JS displays server values.
- (v0.0.5) The `load_payroll_data` rewrite dropped a local `flt` import; the "smoke test" only imported
  modules, so a NameError shipped and broke the worksheet loader until a follow-up fix + restart
  → `tools/check.sh` (pyflakes + import of every module) before every commit.
- (v0.0.5) Import-only smoke tests can't see errors inside functions → smoke tests call every touched
  whitelisted endpoint with throwaway data / minimal args.
- (v0.0.5) One deploy report omitted the core-app git status → every deploy report lists frappe,
  erpnext, hrms and slhrm status + HEAD vs upstream/master.

- (v0.0.9, 1.4a) A new worksheet opened on Month 01: Frappe's `create_new` pre-fills a required Select
  with its first option, which a stubbed Node harness did not do, so the harness passed while Desk failed
  → **form JS must be verified in a real browser (Playwright, `~/pwtest`, scripts in `~/pw/`, logged in as
  a throwaway test user — the DEMO users are gone since v0.0.11), not a stubbed harness.** Reproduce the bug in the browser first, then fix.
- (v0.0.9, 1.4b) The EMPLOYER toggle hid body cells but not the headers (header loops read `c.group`,
  which only `t.columns` carry) → misaligned columns; found only by measuring the rendered DOM.

- (v0.0.12) PWA `call()` (frappe-ui) resolves to the method's `message` itself — `r.message` was always undefined, so the
  PWA never saw a pending password change → read the resolved value; verify PWA flows in a real browser.
- (v0.0.12) A deliberate `frappe.throw` in a Desk action is an HTTP 417 plus a server traceback in the user's console →
  expected business refusals return a structured `{"refused": msg}`; only permission failures raise.

- (2026-11-11) Deleting "Standard Staff Structure" and then renaming "-2" to that same name in the same run: Frappe's
  `delete_dynamic_links` job (enqueued after commit) later deleted every Version / Comment pointing at the NAME — i.e.
  the renamed structure's history (2 Versions + the rename comment) → after deleting a doc, wait until the `default`
  queue is empty BEFORE renaming another doc to its name.
- (v0.0.14) A docs commit reused a stale commit-message file from the scratchpad, so 258011c (the CLAUDE.md
  handoff + branch-scoped/cutoff docs) carries an old PWA message → write a NEW, uniquely named message file for
  every commit and read `git log -1 --format=%B` BEFORE `git push`.

## Handoff — current state (2026-11-11, v0.2.2, prod = upstream/master = dev)
- Audit trail of every phase: `~/slhrm_audit_20261108.md` (… "Phase 3.0 result", "Phase 3.0 completion after
  restart", "Phase 3.1 result", "Phase 3.2 result"). Read the last sections before starting.
- Version 0.2.2 (`slhrm/__init__.py`, pyproject / setup.py / setup.cfg in step). Last deploy + restart 2026-11-11
  03:13 UTC; all GILLSHR processes confirmed.
- **Employees:** 118 active — DUTCHPUB 45, FORTFUSION 35, BRITISHPUB 22, ALIYA 16. No DEMO data. No user logins
  yet (prod has no outgoing email → temporary passwords). 3 DUTCHPUB employees created from device users with
  placeholder data (HR-EMP-00155 Raveesha 3095, -00156 Dilith 501, -00157 Buddhika Rupasinghe 575; Comment on each).
- **Payroll (v0.1.0–v0.2.2):** "Standard Staff Structure" (every payslip line, zeros kept; the only active structure —
  amendment chain removed and "-2" renamed back on 2026-11-11; legacy "Standard Salary Structure - GHPL" kept, inactive) + components (Overtime,
  Staff Bill, APIT with exact monthly slabs, EPF/ETF via `slhrm.statutory`); print format "SLHRM Payslip" is the Salary
  Slip default. No Employee Salary Package, SSA, marker or worksheet exists yet — **HR fills
  `~/cc-tmp/salary_import_template.xlsx`** (118 active employees, amounts empty, Effective From 2026-10-01) and imports
  it (Employee Salary Package list → Import Salary Packages).
  ONE OT type: (Early In + Late Out)/60 on a working day, all hours on a holiday/weekly off; OT rate = SLHRM Settings
  `default_ot_rate` (currently **0**), Minimum OT Hours 0.
- **Attendance:** 7 Shift Types (03-12 Dawn … 21-06 Night) exist, but **no employee has a shift** → every marker row is
  "No shift" (no OT, no late/early; with no shift the punch window is the whole day, so some rows show ~24 h).
  Role "Attendance Supervisor" exists (no user has it yet); supervisors are scoped by a User Permission on Branch.
- **Holidays:** HRMS v16 uses Holiday List Assignment only. One company assignment: "Holidays 2026-2027 - GHPL"
  (from 2026-04-01) with **5 public holidays and no weekly offs**.
- **Biometric:** only DUTCHPUB (serves DUTCHPUB + FORTFUSION) is registered and enabled; agent every 5 min (rajerp
  crontab, `~/slhrm-agent/`). Cutoff 2026-11-01. Device id = `Employee.attendance_device_id` ("Attendance Device ID
  (all devices)", unique company-wide; 50 employees have one). Punches: ~3,100 matched (Pending), 173 Unmatched
  (device users 571, 572, 576, 13426 — names on the device are "NN-…"). 322 Shanaka (ALIYA) matches as other branch.
  DUTCHPUB clock ~11 min slow (−670 s) — fix on site; the agent never sets device time.
- **Open — waiting for Raj / HR:**
  - **OT rate formula** (today a flat SLHRM Settings rate, 0). `overtime.calculate_ot_rate(employee, base, settings)` is
    the one place to implement it.
  - **GL accounts** on salary components before any Payroll Entry (none set). Earnings: Basic Salary, Base Allowance,
    Vehicle Allowance, Other Allowance, Overtime (+ unused HRMS defaults Basic, Arrear, Leave Encashment). Deductions:
    EPF Employee 8%, APIT, Death Donation, No Pay, Other Deduction, Salary Advance, Personal Loan, Staff Bill (+ unused
    Income Tax). EPF Employer 12% / ETF Employer 3% only if an employer-contribution JV is wanted. Payroll Payable
    default: 2120 - Payroll Payable - GHPL.
  - **BRITISHPUB / ALIYA devices:** unreachable from the VPS; need network access + comm keys (passwords). Then:
    register the Biometric Device (branch, served branches, timezone) → agent `sync_users` (read-only) →
    `bench execute slhrm.biometric.device_id_collisions --kwargs '{"serial": "…"}'` (collisions = re-enrol on site;
    similar / no_name = HR checks) → `backfill --device N` → enable in the agent config. FORTFUSION has no device.
  - **HR data items:**
    - Shifts: set `default_shift` (or Shift Assignments) for every employee — needed for OT and late/early.
    - Supervisor branch permissions: give each supervisor the role "Attendance Supervisor" + a User Permission
      (Allow: Branch, value: their branch).
    - Holiday list assignment: complete "Holidays 2026-2027 - GHPL" (weekly offs, Poya days …) or assign per-branch /
      per-employee lists where branches differ (Holiday List Assignment).
    - Placeholder employee details: gender / DOB / date of joining for HR-EMP-00155, -00156, -00157 (and the earlier
      DUTCHPUB new employees with the same Comment).
    - Device users 571, 572, 576, 13426: identify on site, then "Map to Employee" in Unmatched Device Users.

## Known open items (not yet fixed)
- `SLHRM Settings` fields never read by code: `auto_mark_attendance`, `auto_create_payroll_on_submit`.

## Single OT, early/late, short leave, Attendance Supervisor (v0.2.0)
- ONE OT type everywhere ("OT"; component "Overtime"). `slhrm/overtime.py`: per row whole minutes early_in / late_in /
  early_out / late_out from shift start/end and IN/OUT (incl. OUT +1); OT = (early_in + late_out)/60 on a working day,
  all worked hours on a holiday / weekly off (early/late minutes 0 that day), 0 without shift times, Minimum OT Hours still applies. One entry point
  `attendance.day_figures` (loader, `calc_attendance_times`, marker `_apply_overtime`). Patch v0_2_0.merge_double_ot
  added old double hours into OT and dropped the old columns.
- Marker grid (10 cols): Employee Name 2, Shift, IN, OUT, OUT +1, Hrs, Late In, Early Out, OT. Late In / Early Out orange
  (docfield formatter) unless excused. Short leave (row, permlevel 1): allowance used by Late In first, then Early Out;
  excused values are not counted in the parent "Lates" counts (late_in_count / early_out_count).
- Role "Attendance Supervisor" (install.ensure_roles): Attendance Marker create/write/submit + permlevel 1 (ot_hours,
  short leave). No worksheet / pay permissions. ot_hours != calc_ot → ot_edited_by / ot_edited_on set by the server
  (kept while the value is unchanged); Version (track_changes) keeps the history. Users without level-1 write: ot_hours
  follows calc_ot unless a level-1 user edited it.
- Staff Bill (SB): deduction via Additional Salary, worksheet fixed column; not EPF base, not APIT-deductible.

## Device ids company-wide, Attendance Supervisor reads, no-shift warning (v0.2.1, Raj 2026-11-10)
- Property Setter fixtures: `doctype_or_field` must be `DocField` (or `DocType`); `Field` is silently ignored by
  Frappe (v0.2.1 found the employee_number setters had never applied).
- **Device id = ERPNext `Employee.attendance_device_id`** (label "Attendance Device ID (all devices)", Property Setters;
  placed after Employee Number by a `field_order` Property Setter). DB unique index → one number = one person on every
  device, company-wide. `slhrm_biometric_device_id` is legacy: copied by patch v0_2_1.copy_device_ids (aborts on any
  conflict), hidden + read-only, never written or read by matching.
- Matching (`slhrm/biometric.py`): (a) SITE-WIDE Active employee with that attendance_device_id; employee's branch not
  served by the device → still matched, punch `match_reason = other_branch` (report **Device Users Other Branch**).
  (b) employee-number fallback stays scoped to the device's served branches and writes attendance_device_id.
  No per-branch uniqueness checks; branch transfer keeps the id; Employee validate refuses an id held by anyone else
  (any branch / status) and stores empty as NULL. Map to Employee allows any branch (alert says "other branch").
- Before a new device goes live: agent syncs its users (read-only) → `bench execute slhrm.biometric.device_id_collisions
  --kwargs '{"serial": "..."}'` lists device users whose id already belongs to someone else (re-enrol on site).
- **Attendance Supervisor reads** Branch / Employee / Shift Type / Holiday List: Custom DocPerm fixture
  (`fixtures/custom_docperm.json`, read only). Frappe uses ONLY Custom DocPerm rows for a doctype once one exists:
  patch v0_2_1.supervisor_perm_base + `install.ensure_custom_perm_base` copy the standard rows first (no-op on prod,
  which already had custom rows for all four). **Branch scope: HR adds a User Permission (Allow: Branch, value = the
  supervisor's branch) per supervisor**; `api._check_branch_allowed` applies it to load_attendance_data /
  recalc_attendance_row / calc_attendance_times (they read with get_all).
- Working day without a shift: row `no_shift` (orange "No shift" in the Shift cell), parent `no_shift_count` ("No shift").

## Payslip lines + salary package import (v0.2.2, Raj 2026-11-11)
- **Every payslip line is in the structure** ("Standard Staff Structure", `salary_setup.STRUCTURE_ROWS`, order =
  `EARNING_LINES` | `DEDUCTION_LINES`, employer EPF 12% / ETF 3% statistical last); `remove_if_zero_valued` = 0 on
  `SHOW_ZERO`, so zero lines stay; `apply_apit` keeps a 0 APIT line.
- **Additional Salary adds up** for `ADDITIVE_COMPONENTS` (Overtime, Other Allowance, No Pay, Other Deduction, Salary
  Advance, Personal Loan, Staff Bill): doc_event `overrides.additional_salary.before_validate` forces
  overwrite_salary_structure_amount = 0 (worksheet OT too). HRMS then adds ONE slip row per Additional Salary next to
  the structure's 0 row (several rows per component on the Salary Slip form); with overwrite = 1 a second entry in the
  month is refused by HRMS. Totals are right either way; the **"SLHRM Payslip"** print format (default for Salary
  Slip, Property Setter) and the worksheet table SUM per component (`slhrm/payslip.py` jinja `payslip_data`, employer
  box from `statutory.employer_lines`).
- Worksheet table: the OT component's structure line (0 in the preview) gets no EARNINGS column while 0 in every row
  (OT has its own group); `components_json.ot_component`.
- **Salary package import** (`slhrm/salary_import.py`): `make_template` (one row per Active employee, amounts EMPTY —
  never invent salaries), `run(file, dry_run)` (validates, totals per branch, creates / updates Employee Salary Package
  on the active structure → the package makes the SSA; empty Basic → skipped; identical row → unchanged). Desk:
  Employee Salary Package list → "Import Salary Packages" (HR Manager / System Manager): private upload → preview →
  Apply; the uploaded file is deleted after Apply / Cancel.

