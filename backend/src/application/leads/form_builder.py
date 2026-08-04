"""Form builder: draft, edit, publish, unpublish.

The publish step is the whole point of this module. `schema_json` is the draft the
builder edits; `published_schema` is the immutable snapshot the public endpoint
serves. Editing a draft therefore cannot change what a live form does - a
half-finished field rename cannot reach the internet - and publishing is an
explicit, audited act with a timestamp.

Unpublishing takes the form offline but keeps the snapshot, so republishing is a
decision rather than a rebuild, and so an incident can be answered with "what was
live at 14:00" rather than a guess.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from application.audit.recorder import AuditRecorder
from domain.leads.form_schema import validate_form_schema, validate_origins
from infrastructure.database.models.leads import Form
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span
from shared.exceptions import Conflict, NotFound, PreconditionFailed
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.leads.form_builder")

FORM_TYPES = ("embedded", "hosted", "popup")
MAX_FORMS_PER_TENANT = 200


def _serialize(form: Form) -> dict[str, Any]:
    return {
        "id": str(form.id),
        "name": form.name,
        "type": form.form_type,
        "source": form.source,
        "schema": form.schema_json,
        "settings": form.settings,
        "allowed_origins": list(form.allowed_origins or []),
        "is_published": form.is_published,
        "published_schema": form.published_schema,
        "published_at": form.published_at.isoformat() if form.published_at else None,
        # True when the draft has moved on since the last publish. The builder
        # needs it to show "you have unpublished changes" rather than implying the
        # edit is already live.
        "has_unpublished_changes": bool(
            form.is_published and form.schema_json != form.published_schema
        ),
        "version": form.version,
        "created_at": form.created_at.isoformat() if form.created_at else None,
        "updated_at": form.updated_at.isoformat() if form.updated_at else None,
    }


async def _load(session: Any, tenant_id: UUID, form_id: UUID) -> Form:
    form: Form | None = (
        await session.execute(
            select(Form).where(
                Form.id == form_id, Form.tenant_id == tenant_id, Form.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if form is None:
        raise NotFound("That form does not exist.")
    return form


async def list_forms(*, tenant_id: UUID, include_archived: bool = False) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        statement = select(Form).where(Form.tenant_id == tenant_id)
        if not include_archived:
            statement = statement.where(Form.deleted_at.is_(None))
        rows = (await session.execute(statement.order_by(Form.created_at.desc()))).scalars().all()
        return [_serialize(form) for form in rows]


async def get_form(*, tenant_id: UUID, form_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return _serialize(await _load(session, tenant_id, form_id))


async def create_form(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    name: str,
    form_type: str = "embedded",
    schema: dict[str, Any],
    allowed_origins: list[Any] | None = None,
    source: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a draft. A new form is never live: publishing is a separate act."""
    if form_type not in FORM_TYPES:
        raise Conflict(f"{form_type!r} is not a form type.", details={"allowed": list(FORM_TYPES)})

    validated = validate_form_schema(schema)
    origins = validate_origins(allowed_origins or [])
    form_id = uuid7()

    with start_span("form create", attributes={"tenant.id": str(tenant_id)}):
        async with tenant_session(tenant_id) as session:
            existing = (
                await session.execute(
                    select(func.count())
                    .select_from(Form)
                    .where(Form.tenant_id == tenant_id, Form.deleted_at.is_(None))
                )
            ).scalar_one()
            if existing >= MAX_FORMS_PER_TENANT:
                raise Conflict(
                    f"This organisation already has {MAX_FORMS_PER_TENANT} forms.",
                    details={"limit": MAX_FORMS_PER_TENANT},
                )

            session.add(
                Form(
                    id=form_id,
                    tenant_id=tenant_id,
                    name=name.strip()[:150],
                    form_type=form_type,
                    schema_json=validated,
                    settings=settings or {},
                    source=(source or "").strip()[:80] or None,
                    allowed_origins=origins,
                    is_published=False,
                    published_schema={},
                    created_by=actor_id,
                    updated_by=actor_id,
                    version=1,
                )
            )
            AuditRecorder(session).record(
                action="form.created",
                resource_type="form",
                resource_id=form_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                new_values={"name": name.strip()[:150], "type": form_type},
            )
            await session.flush()
            form = await _load(session, tenant_id, form_id)
            result = _serialize(form)

    logger.info("form_created", tenant_id=str(tenant_id), form_id=str(form_id))
    return result


