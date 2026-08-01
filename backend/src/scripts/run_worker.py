"""Worker entrypoint that starts the pool's queues with the specified concurrency.

Concurrency comes from the queue table, so a pool never silently runs with Celery's
default. Prefer this over a bare `celery worker` invocation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.celery.app import app
from infrastructure.celery.queues import BY_NAME, WORKER_POOLS


def main() -> int:
    parser = argparse.ArgumentParser(description="Start an AI RevenueOS worker pool")
    parser.add_argument("--pool", default="general", choices=sorted(WORKER_POOLS))
    parser.add_argument("--loglevel", default="INFO")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="override the concurrency derived from the queue table",
    )
    args = parser.parse_args()

    queues = WORKER_POOLS[args.pool]
    # The pool's concurrency is the largest its queues require.
    concurrency = args.concurrency or max(BY_NAME[q].concurrency for q in queues)

    app.worker_main(
        [
            "worker",
            "--queues",
            ",".join(queues),
            "--concurrency",
            str(concurrency),
            "--loglevel",
            args.loglevel,
            "--hostname",
            f"{args.pool}@%h",
            "--prefetch-multiplier",
            "1",
            "--without-gossip",
            "--without-mingle",
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
