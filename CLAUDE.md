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
- (v0.0.3) install.py deleted the core "Home" workspace and rebuilt the sidebar/page/icon with raw SQL on every migrate, and Frappe's orphan cleanup then deleted the SLHRM icon (no JSON) → ship desk records as app JSON; never touch core records.

## Known open items (not yet fixed)
- `SLHRM Settings` fields never read by code: `auto_mark_attendance`, `auto_create_payroll_on_submit`, `overtime_threshold`.
- `create_employee_user` sets default password `Abc@12345` and shows it in a msgprint;
  `slhrm_must_change_password` is enforced only by the PWA router, not in Desk/API.