async def update_form(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    form_id: UUID,
    expected_version: int | None = None,
    name: str | None = None,
    schema: dict[str, Any] | None = None,
    allowed_origins: list[Any] | None = None,
    settings: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Edit the draft. What is published does not move until `publish_form`."""
    validated = validate_form_schema(schema) if schema is not None else None
    origins = validate_origins(allowed_origins) if allowed_origins is not None else None

    async with tenant_session(tenant_id) as session:
        form = await _load(session, tenant_id, form_id)
        if expected_version is not None and form.version != expected_version:
            raise PreconditionFailed(
                "This form changed since you loaded it.",
                details={"expected": expected_version, "current": form.version},
            )

        before = {"name": form.name, "version": form.version}
        if name is not None:
            form.name = name.strip()[:150]
        if validated is not None:
            form.schema_json = validated
        if origins is not None:
            form.allowed_origins = origins
        if settings is not None:
            form.settings = settings
        if source is not None:
            form.source = source.strip()[:80] or None
        form.updated_by = actor_id
        form.version += 1

        AuditRecorder(session).record(
            action="form.updated",
            resource_type="form",
            resource_id=form_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            old_values=before,
            new_values={"name": form.name, "version": form.version},
        )
        return _serialize(form)


async def publish_form(*, tenant_id: UUID, actor_id: UUID, form_id: UUID) -> dict[str, Any]:
    """Snapshot the draft and take the form live.

    The snapshot is what makes this safe: the public endpoint reads
    `published_schema`, so subsequent edits to the draft are invisible until the
    next publish.
    """
    with start_span("form publish", attributes={"tenant.id": str(tenant_id)}):
        async with tenant_session(tenant_id) as session:
            form = await _load(session, tenant_id, form_id)

            # Re-validate at publish time. The draft may predate a tightening of
            # the rules, and the moment it becomes internet-reachable is the right
            # moment to refuse it.
            snapshot = validate_form_schema(form.schema_json)

            form.published_schema = snapshot
            form.schema_json = snapshot
            form.is_published = True
            form.published_at = utcnow()
            form.updated_by = actor_id
            form.version += 1

            AuditRecorder(session).record(
                action="form.published",
                resource_type="form",
                resource_id=form_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                new_values={
                    "is_published": True,
                    "field_count": len(snapshot["fields"]),
                    "allowed_origins": list(form.allowed_origins or []),
                },
            )
            result = _serialize(form)

    logger.info("form_published", tenant_id=str(tenant_id), form_id=str(form_id))
    return result


async def unpublish_form(*, tenant_id: UUID, actor_id: UUID, form_id: UUID) -> dict[str, Any]:
    """Take the form offline. The snapshot is kept, so republishing is one act."""
    async with tenant_session(tenant_id) as session:
        form = await _load(session, tenant_id, form_id)
        if not form.is_published:
            return _serialize(form)

        form.is_published = False
        form.updated_by = actor_id
        form.version += 1

        AuditRecorder(session).record(
            action="form.unpublished",
            resource_type="form",
            resource_id=form_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            old_values={"is_published": True},
            new_values={"is_published": False},
        )
        return _serialize(form)


async def archive_form(*, tenant_id: UUID, actor_id: UUID, form_id: UUID) -> dict[str, Any]:
    """Soft delete, and take it offline in the same transaction.

    An archived form that stays published would keep accepting submissions from
    every page that already embeds it.
    """
    async with tenant_session(tenant_id) as session:
        form = await _load(session, tenant_id, form_id)
        form.is_published = False
        form.deleted_at = utcnow()
        form.updated_by = actor_id
        form.version += 1

        AuditRecorder(session).record(
            action="form.archived",
            resource_type="form",
            resource_id=form_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"archived": True, "is_published": False},
        )
        return {"id": str(form_id), "archived": True, "is_published": False}
