"""Worker health probe for Compose `healthcheck` and the ECS container check.

Exit 0 when ready, 1 otherwise, so it can be used directly as a container probe:

    python src/scripts/worker_health.py --pool comms
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.celery.health import check_worker


async def main() -> int:
    parser = argparse.ArgumentParser(description="AI RevenueOS worker health probe")
    parser.add_argument("--pool", default="general", help="worker pool name")
    parser.add_argument(
        "--liveness-only",
        action="store_true",
        help="pass when the broker is reachable, even if the database is not",
    )
    args = parser.parse_args()

    health = await check_worker(args.pool)
    print(json.dumps(health.to_dict()))  # noqa: T201 - this is the probe's output
    return 0 if (health.alive if args.liveness_only else health.ready) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
