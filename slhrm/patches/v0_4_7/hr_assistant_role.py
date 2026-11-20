"""pre_model_sync (before fixtures), v0.4.7: create the "HR Assistant" role and copy the standard permission rows to Custom
DocPerm for every core doctype the role gets fixture rows on that has none yet (Frappe uses ONLY Custom DocPerm rows once one
exists) — so no existing role loses a permission. No-op for doctypes that already have custom rows."""
from slhrm.install import ensure_custom_perm_base, ensure_roles


def execute():
    ensure_roles()
    ensure_custom_perm_base()
