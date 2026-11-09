"""Employee login accounts + forced password change (SLHRM-owned; no core edits).

User creation (Employee after_insert):
- Never a fixed password.
- Outgoing email deliverable (enabled outgoing Email Account or site mail_server, and emails not muted)
  -> User with send_welcome_email=1: Frappe's standard set-password link; no flag.
- Otherwise -> random 12-char password (secrets) + `slhrm_must_change_password` = 1. The password is shown
  ONCE to the session user (msgprint in the response) — never logged, never in Error Log / Comment /
  Version. During a Data Import it is NOT shown (the importer persists message_log into Data Import Log
  when a later row fails); HR issues one with `issue_temporary_password` (Employee form button).
- Employees without an email get no user. Interactive: an alert. Data Import: ONE summary Comment on the
  Data Import, updated per row — no Error Log per employee.

Forced change:
- A user must change while `slhrm_must_change_password` = 1 AND `last_password_reset_date` is empty.
  Frappe's own `update_password` (the /update-password page and the PWA) sets that date, so ANY real
  password change ends the requirement; the flag is then cleared. A client call alone can never clear it.
- `enforce_password_change` (auth_hooks: runs on every request after cookie / token / API-key auth):
  Desk + PWA pages -> 302 /update-password; API calls -> 403 "Password change required", except login,
  logout and the password-update methods.
"""

import secrets
import string

import frappe
from frappe import _
from frappe.utils import cint
from werkzeug.exceptions import HTTPException
from werkzeug.utils import redirect

FLAG = "slhrm_must_change_password"
CACHE_KEY = "slhrm_must_change_pw"  # user -> 0 (only "no change needed" is cached)
SUMMARY_MARKER = "SLHRM user creation summary"
UPDATE_PASSWORD_PAGE = "/update-password"

# API methods a user who must change the password may still call.
ALLOWED_METHODS = frozenset({
    "login",
    "logout",
    "web_logout",
    "frappe.auth.get_logged_user",
    "frappe.core.doctype.user.user.update_password",
    "frappe.core.doctype.user.user.test_password_strength",
    "slhrm.api.check_must_change_password",
    "slhrm.api.clear_must_change_password",
})
REDIRECT_PREFIXES = ("/desk", "/app", "/slhrm")
# A temporary password may only be issued to plain employee accounts (never to HR / admins).
TEMP_PASSWORD_ROLES = frozenset({"Employee", "Employee Self Service", "Desk User", "All", "Guest"})
ISSUER_ROLES = ("HR Manager", "System Manager")


# ── user creation ───────────────────────────────────────────────


def create_employee_user(doc, method=None):
    """doc_events Employee.after_insert."""
    if doc.user_id:
        return

    email = doc.company_email or doc.personal_email
    if not email:
        _report_no_email(doc)
        return

    if frappe.db.exists("User", email):
        doc.db_set("user_id", email)
        _note_import(doc)
        if not frappe.flags.in_import:
            frappe.msgprint(_("User {0} already exists. Linked to employee.").format(email),
                            indicator="blue", alert=True)
        return

    by_email = outgoing_email_ready()
    password = None if by_email else random_password()
    frappe.db.savepoint("slhrm_create_user")
    try:
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = doc.first_name or doc.employee_name
        user.last_name = doc.last_name or ""
        user.enabled = 1
        user.user_type = "System User"
        user.send_welcome_email = 1 if by_email else 0
        if password:
            user.new_password = password
            user.set(FLAG, 1)
        user.append("roles", {"role": "Employee"})
        user.flags.ignore_permissions = True
        # link first: ERPNext's User validate (validate_employee_role) strips the Employee role,
        # with a confusing message, from a user that no Employee points to yet
        doc.db_set("user_id", email)
        user.insert()
    except Exception as e:
        frappe.db.rollback(save_point="slhrm_create_user")
        doc.user_id = None
        frappe.log_error(title="SLHRM: User creation failed",
                         message=f"Employee {doc.name}: could not create User {email}: {type(e).__name__}: {e}")
        if not frappe.flags.in_import:
            frappe.msgprint(_("Failed to create User for {0}: {1}").format(doc.employee_name, str(e)),
                            indicator="red", alert=True)
        return

    _forget(user.name)
    if by_email:
        _note_import(doc)
        if not frappe.flags.in_import:
            frappe.msgprint(_("User {0} created for {1}. A welcome email with a set-password link was sent.")
                            .format(email, doc.employee_name), indicator="green", alert=True)
    elif frappe.flags.in_import or not getattr(frappe.local, "request", None):
        # never echo a password into an import / background job (it could be persisted)
        _note_import(doc)
    else:
        _show_password_once(email, doc.employee_name, password)


