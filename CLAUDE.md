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
- Python change under `slhrm/` → stop after clear-cache; Raj restarts (`rajerp` has no passwordless sudo).

## Layout
- The live Python package is `slhrm/`. The repo root holds only packaging files
  (`pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`), `SLHRM-PWA/` and `slhrm/`.
  **Never recreate root-level duplicates** of `api.py`, `hooks.py`, `install.py`, `public/` etc.
- Module folder `slhrm/slhrm/` (module "SLHRM") holds committed symlinks
  `doctype`, `fixtures`, `page`, `public`, `workspace`, `workspace_sidebar` → `../`.
- Desk records are standard app files synced by `bench migrate` (bump `modified` when editing):
  Workspace `slhrm/workspace/slhrm/slhrm.json`, Page `slhrm/page/slhrm_dashboard/slhrm_dashboard.json`
  (module folder), Workspace Sidebar `slhrm/workspace_sidebar/slhrm.json` and Desktop Icon
  `slhrm/desktop_icon/slhrm.json` (app-level folders). A standard record without its JSON file is
  deleted by Frappe's orphan cleanup on migrate.
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
- Device endpoints (`device_punch`, `device_punch_bulk`) are `allow_guest`; they must call
  `_validate_device_api_key()` first, and that check must fail closed (disabled/unset/wrong → 403).
- `install.execute` / `install.after_migrate` only ensure the SLHRM Module Def via the API. Keep them
  idempotent and API-based, on SLHRM-owned records only; no raw SQL, no file writes into the app.
- Custom fields carry the `slhrm_` prefix (Employee: `slhrm_biometric_section`,
  `slhrm_biometric_device_id`, `slhrm_biometric_device_name`). Check that every `insert_after`
  anchor exists in the current core JSON.

## Overtime (OT) flow
`Attendance Marker` → `Payroll Worksheet` → `Additional Salary` → `Salary Slip`
- **`slhrm/overtime.py` is the only OT math** (pure functions: `calculate_ot_hours`,
  `calculate_ot_rates`, `calculate_ot_amounts`; currently PLACEHOLDER formulas). Never compute OT
  anywhere else — the worksheet JS calls `slhrm.api.calc_worksheet_row`. Unit tests: `slhrm/tests/test_overtime.py`
  (UnitTestCase only; run with `CI=1 bench --site … run-tests --app slhrm --module
  slhrm.tests.test_overtime --skip-before-tests` — do not set `allow_tests` on production).
- Two types: **Normal** (working-day hours beyond the shift) and **Double** (holiday / weekly off).
  HRMS v16 resolves holidays only via **Holiday List Assignment** (employee, else company);
  `Employee.holiday_list` is ignored.
- **Worksheet = HRMS Salary Slip preview + OT. Never duplicate HRMS pay math.**
  `slhrm/payroll_preview.build_preview` builds an in-memory Salary Slip with HRMS's own methods
  (`get_working_days_details` → `check_sal_struct` → `make_salary_slip(structure, slip)`), applies
  `overrides.salary_slip.apply_package_overrides` (same function as the real slip's before_save) and
  returns its earnings/deductions/gross/net/payment days/LWP. **The preview must never write:** no
  insert/save/commit, no `slip.validate()` (check_existing throws), no `get_emp_and_working_day_details`
  (loan accrual writes when lending is installed); every preview runs inside a savepoint that is rolled
  back. `slhrm/payroll_pay.py`: gross = preview gross + Normal OT + Double OT; deductions = preview
  deductions (+ loan); net = gross − deductions. Additional Salary is already inside the preview
  (display totals only); the worksheet's own OT Additional Salary is dropped from previews.
- OT edits (`calc_worksheet_row`, `_recalculate_all`) never rebuild previews; "Refresh Salary Data"
  does (keeps OT edits). >100 employees → background job (`run_payroll_job`, realtime
  `slhrm_payroll_progress`, result via `get_payroll_job_result`). Rows with `row_error` block submit.
- Tax/statutory components use gross INCLUDING OT on the final slip, so the worksheet shows them
  without OT (UI note says so).
- Eligibility: `Employee.slhrm_ot_eligible`. Always re-read on the server; ineligible → 0 everywhere.
- Marker (`slhrm/attendance.py`): punches = Biometric Punch Log for all + Employee Checkin for
  `slhrm_allow_app_checkin`; window = shift start − `shift_match_window_before` … shift end +
  `ot_punch_window_after`. Rows keep `calc_normal_ot`/`calc_double_ot` (server-computed) and approved
  `normal_ot_hours`/`double_ot_hours`.
- Worksheet sums submitted markers' approved hours (`slhrm/payroll_ot.py`), rates from overtime.py.
  On submit: one Additional Salary per employee per OT type (components in SLHRM Settings,
  `ref_doctype`/`ref_docname` = the worksheet). On cancel: blocked if a submitted Salary Slip uses it,
  else the Additional Salary is cancelled + deleted. `load_payroll_data` excludes Additional Salary
  with `ref_doctype = 'Payroll Worksheet'` (no double count).
- **Permlevel 1** = OT hours/rates on Marker Detail and Worksheet Employee: read for HR roles, write only
  HR Manager / System Manager. Frappe resets level-1 child fields only for *existing* docs and only
  *before* `validate`, so the controllers enforce it themselves (new rows → calculated values,
  existing rows → stored values, for users without level-1 write).
- Employee Salary Package overrides (`overrides/salary_slip.py`) must never include the OT components.

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
- `frappe.boot` keys the PWA reads: `push_relay_server_url`, `lang`, `__messages`
  (`translations_hash` is optional). Add new keys in `slhrm/www/slhrm.py:get_boot`.

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
- (v0.0.6) Re-implementing HRMS salary math in SLHRM (structure formulas, proration, Additional Salary) drifted from the real slip (LWP, overrides) → the worksheet uses HRMS's own Salary Slip calculation as an unsaved preview; SLHRM only adds OT.
- (v0.0.5) The worksheet put structure components into `additional_earning_total` and added `base` on top, so gross counted base twice; structure amounts were also computed twice (with and without package overrides) and the JS recomputed totals itself → one pay module (`payroll_pay.py`), Additional Salary means Additional Salary only, JS displays server values.
- (v0.0.5) The `load_payroll_data` rewrite dropped a local `flt` import; the "smoke test" only imported
  modules, so a NameError shipped and broke the worksheet loader until a follow-up fix + restart
  → `tools/check.sh` (pyflakes + import of every module) before every commit.
- (v0.0.5) Import-only smoke tests can't see errors inside functions → smoke tests call every touched
  whitelisted endpoint with throwaway data / minimal args.
- (v0.0.5) One deploy report omitted the core-app git status → every deploy report lists frappe,
  erpnext, hrms and slhrm status + HEAD vs upstream/master.

## Known open items (not yet fixed)
- `SLHRM Settings` fields never read by code: `auto_mark_attendance`, `auto_create_payroll_on_submit`.
- `create_employee_user` sets default password `Abc@12345` and shows it in a msgprint;
  `slhrm_must_change_password` is enforced only by the PWA router, not in Desk/API.
