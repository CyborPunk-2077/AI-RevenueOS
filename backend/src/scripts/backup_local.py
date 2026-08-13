"""A local database snapshot, taken before anything destructive runs. LOCAL ONLY.

Small on purpose. This is not a backup product; it is the seatbelt that was
missing when a demo refresh deleted a real prospect. The rule it enforces is the
only one that matters:

**If the snapshot cannot be written, the destructive operation does not start.**

A backup that is best-effort is not a backup - it is a comforting log line that
turns out to be absent on the one morning it was needed.

Snapshots are plain `pg_dump` output under `backups/` at the repository root,
named for the moment they were taken. That directory is git-ignored: it contains
real prospect names, phone numbers and email addresses, and none of that belongs
in version control.

    python src/scripts/backup_local.py                 # take one now
    python src/scripts/backup_local.py --reason refresh

Recovery is deliberately manual, because restoring over live data should be a
decision somebody makes rather than something a script can do by accident:

    docker compose exec -T postgres psql -U airevenueos -d airevenueos < backups/<file>.sql
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.logging.setup import configure_logging, get_logger
from shared.settings import get_settings
from shared.utils.timeutil import utcnow

logger = get_logger("scripts.backup_local")

#: Kept inside the container at a path the compose file maps to `backups/` on the
#: host, so a snapshot survives the container that produced it.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))

#: Enough history to undo a mistake, not so much that a laptop fills up.
KEEP_LAST = 10

_SAFE_REASON = re.compile(r"[^a-z0-9-]+")


class BackupFailed(RuntimeError):
    """Raised so a caller cannot proceed with a destructive operation."""


def _dump_command(database_url: str) -> list[str]:
    """`pg_dump` arguments for the maintenance connection.

    The URL is handed to pg_dump directly rather than split into flags: it already
    carries the host, port, database and credential, and re-deriving those is how
    a snapshot ends up silently pointing at the wrong database.
    """
    return [
        "pg_dump",
        "--dbname",
        database_url,
        "--format",
        "plain",
        "--no-owner",
        "--no-privileges",
        # Data plus schema: a restore has to be able to stand up the tables it
        # fills, and this database is small enough that the distinction costs
        # nothing.
        "--clean",
        "--if-exists",
    ]


def _postgres_url() -> str:
    """The synchronous URL pg_dump understands.

    The application connects with `postgresql+asyncpg://`, which is a SQLAlchemy
    dialect string and not something libpq can parse.
    """
    # The migration credential is the right one: it owns the schema, so the dump
    # includes everything. The runtime role deliberately cannot see some of it.
    url = os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().sync_database_url
    for dialect in ("+asyncpg", "+psycopg"):
        url = url.replace(dialect, "")
    return url


def prune(directory: Path, keep: int = KEEP_LAST) -> int:
    """Delete all but the newest `keep` snapshots. Returns how many went."""
    snapshots = sorted(directory.glob("sangam-*.sql"), key=lambda p: p.name, reverse=True)
    removed = 0
    for stale in snapshots[keep:]:
        stale.unlink(missing_ok=True)
        removed += 1
    return removed


def take_snapshot(reason: str = "manual", *, directory: Path | None = None) -> Path:
    """Write a snapshot and return its path. Raises `BackupFailed` if it cannot.

    Never returns a path that does not exist and is not non-empty: the whole point
    is that the caller may treat a successful return as permission to proceed.
    """
    settings = get_settings()
    if settings.environment != "local":
        raise BackupFailed(f"refusing to snapshot in the '{settings.environment}' environment")

    target = directory or BACKUP_DIR
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupFailed(f"cannot create the backup directory {target}: {exc}") from exc

    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    label = _SAFE_REASON.sub("-", reason.lower()).strip("-") or "manual"
    path = target / f"sangam-{stamp}-{label}.sql"

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            _dump_command(_postgres_url()),
            capture_output=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BackupFailed("pg_dump is not available in this container") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupFailed("pg_dump did not finish within ten minutes") from exc

    if completed.returncode != 0:
        # stderr can name the database and the role; the return code and a fixed
        # message are enough for the operator, and the detail stays out of the log.
        raise BackupFailed(f"pg_dump exited with code {completed.returncode}")

    path.write_bytes(completed.stdout)
    if path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise BackupFailed("pg_dump produced an empty file")

    pruned = prune(target)
    # Size and name only. A backup log is not a place for customer data.
    logger.info(
        "backup_taken",
        file=path.name,
        bytes=path.stat().st_size,
        reason=label,
        pruned=pruned,
    )
    return path


async def main() -> int:
    parser = argparse.ArgumentParser(description="Take a local database snapshot")
    parser.add_argument("--reason", default="manual", help="what this snapshot is for")
    args = parser.parse_args()

    configure_logging(json_output=False)
    try:
        path = take_snapshot(args.reason)
    except BackupFailed as exc:
        print(f"\n  Backup failed: {exc}")  # noqa: T201
        print("  Nothing destructive should run until this is fixed.\n")  # noqa: T201
        return 1

    print(f"\n  Snapshot written: {path.name} ({path.stat().st_size:,} bytes)")  # noqa: T201
    print(f"  Location on the host: backups/{path.name}\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
