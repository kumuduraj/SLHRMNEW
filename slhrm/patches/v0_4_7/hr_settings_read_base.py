"""pre_model_sync (before fixtures), v0.4.7: HR Assistant gets read on HR Settings (the new Employee form reads
emp_created_by). HR Settings had no Custom DocPerm rows, so copy its standard rows first (setup_custom_perms) — otherwise the
fixture row would replace them. Separate patch because v0_4_7.hr_assistant_role already ran."""
from slhrm.install import ensure_custom_perm_base


def execute():
    ensure_custom_perm_base()
