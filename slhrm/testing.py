# slhrm/testing.py
"""Throwaway-test helpers for production checks (bench execute / scripts only — nothing here is whitelisted).

delete_throwaway() removes a test record WITHOUT leaving Frappe's deletion trail: no "Deleted Document"
copy (delete_permanently=True) and no "Deleted" Comment (insert_feed is skipped while frappe.flags.in_import
is set). Use it in every teardown; the "counts before = after" proof must include Deleted Document and Comment.
"""
from contextlib import contextmanager

import frappe

TRAIL_DOCTYPES = ("Deleted Document", "Comment")


@contextmanager
def no_delete_feed():
    previous = frappe.flags.in_import
    frappe.flags.in_import = True
    try:
        yield
    finally:
        frappe.flags.in_import = previous


def delete_throwaway(doctype, name, cancel=True):
    """Cancel (if submitted) and permanently delete one test record; no Deleted Document, no Deleted comment.
    Returns True if it existed."""
    if not name or not frappe.db.exists(doctype, name):
        return False
    doc = frappe.get_doc(doctype, name)
    if cancel and doc.meta.is_submittable and doc.docstatus == 1:
        doc.flags.ignore_permissions = True
        doc.cancel()
    with no_delete_feed():
        frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, delete_permanently=True)
    return True


def trail_counts():
    return {dt: frappe.db.count(dt) for dt in TRAIL_DOCTYPES}
