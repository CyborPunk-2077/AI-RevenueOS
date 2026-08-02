"""Pipelines, stages and deals.

`domain/deals/pipeline_policy.py` already owns the rules -- required fields,
direction limits, loss reasons, status transitions, weighted value -- and is unit
tested. This service is orchestration only: load the stage specs, hand them to the
policy, persist what it returns. Re-implementing any of that here would give two
answers to the same question.

A tenant gets a default pipeline on first use rather than as part of sign-up
seeding. Provisioning it lazily means an organisation created before this module
existed still works, and there is no migration to backfill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.base import DomainEvent
from domain.deals.pipeline_policy import (
    DealStatus,
    StageMoveRequest,
    StageSpec,
    assert_status_transition,
    validate_stage_move,
    weighted_pipeline_value,
)
from domain.events.catalog import (
    OPPORTUNITY_CREATED,
    OPPORTUNITY_LOST,
    OPPORTUNITY_STAGE_CHANGED,
    OPPORTUNITY_UPDATED,
    OPPORTUNITY_WON,
)
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound, ValidationError
from shared.pagination import Page
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.crm.deals")

DEFAULT_PIPELINE_NAME = "Sales"

# Applied when a tenant has no pipeline yet. Probabilities are the usual SME sales
# ladder; a tenant can rename or re-weight later without a migration.
DEFAULT_STAGES: tuple[dict[str, Any], ...] = (
    {"name": "New", "position": 0, "probability": 10},
    {"name": "Qualified", "position": 1, "probability": 30},
    {"name": "Proposal", "position": 2, "probability": 60},
    {"name": "Negotiation", "position": 3, "probability": 80},
    {"name": "Won", "position": 4, "probability": 100, "is_won": True},
    {"name": "Lost", "position": 5, "probability": 0, "is_lost": True},
)


def serialize_stage(row: Any, *, deal_count: int = 0, value_minor: int = 0) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "position": row.position,
        "probability": row.probability,
        "is_won": row.is_won,
        "is_lost": row.is_lost,
        "required_fields": list(row.required_fields or []),
        "deal_count": deal_count,
        "value_minor": value_minor,
    }


def serialize_deal(
    row: Any,
    *,
    stage_name: str | None = None,
    contact_name: str | None = None,
    account_name: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "probability": row.probability,
        "status": row.status,
        "loss_reason": row.loss_reason,
        "pipeline_id": str(row.pipeline_id),
        "stage_id": str(row.stage_id),
        "stage_name": stage_name,
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "contact_name": contact_name,
        "account_id": str(row.account_id) if row.account_id else None,
        "account_name": account_name,
        "assignee_id": str(row.assignee_id) if row.assignee_id else None,
        "expected_close_date": (
            row.expected_close_date.isoformat() if row.expected_close_date else None
        ),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _spec(row: Any) -> StageSpec:
    """A database stage as the policy's value object."""
    rules = dict(row.transition_rules or {})
    return StageSpec(
        id=str(row.id),
        name=row.name,
        position=row.position,
        probability=row.probability,
        required_fields=tuple(row.required_fields or []),
        is_won=row.is_won,
        is_lost=row.is_lost,
        allow_skip_forward=bool(rules.get("allow_skip_forward", True)),
        allow_backward=bool(rules.get("allow_backward", True)),
    )


