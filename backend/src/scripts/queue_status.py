"""Operator view of the worker tier: queue depths, live workers and dead letters.

python src/scripts/queue_status.py
python src/scripts/queue_status.py --dead-letters
python src/scripts/queue_status.py --replay <dead_letter_id>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.celery.health import inspect_active_workers
from infrastructure.celery.queues import BY_NAME, WORKER_POOLS
from infrastructure.logging.setup import configure_logging


async def show_queues() -> int:
    from infrastructure.celery.tasks.scheduled import queue_depths

    depths = await queue_depths()
    print(f"{'queue':24} {'depth':>6} {'conc':>5} {'prio':>5} {'timeout':>8}")  # noqa: T201
    print("-" * 52)  # noqa: T201
    for name, spec in BY_NAME.items():
        depth = depths.get(name, 0)
        print(  # noqa: T201
            f"{name:24} {depth:>6} {spec.concurrency:>5} "
            f"{spec.spec_priority:>5} {spec.timeout_seconds:>7}s"
        )

    print("\npools:")  # noqa: T201
    for pool, queues in WORKER_POOLS.items():
        print(f"  {pool:10} {', '.join(queues)}")  # noqa: T201

    workers = inspect_active_workers()
    print(f"\nlive workers: {workers.get('count', 0)}")  # noqa: T201
    for name in workers.get("workers", []):
        print(f"  {name}")  # noqa: T201
    if workers.get("error"):
        print(f"  (broker unreachable: {workers['error']})")  # noqa: T201
    return 0


async def show_dead_letters(limit: int) -> int:
    from sqlalchemy import text

    from infrastructure.database.session import platform_session

    async with platform_session("operator: list dead letters") as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, queue, task_name, attempts, tenant_id, "
                        "       left(error, 80) AS error, created_at, replayed_at "
                        "FROM app.dead_letters ORDER BY created_at DESC LIMIT :n"
                    ),
                    {"n": limit},
                )
            )
            .mappings()
            .all()
        )

    if not rows:
        print("no dead letters")  # noqa: T201
        return 0

    for row in rows:
        replayed = " [replayed]" if row["replayed_at"] else ""
        print(  # noqa: T201
            f"{row['id']}  {row['queue']:22} {row['task_name']:34} "
            f"attempts={row['attempts']}{replayed}"
        )
        print(f"    tenant={row['tenant_id']}  {row['error']}")  # noqa: T201
    return 0


async def replay(dead_letter_id: str) -> int:
    from infrastructure.celery.reliability import replay_dead_letter

    result = await replay_dead_letter(UUID(dead_letter_id))
    print(result)  # noqa: T201
    return 0 if result.get("replayed") else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description="AI RevenueOS worker tier status")
    parser.add_argument("--dead-letters", action="store_true", help="list recent dead letters")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--replay", metavar="DEAD_LETTER_ID", help="re-enqueue a dead letter")
    args = parser.parse_args()

    configure_logging(json_output=False)
    if args.replay:
        return await replay(args.replay)
    if args.dead_letters:
        return await show_dead_letters(args.limit)
    return await show_queues()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
