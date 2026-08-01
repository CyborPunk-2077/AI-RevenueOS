"""Outbox poller entrypoint. Target cadence 500 ms, batch 100, SKIP LOCKED."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.database.session import get_sessionmaker
from infrastructure.logging.setup import configure_logging, get_logger
from infrastructure.messaging.outbox import OutboxDispatcher

logger = get_logger("scripts.outbox")


async def main() -> None:
    configure_logging()
    dispatcher = OutboxDispatcher(get_sessionmaker())

    from application.crm.handlers import register_crm_handlers

    register_crm_handlers(dispatcher)

    from application.workflows.triggers import register_workflow_handlers

    register_workflow_handlers(dispatcher)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, dispatcher.stop)

    logger.info("outbox_poller_starting")
    await dispatcher.run_forever()
    logger.info("outbox_poller_stopped")


if __name__ == "__main__":
    asyncio.run(main())
