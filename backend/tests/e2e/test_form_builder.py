"""Draft and published are two different things, and the public sees only one."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from application.leads import form_builder
from application.leads.forms import get_published_form
from shared.exceptions import NotFound, PreconditionFailed, ValidationError

pytestmark = pytest.mark.postgres

DRAFT: dict[str, Any] = {
    "fields": [
        {"name": "email", "type": "email", "required": True, "label": "Work email"},
        {"name": "company", "type": "text"},
    ],
    "submit_label": "Talk to sales",
}


async def _form(tenant_id: UUID, **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "actor_id": uuid4(),
        "name": f"Contact {uuid4().hex[:8]}",
        "schema": DRAFT,
        "allowed_origins": ["https://example.in"],
    }
    payload.update(over)
    return await form_builder.create_form(**payload)


async def test_a_new_form_is_a_draft_and_is_not_reachable(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)

    assert created["is_published"] is False
    assert created["published_schema"] == {}
    assert await get_published_form(UUID(created["id"])) is None


async def test_publishing_snapshots_the_draft(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)

    published = await form_builder.publish_form(
        tenant_id=tenant_a, actor_id=uuid4(), form_id=UUID(created["id"])
    )

    assert published["is_published"] is True
    assert published["published_at"] is not None
    assert [f["name"] for f in published["published_schema"]["fields"]] == ["email", "company"]

    live = await get_published_form(UUID(created["id"]))
    assert live is not None
    assert live["schema"] == published["published_schema"]


async def test_editing_a_draft_does_not_change_what_is_live(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    """The snapshot is the whole point: a half-finished edit cannot reach the internet."""
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)
    form_id = UUID(created["id"])
    await form_builder.publish_form(tenant_id=tenant_a, actor_id=uuid4(), form_id=form_id)

    edited = await form_builder.update_form(
        tenant_id=tenant_a,
        actor_id=uuid4(),
        form_id=form_id,
        schema={
            "fields": [
                {"name": "email", "type": "email", "required": True},
                {"name": "budget", "type": "select", "options": ["<5L", "5-20L"]},
            ]
        },
    )

    assert edited["has_unpublished_changes"] is True
    live = await get_published_form(form_id)
    assert live is not None
    assert [f["name"] for f in live["schema"]["fields"]] == ["email", "company"]

    await form_builder.publish_form(tenant_id=tenant_a, actor_id=uuid4(), form_id=form_id)
    republished = await get_published_form(form_id)
    assert republished is not None
    assert [f["name"] for f in republished["schema"]["fields"]] == ["email", "budget"]


async def test_unpublishing_takes_it_offline_but_keeps_the_snapshot(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)
    form_id = UUID(created["id"])
    await form_builder.publish_form(tenant_id=tenant_a, actor_id=uuid4(), form_id=form_id)

    offline = await form_builder.unpublish_form(
        tenant_id=tenant_a, actor_id=uuid4(), form_id=form_id
    )

    assert offline["is_published"] is False
    assert offline["published_schema"]["fields"], "the snapshot must survive"
    assert await get_published_form(form_id) is None


async def test_archiving_also_takes_the_form_offline(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    """An archived form that stayed live would keep accepting embedded submissions."""
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)
    form_id = UUID(created["id"])
    await form_builder.publish_form(tenant_id=tenant_a, actor_id=uuid4(), form_id=form_id)

    await form_builder.archive_form(tenant_id=tenant_a, actor_id=uuid4(), form_id=form_id)

    assert await get_published_form(form_id) is None
    with pytest.raises(NotFound):
        await form_builder.get_form(tenant_id=tenant_a, form_id=form_id)


async def test_publishing_revalidates_the_draft(wired_engine: Any, seeded_tenants: Any) -> None:
    """The rules may have tightened since the draft was written."""
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)

    with pytest.raises(ValidationError):
        await form_builder.update_form(
            tenant_id=tenant_a,
            actor_id=uuid4(),
            form_id=UUID(created["id"]),
            schema={"fields": [{"name": "message", "type": "textarea"}]},
        )


async def test_a_stale_version_is_refused(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants
    created = await _form(tenant_a)

    with pytest.raises(PreconditionFailed):
        await form_builder.update_form(
            tenant_id=tenant_a,
            actor_id=uuid4(),
            form_id=UUID(created["id"]),
            expected_version=created["version"] + 5,
            name="Renamed",
        )


async def test_a_form_is_invisible_to_another_tenant(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    created = await _form(tenant_a)

    listed_b = await form_builder.list_forms(tenant_id=tenant_b)
    assert all(item["id"] != created["id"] for item in listed_b)

    with pytest.raises(NotFound):
        await form_builder.get_form(tenant_id=tenant_b, form_id=UUID(created["id"]))

    with pytest.raises(NotFound):
        await form_builder.publish_form(
            tenant_id=tenant_b, actor_id=uuid4(), form_id=UUID(created["id"])
        )
