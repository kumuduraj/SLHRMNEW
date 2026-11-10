"""pre_model_sync (before fixtures): Attendance Supervisor role + standard perms copied to Custom DocPerm for the
doctypes the supervisor reads, so the fixture's read rows never replace everyone else's permissions."""
from slhrm.install import ensure_custom_perm_base, ensure_roles


def execute():
    ensure_roles()
    ensure_custom_perm_base()
