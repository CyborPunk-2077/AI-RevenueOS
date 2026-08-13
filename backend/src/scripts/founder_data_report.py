"""How much genuine, non-sample data a workspace holds. LOCAL ONLY.

Read-only. Its whole job is to let a destructive script ask "is anyone actually
using this?" before it removes anything, and to print a number a human can weigh.

"Genuine" is the complement of the demo manifest: a record the seed never claimed
to create. That is the same definition the refresh uses, so the two cannot drift
into disagreeing about what is disposable.

    python src/scripts/founder_data_report.py            # human summary
    python src/scripts/founder_data_report.py --count    # a single number
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from application.tenants.demo_data import load_manifest
from infrastructure.database.session import admin_session
from infrastructure.logging.setup import configure_logging

#: The workspaces a local reset would destroy. The browser-test tenant is listed
#: because its contents are worthless, not because they are precious - counting it
#: would make every reset look dangerous and train people to ignore the warning.
DISPOSABLE_SLUGS = ("sangam-e2e", "acme", "globex")

COUNTED_TABLES = ("leads", "contacts", "accounts", "deals", "tasks", "notes")


async def founder_record_count() -> tuple[int, dict[str, int]]:
    """Rows in real workspaces that no demo manifest claims. Never counts samples."""
    breakdown: dict[str, int] = {}

    async with admin_session() as session:
        tenants = (
            await session.execute(text("SELECT id, slug FROM app.tenants WHERE deleted_at IS NULL"))
        ).all()

        for tenant_id, slug in tenants:
            if slug in DISPOSABLE_SLUGS:
                continue
            manifest = await load_manifest(session, UUID(str(tenant_id)))
            for table in COUNTED_TABLES:
                claimed = [UUID(v) for v in manifest.get(table, [])]
                # Table name from the fixed tuple above, never from input.
                statement = f"SELECT count(*) FROM app.{table} WHERE tenant_id = :t AND NOT (id = ANY(:claimed))"  # noqa: E501, S608
                total = (
                    await session.execute(text(statement), {"t": tenant_id, "claimed": claimed})
                ).scalar_one()
                if total:
                    breakdown[f"{slug}.{table}"] = int(total)

    return sum(breakdown.values()), breakdown


async def main() -> int:
    parser = argparse.ArgumentParser(description="Count genuine, non-sample records")
    parser.add_argument("--count", action="store_true", help="print only the total")
    args = parser.parse_args()

    if not args.count:
        configure_logging(json_output=False)

    total, breakdown = await founder_record_count()

    if args.count:
        print(total)  # noqa: T201
        return 0

    print("\n" + "=" * 60)  # noqa: T201
    print("  Genuine (non-sample) records")  # noqa: T201
    print("=" * 60)  # noqa: T201
    if not breakdown:
        print("  None. Only sample data and browser-test data exist.")  # noqa: T201
    else:
        for key in sorted(breakdown):
            print(f"  {key:40} {breakdown[key]:>6}")  # noqa: T201
        print(f"\n  Total: {total}")  # noqa: T201
    print("=" * 60 + "\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
