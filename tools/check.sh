#!/usr/bin/env bash
# SLHRM pre-commit check — run before EVERY commit:   tools/check.sh [BASE_REF]
#
#   1. pyflakes: 0 undefined names anywhere in slhrm/
#   2. pyflakes: 0 findings (unused imports, undefined names, ...) in .py files changed
#      vs BASE_REF (default HEAD; staged + unstaged) and in new untracked .py files
#   3. imports every slhrm module from THIS repo (PYTHONPATH=repo), not from apps/slhrm
#
# Uses the bench virtualenv: BENCH (default /home/rajerp/GILLSHR). pyflakes is dev tooling:
#   $BENCH/env/bin/pip install pyflakes
# Exit code 0 = OK, 1 = problems found, 2 = setup problem.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH="${BENCH:-/home/rajerp/GILLSHR}"
PY="$BENCH/env/bin/python"
BASE="${1:-HEAD}"
cd "$REPO" || exit 2
fail=0

if ! "$PY" -m pyflakes --version >/dev/null 2>&1; then
	echo "pyflakes is not installed in $BENCH/env (dev tooling): $BENCH/env/bin/pip install pyflakes"
	exit 2
fi

echo "== 1. pyflakes: undefined names (whole slhrm package)"
undefined=$("$PY" -m pyflakes slhrm 2>&1 | grep -E "undefined name|undefined local|undefined in __all__" || true)
if [ -n "$undefined" ]; then echo "$undefined"; fail=1; else echo "ok"; fi

echo "== 2. pyflakes: all findings in changed .py files (vs $BASE + untracked)"
changed=$(
	{
		git diff --name-only "$BASE" -- 'slhrm/*.py'
		git ls-files --others --exclude-standard -- 'slhrm/*.py'
	} | sort -u | while read -r f; do [ -f "$f" ] && echo "$f"; done
)
if [ -n "$changed" ]; then
	# shellcheck disable=SC2086
	findings=$("$PY" -m pyflakes $changed 2>&1 || true)
	if [ -n "$findings" ]; then echo "$findings"; fail=1; else echo "ok ($(echo "$changed" | wc -l) file(s))"; fi
else
	echo "ok (no changed .py files)"
fi

echo "== 3. import every slhrm module (from $REPO)"
REPO="$REPO" PYTHONPATH="$REPO" "$PY" - <<'EOF' 2>&1 | grep -v "RuntimeWarning: Unexpected value in sys" || true
import importlib, os, sys

import slhrm

repo = os.environ["REPO"]
if not os.path.realpath(slhrm.__file__).startswith(os.path.realpath(repo)):
    print(f"FAIL: imported slhrm from {slhrm.__file__}, expected {repo}")
    sys.exit(1)

# filesystem walk: doctype folders are namespace packages (no __init__.py), which
# pkgutil.walk_packages skips; slhrm/slhrm (module folder) only symlinks the same files
failed, names = [], []
pkg_root = os.path.join(repo, "slhrm")
for dirpath, dirnames, filenames in os.walk(pkg_root):
    rel = os.path.relpath(dirpath, repo)
    dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "public", "node_modules")
                   and not (rel == "slhrm" and d == "slhrm")]
    for fn in filenames:
        if fn.endswith(".py"):
            mod = os.path.join(rel, fn[:-3]).replace(os.sep, ".")
            names.append(mod[: -len(".__init__")] if mod.endswith(".__init__") else mod)
names = sorted(set(names))
for name in names:
    try:
        importlib.import_module(name)
    except Exception as e:
        failed.append(f"{name}: {type(e).__name__}: {e}")
for f in failed:
    print("FAIL", f)
print(f"imported {len(names) - len(failed)}/{len(names)} modules")
open(os.path.join(repo, ".check_import_status"), "w").write("1" if failed else "0")
EOF
if [ "$(cat "$REPO/.check_import_status" 2>/dev/null)" != "0" ]; then fail=1; fi
rm -f "$REPO/.check_import_status"

if [ "$fail" -eq 0 ]; then echo "CHECK PASSED"; else echo "CHECK FAILED"; fi
exit "$fail"
