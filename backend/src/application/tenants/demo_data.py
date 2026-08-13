"""Which rows a demo seed created, and therefore which rows it may delete.

This module exists because of a real incident. The demo refresh used to rebuild a
workspace with `DELETE FROM app.leads WHERE tenant_id = :t` - every row in the
tenant, on the assumption that a demo tenant contains only demo data. By the time
the founders were prospecting for real out of that same workspace the assumption
was false, and a prospect they had created and worked was destroyed along with its
notes and tasks.

The fix is not a better heuristic. A heuristic decides what *looks* synthetic, and
anything it misjudges is deleted silently. Instead the seed **records what it
created**, and the refresh deletes nothing else. The consequences follow from the
design rather than from care:

* a record the seed did not create is never a candidate for deletion, so founder
  and imported records survive by construction, not by being recognised;
* an unmarked or ambiguous row is preserved, because absence from the manifest is
  the default state;
* the blast radius is bounded by the tenant the manifest belongs to.

`capture.demo_data` stays on seeded records, but it is a **display** marker - it
draws the "sample" pill next to a prospect. It is deliberately not what authorises
a delete: a label a user could edit must never decide whether a row is destroyed.

The manifest lives in `tenants.settings`, which is already JSONB, so this needs no
migration and no new table to keep in step with the ones it tracks.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from infrastructure.logging.setup import get_logger

logger = get_logger("application.tenants.demo_data")

MANIFEST_KEY: Final = "demo_seed"

#: Tables the demo seed populates, in the order they must be deleted so that a
#: foreign key never blocks the one before it. Append-only tables - `activities`,
#: `lead_source_events`, the audit log - are absent on purpose: the database
#: refuses to delete from them, and that refusal is a feature.
DELETABLE_TABLES: Final[tuple[str, ...]] = (
    "tasks",
    "notes",
    "deals",
    "stages",
    "pipelines",
    "account_contacts",
    "contacts",
    "accounts",
    "lead_duplicate_candidates",
    "leads",
)


def empty_manifest() -> dict[str, list[str]]:
    return {table: [] for table in DELETABLE_TABLES}


async def load_manifest(session: Any, tenant_id: UUID) -> dict[str, list[str]]:
    """The ids this tenant's demo seed created, or empty when it never ran."""
    from sqlalchemy import select

    from infrastructure.database.models.tenancy import Tenant

    settings = (
        await session.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    stored = (settings or {}).get(MANIFEST_KEY) or {}
    manifest = empty_manifest()
    for table in DELETABLE_TABLES:
        manifest[table] = [str(value) for value in stored.get(table, [])]
    return manifest


async def record_manifest(session: Any, tenant_id: UUID, manifest: dict[str, list[str]]) -> None:
    """Replace the manifest with what the seed has just written.

    Replace rather than append: a refresh deletes the previous generation before
    creating this one, so carrying the old ids forward would only accumulate
    references to rows that no longer exist.
    """
    from sqlalchemy import select, update

    from infrastructure.database.models.tenancy import Tenant

    current = (
        await session.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar_one()
    merged = {
        **(current or {}),
        MANIFEST_KEY: {table: sorted(set(ids)) for table, ids in manifest.items() if ids},
    }
    # A Core update, not an ORM mutation. `Tenant` carries an optimistic version
    # column, and bumping it from a maintenance script would make an unrelated
    # concurrent save fail with a conflict it did not cause.
    await session.execute(update(Tenant).where(Tenant.id == tenant_id).values(settings=merged))


async def delete_recorded_rows(session: Any, tenant_id: UUID) -> dict[str, int]:
    """Delete exactly the rows the seed recorded, and nothing else.

    Both predicates matter. The id list is what makes this sample-only; the
    tenant filter is what makes a manifest that somehow named a foreign id
    harmless anyway.
    """
    from sqlalchemy import text

    manifest = await load_manifest(session, tenant_id)
    removed: dict[str, int] = {}

    for table in DELETABLE_TABLES:
        ids = manifest.get(table) or []
        if not ids:
            continue
        result = await session.execute(
            # Table names come from the fixed tuple above, never from input.
            text(f"DELETE FROM app.{table} WHERE tenant_id = :t AND id = ANY(:ids)"),  # noqa: S608
            {"t": tenant_id, "ids": [UUID(value) for value in ids]},
        )
        removed[table] = int(result.rowcount or 0)

    # The manifest described rows that no longer exist, so it is emptied in the
    # same breath. Leaving stale ids behind would make the next seed believe the
    # samples were still present and decline to rebuild them.
    await record_manifest(session, tenant_id, empty_manifest())

    logger.info("demo_rows_deleted", tenant_id=str(tenant_id), **removed)
    return removed


async def adopt_existing_demo_rows(session: Any, tenant_id: UUID) -> dict[str, list[str]]:
    """Build a manifest from rows an earlier seed marked, for one-time migration.

    Seeds written before the manifest existed left `capture.demo_data = true` on
    every record they created. That marker is written by the seed and by nothing
    else, so it is trustworthy evidence of synthetic origin - which is why it is
    acceptable here and still not acceptable as the thing a delete consults
    directly. Adoption happens once, deliberately, and produces a manifest; from
    then on the manifest is what authorises deletion.

    Deliberately narrow: only records carrying the marker, plus the tasks and
    notes hanging off them. Anything unmarked - a founder's prospect, an imported
    business - is not adopted and therefore stays out of reach of every future
    refresh.
    """
    from sqlalchemy import text

    manifest = empty_manifest()

    for table in ("leads", "contacts", "accounts", "deals"):
        column = "capture" if table == "leads" else "custom_fields"
        # Table and column come from the fixed tuple above, never from input.
        marked = (
            f"SELECT id FROM app.{table} WHERE tenant_id = :t AND {column} ->> 'demo_data' = 'true'"  # noqa: S608
        )
        rows = await session.execute(text(marked), {"t": tenant_id})
        manifest[table] = [str(row[0]) for row in rows]

    parents = {
        "lead": manifest["leads"],
        "deal": manifest["deals"],
        "contact": manifest["contacts"],
        "account": manifest["accounts"],
    }
    for table in ("tasks", "notes"):
        collected: list[str] = []
        for entity_type, ids in parents.items():
            if not ids:
                continue
            # Table name from the fixed tuple above, never from input.
            children = f"SELECT id FROM app.{table} WHERE tenant_id = :t AND entity_type = :entity_type AND entity_id = ANY(:ids)"  # noqa: E501, S608
            rows = await session.execute(
                text(children),
                {"t": tenant_id, "entity_type": entity_type, "ids": [UUID(v) for v in ids]},
            )
            collected.extend(str(row[0]) for row in rows)
        manifest[table] = collected

    await record_manifest(session, tenant_id, manifest)
    logger.info(
        "demo_rows_adopted",
        tenant_id=str(tenant_id),
        **{table: len(ids) for table, ids in manifest.items() if ids},
    )
    return manifest