def _report_no_email(doc):
    if frappe.flags.in_import:
        _note_import(doc)
        return
    frappe.msgprint(_("No email found for {0}. User account was not created. "
                      "Set Company Email or Personal Email, then use Create User on the Employee form.").format(
                        doc.employee_name),
                    indicator="orange", alert=True)


def _show_password_once(user, employee_name, password):
    """Shown to the session user in this response only (not persisted anywhere).
    Server msgprint runs Frappe's clean_html (nh3), which strips <code>: use <strong>."""
    frappe.msgprint(
        _("User <b>{0}</b> created for {1}.<br>Temporary password (shown only now): <strong>{2}</strong><br>"
          "The user must change it at first login.").format(
            frappe.utils.escape_html(user), frappe.utils.escape_html(employee_name or ""), password),
        title=_("Login created"), indicator="green")


def outgoing_email_ready():
    if frappe.flags.mute_emails or cint(frappe.conf.get("mute_emails")):
        return False
    if frappe.conf.get("mail_server"):
        return True
    return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1}))


def random_password(length=12):
    """Random password with upper, lower, digit and symbol (passes Frappe's password policy)."""
    symbols = "!@#$%*-_+=?"
    pools = (string.ascii_uppercase, string.ascii_lowercase, string.digits, symbols)
    alphabet = "".join(pools)
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in pool for c in pwd) for pool in pools):
            return pwd


# ── Data Import summary (one Comment per import) ────────────────


SUMMARY_TITLES = {
    "no_email": "Employees without Company/Personal Email — no user created",
    "temp": "Users with a random password that was NOT shown during the import — "
            "issue one from Employee → Issue Temporary Password",
    "linked": "Users created with a welcome email (set-password link) or linked to an existing user",
}


def _note_import(doc):
    """Rebuild the ONE summary Comment of the running Data Import from the database (no parsing):
    employees of this import = its successful Data Import Log rows + the employee being inserted."""
    ref = doc.flags.updater_reference or {}
    if not frappe.flags.in_import or ref.get("doctype") != "Data Import":
        return
    data_import = ref["docname"]
    names = frappe.get_all("Data Import Log", filters={"data_import": data_import, "success": 1}, pluck="docname")
    names = list(dict.fromkeys([n for n in names if n] + [doc.name]))
    rows = frappe.get_all("Employee", filters={"name": ["in", names]},
                          fields=["name", "employee_name", "company_email", "personal_email", "user_id"],
                          order_by="name asc")
    flagged = set(frappe.get_all("User", filters={"name": ["in", [r.user_id for r in rows if r.user_id] or [""]],
                                                  FLAG: 1}, pluck="name"))
    groups = {k: [] for k in SUMMARY_TITLES}
    for r in rows:
        if r.user_id:
            groups["temp" if r.user_id in flagged else "linked"].append(f"{r.name} → {r.user_id}")
        elif not (r.company_email or r.personal_email):
            groups["no_email"].append(f"{r.name} ({r.employee_name})")
    parts = [f"<p><b>{SUMMARY_MARKER}</b> ({len(rows)} employees so far)</p>"]
    for kind, title in SUMMARY_TITLES.items():
        if groups[kind]:
            parts.append(f"<p><b>{title}: {len(groups[kind])}</b></p><ul>"
                         + "".join(f"<li>{frappe.utils.escape_html(x)}</li>" for x in groups[kind]) + "</ul>")
    content = "\n".join(parts)
    name = frappe.db.get_value("Comment", {"reference_doctype": "Data Import", "reference_name": data_import,
                                           "comment_type": "Info", "content": ["like", f"%{SUMMARY_MARKER}%"]}, "name")
    if name:
        frappe.db.set_value("Comment", name, "content", content, update_modified=False)
    else:
        frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": "Data Import",
                        "reference_name": data_import, "content": content}).insert(ignore_permissions=True)


