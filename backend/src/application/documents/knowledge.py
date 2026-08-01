"""Public knowledge surface: published, public articles only."""

from __future__ import annotations

from typing import Any


async def list_public_articles(tenant_slug: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from infrastructure.database.models.documents import KnowledgeArticle
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.database.session import tenant_session, unscoped_session

    async with unscoped_session() as session:
        tenant_id = (
            await session.execute(select(Tenant.id).where(Tenant.slug == tenant_slug))
        ).scalar_one_or_none()
    if tenant_id is None:
        return []
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(KnowledgeArticle)
                    .where(
                        KnowledgeArticle.is_published.is_(True),
                        KnowledgeArticle.is_public.is_(True),
                        KnowledgeArticle.deleted_at.is_(None),
                    )
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
    return [{"slug": a.slug, "title": a.title} for a in rows]
