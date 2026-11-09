"""Fail if the legacy product brand appears in any git-tracked file (content or path).

    python3 scripts/verify_brand.py

The search pattern is assembled from two parts so this script never contains the legacy name itself.
It matches any case and any separator ("", "-", "_", " ", ".") between the two words, in text files and
in the raw bytes of binary files (PDF metadata, DOCX, images).

Exceptions are explicit, path-exact and justified; add one only for real technical compatibility.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_A, _B = "scope", "lock"
PATTERN = re.compile(rf"{_A}[\s._-]?{_B}", re.IGNORECASE)

# path -> reason. Keep this list short and documented.
ALLOWED: dict[str, str] = {
    "apps/api/alembic/versions/20261107_0002_immutability_triggers.py": (
        "historical migration already applied to existing databases; never edited"
    ),
    "TERMRAIL_MASTER_SPEC.md": (
        "internal engineering spec whose rebrand section must name what is being removed; not shipped to customers"
    ),
    "apps/api/alembic/versions/20261108_0003_rebrand_db_functions.py": (
        "renames the legacy DB function names created by 0002; must name them to rename them"
    ),
    # Browser-storage migration: users upgraded from the old name keep their session, language, theme and
    # workspace because the app still READS the pre-rebrand keys once (and rewrites them under termrail.*).
    "apps/web/src/lib/storage.ts": "reads pre-rebrand localStorage keys so upgraded users keep their preferences",
    "apps/web/index.html": "pre-paint boot script reads the pre-rebrand theme/locale keys to avoid a flash on upgrade",
    "apps/web/src/lib/theme.test.tsx": "regression test for the legacy theme-key migration",
    "apps/web/src/lib/i18n/i18n.test.ts": "regression tests for the legacy locale-key migration and brand-free dictionaries",
}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)  # noqa: S607
    return [p for p in out.stdout.decode().split("\0") if p]


def main() -> int:
    problems: list[str] = []
    for rel in tracked_files():
        if rel in ALLOWED:
            continue
        if PATTERN.search(rel):
            problems.append(f"{rel}: legacy brand in file path")
        path = ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            if PATTERN.search(data.decode("latin-1")):
                problems.append(f"{rel}: legacy brand in binary content")
            continue
        for no, line in enumerate(lines, start=1):
            if PATTERN.search(line):
                problems.append(f"{rel}:{no}: {line.strip()[:120]}")
    if problems:
        print(f"Rebrand verification FAILED: {len(problems)} legacy reference(s)")
        for p in problems:
            print("  " + p)
        return 1
    print(f"Rebrand verification: 0 legacy public references ({len(ALLOWED)} documented exceptions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
