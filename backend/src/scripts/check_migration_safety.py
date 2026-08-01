"""Release gate: a pre-deploy migration must be backward compatible.

Expand/contract means a deployment may add nullable columns, add indexes
concurrently and add NOT VALID foreign keys - but never drop or rewrite in the
same release as the code that depends on the old shape.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_IN_PREDEPLOY = (
    (re.compile(r"\bop\.drop_column\b"), "dropping a column is a contract-phase change"),
    (re.compile(r"\bop\.drop_table\b"), "dropping a table is a contract-phase change"),
    (re.compile(r"\bop\.drop_constraint\b"), "dropping a constraint is a contract-phase change"),
    (re.compile(r"\bop\.alter_column\([^)]*type_="), "changing a column type rewrites the table"),
    (re.compile(r"nullable=False"), "adding a NOT NULL column without a default blocks writes"),
)

REQUIRE_CONCURRENT = re.compile(r"op\.create_index\((?![^)]*postgresql_concurrently=True)")


def check(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    if "# expand-contract: contract-phase" in source:
        return []  # explicitly marked as a later, separate release
    problems: list[str] = []
    for pattern, reason in FORBIDDEN_IN_PREDEPLOY:
        if pattern.search(source):
            problems.append(f"{path.name}: {reason}")
    if REQUIRE_CONCURRENT.search(source) and "0001_" not in path.name:
        problems.append(f"{path.name}: production indexes must be created concurrently")
    return problems


def main() -> int:
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    problems: list[str] = []
    for migration in sorted(versions.glob("*.py")):
        problems.extend(check(migration))
    if problems:
        for problem in problems:
            print(f"MIGRATION SAFETY: {problem}")  # noqa: T201
        return 1
    print(f"migration safety: {len(list(versions.glob('*.py')))} migration(s) verified")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
