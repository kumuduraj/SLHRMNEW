"""pre_model_sync: the Attendance Supervisor role must exist before the Attendance Marker
permissions that name it are synced."""
from slhrm.install import ensure_roles


def execute():
    ensure_roles()