@dataclass(slots=True)
class DealService(_PrincipalScoped):
    """Pipelines, stages and the deals moving through them."""

    # --- pipeline provisioning ---------------------------------------------

    async def ensure_pipeline(self) -> dict[str, Any]:
        """Return the tenant's default pipeline, creating it on first use.

        Idempotent under concurrency by the `pipeline_tenant_name` unique
        constraint: a losing racer re-reads rather than raising.
        """
        from sqlalchemy import select

        from infrastructure.database.models.crm import Pipeline, Stage
        from infrastructure.database.session import tenant_session
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        async with tenant_session(self.tenant_id) as session:
            existing = (
                (
                    await session.execute(
                        select(Pipeline)
                        .where(Pipeline.deleted_at.is_(None), Pipeline.is_active.is_(True))
                        .order_by(Pipeline.is_default.desc(), Pipeline.created_at.asc())
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return {"id": str(existing.id), "name": existing.name}

        pipeline_id = uuid7()
        try:
            async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
                uow.session.add(
                    Pipeline(
                        id=pipeline_id,
                        tenant_id=self.tenant_id,
                        entity_type="deal",
                        name=DEFAULT_PIPELINE_NAME,
                        is_default=True,
                        is_active=True,
                        version=1,
                    )
                )
                await uow.session.flush()
                for stage in DEFAULT_STAGES:
                    uow.session.add(
                        Stage(
                            id=uuid7(),
                            tenant_id=self.tenant_id,
                            pipeline_id=pipeline_id,
                            name=stage["name"],
                            position=stage["position"],
                            probability=stage["probability"],
                            is_won=bool(stage.get("is_won", False)),
                            is_lost=bool(stage.get("is_lost", False)),
                            version=1,
                        )
                    )
        except Exception:
            # Lost the race. Re-read rather than failing the caller's request.
            async with tenant_session(self.tenant_id) as session:
                found = (
                    (
                        await session.execute(
                            select(Pipeline).where(
                                Pipeline.name == DEFAULT_PIPELINE_NAME,
                                Pipeline.deleted_at.is_(None),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if found is None:
                    raise
                return {"id": str(found.id), "name": found.name}

        logger.info("pipeline_provisioned", tenant_id=str(self.tenant_id))
        return {"id": str(pipeline_id), "name": DEFAULT_PIPELINE_NAME}

    async def _stages(self, session: Any, pipeline_id: UUID) -> list[Any]:
        from sqlalchemy import select

        from infrastructure.database.models.crm import Stage

        return list(
            (
                await session.execute(
                    select(Stage)
                    .where(Stage.pipeline_id == pipeline_id)
                    .order_by(Stage.position.asc())
                )
            )
            .scalars()
            .all()
        )

    # --- board -------------------------------------------------------------

    async def board(self) -> dict[str, Any]:
        """The pipeline as columns of open deals, with per-stage totals."""
        pipeline = await self.ensure_pipeline()
        pipeline_id = UUID(pipeline["id"])

        from infrastructure.database.models.crm import Deal
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        async with tenant_session(self.tenant_id) as session:
            stages = await self._stages(session, pipeline_id)
            repo = DealRepository(session, self.tenant_id)
            rows = list(
                (
                    await session.execute(
                        repo.scoped_query(self.permissions_scope())
                        .where(Deal.pipeline_id == pipeline_id)
                        .order_by(Deal.created_at.desc())
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
            names = {s.id: s.name for s in stages}
            by_stage: dict[str, list[dict[str, Any]]] = {str(s.id): [] for s in stages}
            for row in rows:
                key = str(row.stage_id)
                if key in by_stage:
                    by_stage[key].append(serialize_deal(row, stage_name=names.get(row.stage_id)))

        columns = []
        for stage in stages:
            deals = by_stage[str(stage.id)]
            columns.append(
                {
                    **serialize_stage(
                        stage,
                        deal_count=len(deals),
                        value_minor=sum(d["amount_minor"] for d in deals),
                    ),
                    "deals": deals,
                }
            )

        all_deals = [d for column in columns for d in column["deals"]]
        return {
            "pipeline": pipeline,
            "stages": columns,
            "totals": {
                "open_count": sum(1 for d in all_deals if d["status"] == "open"),
                "open_value_minor": sum(
                    d["amount_minor"] for d in all_deals if d["status"] == "open"
                ),
                # The domain function, not a re-derivation: it excludes closed
                # deals, which a naive sum would silently include.
                "weighted_value_minor": weighted_pipeline_value(all_deals),
                "won_value_minor": sum(
                    d["amount_minor"] for d in all_deals if d["status"] == "won"
                ),
            },
        }

    # --- deals -------------------------------------------------------------

    async def list_deals(self, query: Any, *, status: str | None = None) -> Page:
        from infrastructure.database.models.crm import Deal
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        async with tenant_session(self.tenant_id) as session:
            repo = DealRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if status:
                if status not in {s.value for s in DealStatus}:
                    raise ValidationError(f"Unknown status: {status!r}.")
                stmt = stmt.where(Deal.status == status)
            page = await repo.paginate_cursor(
                self.permissions_scope(), stmt, cursor=query.cursor, page_size=query.page_size
            )
            page.items = [serialize_deal(d) for d in page.items]
            return page

    async def get(self, deal_id: UUID) -> dict[str, Any]:
        from sqlalchemy import select

        from infrastructure.database.models.crm import Account, Contact, Deal, Stage
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        async with tenant_session(self.tenant_id) as session:
            deal = await DealRepository(session, self.tenant_id).get_scoped(
                deal_id, self.permissions_scope()
            )
            if deal is None:
                raise NotFound("Deal not found.")

            stage_name = (
                await session.execute(select(Stage.name).where(Stage.id == deal.stage_id))
            ).scalar_one_or_none()
            contact_name = None
            if deal.contact_id:
                row = (
                    await session.execute(
                        select(Contact.first_name, Contact.last_name).where(
                            Contact.id == deal.contact_id, Contact.deleted_at.is_(None)
                        )
                    )
                ).first()
                if row:
                    contact_name = f"{row[0]} {row[1] or ''}".strip()
            account_name = None
            if deal.account_id:
                account_name = (
                    await session.execute(
                        select(Account.name).where(
                            Account.id == deal.account_id, Account.deleted_at.is_(None)
                        )
                    )
                ).scalar_one_or_none()

            return serialize_deal(
                deal,
                stage_name=stage_name,
                contact_name=contact_name,
                account_name=account_name,
            )

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Deal
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValidationError("A title is required.")

        pipeline = await self.ensure_pipeline()
        pipeline_id = UUID(pipeline["id"])
        deal_id = uuid7()

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            stages = await self._stages(uow.session, pipeline_id)
            if not stages:
                raise ValidationError("This pipeline has no stages.")

            requested = payload.get("stage_id")
            if requested:
                stage = next((s for s in stages if s.id == requested), None)
                if stage is None:
                    raise NotFound("Stage not found.")
            else:
                stage = stages[0]

            await self._assert_links_visible(uow.session, payload)

            uow.session.add(
                Deal(
                    id=deal_id,
                    tenant_id=self.tenant_id,
                    title=title[:250],
                    amount_minor=int(payload.get("amount_minor") or 0),
                    currency=str(payload.get("currency") or "INR"),
                    probability=stage.probability,
                    status=DealStatus.OPEN.value,
                    pipeline_id=pipeline_id,
                    stage_id=stage.id,
                    contact_id=payload.get("contact_id"),
                    account_id=payload.get("account_id"),
                    assignee_id=payload.get("assignee_id") or self.user_id,
                    expected_close_date=payload.get("expected_close_date"),
                    created_by=self.user_id,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="deal.create",
                resource_type="deal",
                resource_id=deal_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"title": title, "amount_minor": payload.get("amount_minor")},
            )
            uow.collect(
                DomainEvent(
                    event_type=OPPORTUNITY_CREATED,
                    tenant_id=self.tenant_id,
                    resource_type="deal",
                    resource_id=deal_id,
                    actor_id=self.user_id,
                    payload={
                        "stage_id": str(stage.id),
                        "amount_minor": payload.get("amount_minor"),
                    },
                )
            )

        logger.info("deal_created", tenant_id=str(self.tenant_id), deal_id=str(deal_id))
        return await self.get(deal_id)

    async def _assert_links_visible(self, session: Any, payload: dict[str, Any]) -> None:
        """A contact or account from another tenant must be as absent as a fake id."""
        from infrastructure.database.models.crm import Account, Contact
        from infrastructure.database.repositories.base import TenantRepository

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        class AccountRepository(TenantRepository[Account]):
            model = Account

        if payload.get("contact_id") and (
            await ContactRepository(session, self.tenant_id).get(
                payload["contact_id"], self.permissions_scope()
            )
            is None
        ):
            raise NotFound("Contact not found.")
        if payload.get("account_id") and (
            await AccountRepository(session, self.tenant_id).get(
                payload["account_id"], self.permissions_scope()
            )
            is None
        ):
            raise NotFound("Account not found.")

    async def update(
        self, deal_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder, diff_for_audit
        from infrastructure.database.models.crm import Deal
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = DealRepository(uow.session, self.tenant_id)
            deal = await repo.get_scoped_or_404(deal_id, self.permissions_scope())
            before = serialize_deal(deal)

            await self._assert_links_visible(uow.session, changes)

            for field_name, value in changes.items():
                if field_name in {"contact_id", "account_id"} or value is not None:
                    setattr(deal, field_name, value)

            await repo.bump_version(deal, expected_version)
            deal.updated_by = self.user_id
            after = serialize_deal(deal)

            old_values, new_values = diff_for_audit(before, after)
            AuditRecorder(uow.session).record(
                action="deal.update",
                resource_type="deal",
                resource_id=deal_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values=old_values,
                new_values=new_values,
            )
            uow.collect(
                DomainEvent(
                    event_type=OPPORTUNITY_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="deal",
                    resource_id=deal_id,
                    actor_id=self.user_id,
                    payload={"changed": sorted(changes)},
                )
            )
        return await self.get(deal_id)

    async def move_stage(
        self,
        deal_id: UUID,
        target_stage_id: UUID,
        *,
        loss_reason: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Move a deal between stages. Every rule comes from the domain policy."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Deal
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = DealRepository(uow.session, self.tenant_id)
            deal = await repo.get_scoped_or_404(deal_id, self.permissions_scope())

            stages = await self._stages(uow.session, deal.pipeline_id)
            source = next((s for s in stages if s.id == deal.stage_id), None)
            target = next((s for s in stages if s.id == target_stage_id), None)
            if target is None:
                raise NotFound("Stage not found.")
            if source is None:
                raise ValidationError("This deal's current stage no longer exists.")

            # `validate_stage_move` raises InvalidTransition or PolicyViolation,
            # which the API error mapper already turns into typed responses.
            result = validate_stage_move(
                StageMoveRequest(
                    from_stage=_spec(source),
                    to_stage=_spec(target),
                    deal_fields=serialize_deal(deal),
                    loss_reason=loss_reason,
                    status=DealStatus(deal.status),
                )
            )

            previous_stage = str(deal.stage_id)
            deal.stage_id = target.id
            deal.probability = result.probability
            deal.status = result.status.value
            if result.status is DealStatus.LOST:
                deal.loss_reason = loss_reason
            if result.status in {DealStatus.WON, DealStatus.LOST}:
                deal.closed_at = utcnow()
            else:
                deal.closed_at = None
                deal.loss_reason = None

            await repo.bump_version(deal, expected_version)
            deal.updated_by = self.user_id

            AuditRecorder(uow.session).record(
                action="deal.stage_change",
                resource_type="deal",
                resource_id=deal_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values={"stage_id": previous_stage},
                new_values={"stage_id": str(target.id), "status": deal.status},
            )

            events = [
                DomainEvent(
                    event_type=OPPORTUNITY_STAGE_CHANGED,
                    tenant_id=self.tenant_id,
                    resource_type="deal",
                    resource_id=deal_id,
                    actor_id=self.user_id,
                    payload={
                        "from_stage_id": previous_stage,
                        "to_stage_id": str(target.id),
                        "status": deal.status,
                    },
                )
            ]
            if result.status is DealStatus.WON:
                events.append(
                    DomainEvent(
                        event_type=OPPORTUNITY_WON,
                        tenant_id=self.tenant_id,
                        resource_type="deal",
                        resource_id=deal_id,
                        actor_id=self.user_id,
                        payload={"amount_minor": deal.amount_minor},
                    )
                )
            elif result.status is DealStatus.LOST:
                events.append(
                    DomainEvent(
                        event_type=OPPORTUNITY_LOST,
                        tenant_id=self.tenant_id,
                        resource_type="deal",
                        resource_id=deal_id,
                        actor_id=self.user_id,
                        payload={"loss_reason": loss_reason},
                    )
                )
            uow.collect(*events)

        logger.info("deal_stage_changed", deal_id=str(deal_id), status=deal.status)
        return await self.get(deal_id)

    async def reopen(self, deal_id: UUID, *, expected_version: int | None = None) -> dict[str, Any]:
        """Reopen a closed deal. The transition itself is the domain's decision."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Deal
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = DealRepository(uow.session, self.tenant_id)
            deal = await repo.get_scoped_or_404(deal_id, self.permissions_scope())
            target = assert_status_transition(deal.status, DealStatus.OPEN)

            deal.status = target.value
            deal.closed_at = None
            deal.loss_reason = None
            await repo.bump_version(deal, expected_version)
            deal.updated_by = self.user_id

            AuditRecorder(uow.session).record(
                action="deal.reopen",
                resource_type="deal",
                resource_id=deal_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"status": target.value},
            )
            uow.collect(
                DomainEvent(
                    event_type=OPPORTUNITY_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="deal",
                    resource_id=deal_id,
                    actor_id=self.user_id,
                    payload={"reopened": True},
                )
            )
        return await self.get(deal_id)