# ── temporary password for an existing employee login ───────────


@frappe.whitelist(methods=["POST"])
def issue_temporary_password(employee):
    """HR Manager / System Manager: new random password for the employee's (plain employee) user.
    Returned in THIS response only; the user must change it at next login."""
    frappe.only_for(ISSUER_ROLES)
    user = frappe.db.get_value("Employee", employee, "user_id")
    if not user:
        frappe.throw(_("Employee {0} has no linked User.").format(employee))
    if user in frappe.STANDARD_USERS or user == frappe.session.user:
        frappe.throw(_("Not allowed for this user."), frappe.PermissionError)
    extra = set(frappe.get_roles(user)) - TEMP_PASSWORD_ROLES
    if extra:
        frappe.throw(_("User {0} has roles beyond Employee ({1}); reset it from the User form.").format(
            user, ", ".join(sorted(extra))), frappe.PermissionError)
    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw(_("User {0} is disabled.").format(user))

    from frappe.utils.password import update_password

    password = random_password()
    update_password(user, password, logout_all_sessions=True)
    frappe.db.set_value("User", user, {FLAG: 1, "last_password_reset_date": None})
    _forget(user)
    return {"user": user, "password": password}


# ── forced password change ──────────────────────────────────────


def must_change_password(user=None):
    user = user or frappe.session.user
    if not user or user in frappe.STANDARD_USERS:
        return False
    if frappe.cache.hget(CACHE_KEY, user) == 0:
        return False
    flag, changed_on = frappe.db.get_value("User", user, [FLAG, "last_password_reset_date"]) or (0, None)
    if cint(flag) and changed_on:
        # a real password change happened (Frappe's update_password sets the date) -> requirement met
        frappe.db.set_value("User", user, FLAG, 0, update_modified=False)
        flag = 0
    if not cint(flag):
        frappe.cache.hset(CACHE_KEY, user, 0)
        return False
    return True


def _forget(user):
    frappe.cache.hdel(CACHE_KEY, user)


class _RedirectResponse(HTTPException):
    """werkzeug HTTPException -> frappe.app returns e.get_response() as is (302, not cached)."""

    code = 302

    def __init__(self, location):
        super().__init__()
        self.location = location

    def get_response(self, environ=None, scope=None):
        response = redirect(self.location, 302)
        response.headers["Cache-Control"] = "no-store"
        return response


def _api_method(path):
    for prefix in ("/api/method/", "/api/v1/method/", "/api/v2/method/"):
        if path.startswith(prefix):
            return path[len(prefix):].strip("/")
    return None


def enforce_password_change():
    """auth_hooks: every request, after cookie / token / API-key authentication."""
    request = getattr(frappe.local, "request", None)
    if request is None or not must_change_password():
        return
    path = request.path or "/"
    if path.startswith("/api/"):
        if _api_method(path) in ALLOWED_METHODS:
            return
        raise frappe.PermissionError(_("Password change required"))
    if path.startswith("/private/files/"):
        raise frappe.PermissionError(_("Password change required"))
    if request.method in ("GET", "HEAD") and any(path == p or path.startswith(p + "/") for p in REDIRECT_PREFIXES):
        if path == "/slhrm" or path.startswith("/slhrm/"):
            # Frappe's update_password sends the user here after the change
            frappe.cache.hset("redirect_after_login", frappe.session.user, "/slhrm")
        raise _RedirectResponse(UPDATE_PASSWORD_PAGE)


def on_session_creation(login_manager=None):
    """Fresh state at every login (Desk redirect itself happens in enforce_password_change)."""
    _forget(frappe.session.user)
    must_change_password()


def extend_bootinfo(bootinfo):
    if must_change_password():
        bootinfo.slhrm_must_change_password = 1


def on_user_update(doc, method=None):
    _forget(doc.name)
