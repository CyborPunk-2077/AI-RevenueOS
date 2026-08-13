"""Tell Sangam which workspace owns a WhatsApp business number. LOCAL ONLY.

Meta sends every message for an app to one webhook. The only thing in the payload
that says *which business* it was for is the phone number id it arrived on, so
that id has to be claimed by a workspace before anything can be routed.

Without this row an inbound message is refused rather than guessed at. That is the
right behaviour and it is also the single most confusing failure during a first
live test, which is why this script exists instead of a line of SQL in a document.

    python src/scripts/claim_whatsapp_number.py --slug sharma-motors \
        --phone-number-id 123456789012345 --display "+91 90000 00000"

Re-running for the same workspace updates the number rather than adding a second.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from infrastructure.database.models.communications import Channel
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.session import admin_session
from infrastructure.logging.setup import configure_logging, get_logger
from shared.utils.ids import uuid7

logger = get_logger("scripts.claim_whatsapp_number")


async def claim(*, slug: str, phone_number_id: str, display_name: str) -> dict[str, str]:
    async with admin_session() as session:
        tenant = (
            await session.execute(
                select(Tenant.id, Tenant.name).where(
                    Tenant.slug == slug, Tenant.deleted_at.is_(None)
                )
            )
        ).first()
        if tenant is None:
            raise SystemExit(f"No workspace with the id '{slug}'.")
        tenant_id, tenant_name = tenant

        # One workspace may not silently take a number another one is already
        # using: two tenants claiming the same id would make routing ambiguous,
        # and the losing business would find its customers in somebody else's
        # workspace.
        clash = (
            await session.execute(
                select(Channel.tenant_id).where(
                    Channel.channel_type == "whatsapp",
                    Channel.identifier == phone_number_id,
                    Channel.tenant_id != tenant_id,
                    Channel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise SystemExit(
                f"Phone number id {phone_number_id} is already claimed by another workspace. "
                "Release it there first."
            )

        existing = (
            await session.execute(
                select(Channel).where(
                    Channel.tenant_id == tenant_id,
                    Channel.channel_type == "whatsapp",
                    Channel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                Channel(
                    id=uuid7(),
                    tenant_id=tenant_id,
                    channel_type="whatsapp",
                    identifier=phone_number_id,
                    display_name=display_name or "WhatsApp business number",
                    settings={},
                    is_active=True,
                    # Not "healthy". Nothing has been proven yet - the Test Centre
                    # decides that by calling Meta, and this script has not.
                    health_status="unconfigured",
                    health_detail={},
                    version=1,
                )
            )
            action = "claimed"
        else:
            existing.identifier = phone_number_id
            if display_name:
                existing.display_name = display_name
            existing.is_active = True
            action = "updated"

    logger.info("whatsapp_number_claimed", slug=slug, action=action)
    return {"tenant": str(tenant_name), "slug": slug, "action": action}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Claim a WhatsApp business number")
    parser.add_argument("--slug", required=True, help="the workspace id, e.g. sharma-motors")
    parser.add_argument("--phone-number-id", required=True, help="Meta's Phone number ID")
    parser.add_argument("--display", default="", help="how to show the number in Sangam")
    args = parser.parse_args()

    configure_logging(json_output=False)
    result = await claim(
        slug=args.slug,
        phone_number_id=args.phone_number_id.strip(),
        display_name=args.display.strip(),
    )

    print("\n" + "=" * 64)  # noqa: T201
    print(f"  WhatsApp number {result['action']} for: {result['tenant']}")  # noqa: T201
    print("=" * 64)  # noqa: T201
    print("  Inbound messages on this number now belong to this workspace.")  # noqa: T201
    print("  Nothing has been sent, and nothing has been verified with Meta yet -")  # noqa: T201
    print("  open the Test Centre to check the connection itself.")  # noqa: T201
    print("=" * 64 + "\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
