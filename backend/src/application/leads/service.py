"""Lead application service: orchestration, permissions, transactions and events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from domain.auth.permissions import EffectivePermissions, Scope
from domain.base import DomainEvent
from domain.events.catalog import LEAD_CREATED, LEAD_QUALIFIED, LEAD_UPDATED
from domain.leads.lifecycle import assert_transition, dedupe_key, find_duplicates
from domain.leads.qualification import (
    Criterion,
    QualificationResult,
    apply_human_decision,
    degraded_result,
    score_from_rubric,
)
from domain.tenants.templates import qualification_criteria
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound
from shared.pagination import Page
from shared.utils.ids import uuid7

logger = get_logger("application.leads")


@dataclass(slots=True)
class LeadService:
    """Constructed per request from the authenticated principal."""

    tenant_id: UUID
    user_id: UUID
    permissions: frozenset[str]
    industry_code: str = "other_sme"
    scope: Scope = Scope.GLOBAL
    branch_ids: frozenset[str] = frozenset()
    team_ids: frozenset[str] = frozenset()

    @classmethod
    def for_principal(cls, principal: Any) -> LeadService:
        return cls(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            permissions=principal.permissions,
            scope=principal.scope,
            branch_ids=principal.branch_ids,
            team_ids=principal.team_ids,
        )

    def permissions_scope(self) -> EffectivePermissions:
        """The scope predicate this principal's queries must be filtered by."""
        return EffectivePermissions(
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
            user_id=str(self.user_id),
        )

    async def list_leads(self, query: Any) -> Page:
        """Branch/team/self scope is applied inside the query, never after fetching."""
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class LeadRepository(TenantRepository[Lead]):
            model = Lead

        async with tenant_session(self.tenant_id) as session:
            repo = LeadRepository(session, self.tenant_id)
            page = await repo.paginate_cursor(
                repo.scoped_query(self.permissions_scope()),
                cursor=query.cursor,
                page_size=query.page_size,
            )
            page.items = [_serialize(lead) for lead in page.items]
            return page

    async def get(self, lead_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class LeadRepository(TenantRepository[Lead]):
            model = Lead

        async with tenant_session(self.tenant_id) as session:
            # Scoped, not merely tenant-filtered: otherwise a self-scoped principal
            # could read any record in the tenant by id.
            lead = await LeadRepository(session, self.tenant_id).get_scoped(
                lead_id, self.permissions_scope()
            )
            if lead is None:
                raise NotFound("Lead not found.")
            return _serialize(lead)

    async def capture(self, payload: dict[str, Any], *, idempotency: Any = None) -> dict[str, Any]:
        """Dedupe is advisory: the source event is always preserved."""
        from infrastructure.database.models.leads import Lead, LeadSourceEvent
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        key = dedupe_key(
            email=payload.get("email"),
            phone=payload.get("phone"),
            name=payload.get("first_name"),
        )
        lead_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            lead = Lead(
                id=lead_id,
                tenant_id=self.tenant_id,
                first_name=payload["first_name"],
                last_name=payload.get("last_name"),
                email=payload.get("email"),
                phone=payload.get("phone"),
                source=payload.get("source", "manual"),
                source_channel=payload.get("source_channel"),
                capture=payload.get("capture", {}),
                utm=payload.get("utm", {}),
                dedupe_key=key,
                status="new",
                assignee_id=payload.get("assignee_id"),
                branch_id=payload.get("branch_id"),
                team_id=payload.get("team_id"),
                created_by=self.user_id,
                version=1,
            )
            uow.session.add(lead)
            uow.session.add(
                LeadSourceEvent(
                    tenant_id=self.tenant_id,
                    source=lead.source,
                    source_channel=lead.source_channel,
                    source_idempotency_key=str(getattr(idempotency, "key", None) or lead_id),
                    # JSONB cannot hold UUID/date objects; Pydantic hands us real
                    # UUIDs for assignee_id and branch_id.
                    raw_payload=_json_safe(payload),
                    normalized={"dedupe_key": key},
                    utm=payload.get("utm", {}),
                    lead_id=lead_id,
                    outcome="created",
                )
            )
            uow.collect(
                DomainEvent(
                    event_type=LEAD_CREATED,
                    tenant_id=self.tenant_id,
                    resource_type="lead",
                    resource_id=lead_id,
                    actor_id=self.user_id,
                    payload={"source": lead.source, "dedupe_key": key},
                )
            )
        return await self.get(lead_id)

    async def update(
        self, lead_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class LeadRepository(TenantRepository[Lead]):
            model = Lead

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = LeadRepository(uow.session, self.tenant_id)
            lead = await repo.get_scoped_or_404(lead_id, self.permissions_scope())
            if changes.get("status"):
                assert_transition(
                    lead.status, changes["status"], reason=changes.get("disqualify_reason")
                )
            for field_name, value in changes.items():
                if value is not None:
                    setattr(lead, field_name, value)
            await repo.bump_version(lead, expected_version)
            lead.updated_by = self.user_id
            uow.collect(
                DomainEvent(
                    event_type=LEAD_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="lead",
                    resource_id=lead_id,
                    actor_id=self.user_id,
                    payload={"changed": sorted(changes)},
                )
            )
        return await self.get(lead_id)

    async def duplicates(self, lead_id: UUID) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from infrastructure.database.models.leads import Lead
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            current = (
                await session.execute(select(Lead).where(Lead.id == lead_id))
            ).scalar_one_or_none()
            if current is None:
                raise NotFound("Lead not found.")
            others = (
                (
                    await session.execute(
                        select(Lead).where(Lead.id != lead_id, Lead.deleted_at.is_(None)).limit(500)
                    )
                )
                .scalars()
                .all()
            )
        candidates = find_duplicates(
            {
                "email": current.email,
                "phone": current.phone,
                "first_name": current.first_name,
                "last_name": current.last_name,
                "source": current.source,
            },
            [
                {
                    "id": o.id,
                    "email": o.email,
                    "phone": o.phone,
                    "first_name": o.first_name,
                    "last_name": o.last_name,
                    "source": o.source,
                }
                for o in others
            ],
        )
        return [
            {"lead_id": c.lead_id, "match_reason": c.match_reason, "confidence": c.confidence}
            for c in candidates
        ]

    async def qualify(
        self,
        lead_id: UUID,
        *,
        mode: str = "rule",
        manual_score: int | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        lead = await self.get(lead_id)
        criteria = [Criterion(**c) for c in qualification_criteria(self.industry_code)]

        if mode == "manual":
            if manual_score is None:
                raise ValueError("a manual qualification requires a score")
            result = apply_human_decision(
                score_from_rubric(criteria, lead.get("capture", {})),
                decision="edited",
                edited_score=manual_score,
                note=notes,
            )
        elif mode == "ai":
            result = await self._qualify_with_ai(lead, criteria)
        else:
            result = score_from_rubric(criteria, lead.get("capture", {}))

        await self._persist_qualification(lead_id, result)
        return {"lead_id": str(lead_id), "qualification": result.to_dict()}

    async def _qualify_with_ai(
        self, lead: dict[str, Any], criteria: list[Criterion]
    ) -> QualificationResult:
        """A provider or guard failure never blocks core CRM operation."""
        from application.ai.registry import get_gateway
        from infrastructure.ai.gateway import AIRequest
        from infrastructure.ai.models import Task

        gateway = get_gateway()
        response = await gateway.complete(
            AIRequest(
                task=Task.QUALIFY_LEAD,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                industry_code=self.industry_code,
                messages=[{"role": "user", "content": str(lead.get("capture", {}))}],
                response_schema={
                    "type": "object",
                    "required": ["score", "reasons"],
                    "properties": {
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "reasons": {"type": "array"},
                    },
                },
            )
        )
        if not response.ok or response.structured is None:
            fallback = score_from_rubric(criteria, lead.get("capture", {}))
            degraded = degraded_result(response.degraded_reason or "ai unavailable")
            return QualificationResult(
                score=fallback.score,
                category=fallback.category,
                evidence=fallback.evidence,
                reasons=[*fallback.reasons, *degraded.reasons],
                missing_fields=fallback.missing_fields,
                qualified_by="rule",
                degraded=True,
                provenance={"method": "rule_fallback", "ai_reason": response.degraded_reason},
            )
        from domain.leads.qualification import categorize

        score = int(response.structured["score"])
        return QualificationResult(
            score=score,
            category=categorize(score),
            reasons=[str(r) for r in response.structured.get("reasons", [])],
            qualified_by="ai",
            provenance=response.to_metadata(),
        )

    async def _persist_qualification(self, lead_id: UUID, result: QualificationResult) -> None:
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.timeutil import utcnow

        class LeadRepository(TenantRepository[Lead]):
            model = Lead

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = LeadRepository(uow.session, self.tenant_id)
            lead = await repo.get_scoped_or_404(lead_id, self.permissions_scope())
            lead.qualification_score = result.score
            lead.category = result.category.value
            lead.reasoning = result.to_dict()
            lead.qualified_by = result.qualified_by
            lead.qualified_at = utcnow()
            lead.reviewer_state = result.review_state.value
            await repo.bump_version(lead, None)
            uow.collect(
                DomainEvent(
                    event_type=LEAD_QUALIFIED,
                    tenant_id=self.tenant_id,
                    resource_type="lead",
                    resource_id=lead_id,
                    actor_id=self.user_id,
                    payload={
                        "score": result.score,
                        "category": result.category.value,
                        "degraded": result.degraded,
                    },
                )
            )

    async def review_qualification(
        self, lead_id: UUID, *, decision: str, edited_score: int | None, note: str | None
    ) -> dict[str, Any]:
        lead = await self.get(lead_id)
        base = score_from_rubric(
            [Criterion(**c) for c in qualification_criteria(self.industry_code)],
            lead.get("capture", {}),
        )
        result = apply_human_decision(base, decision=decision, edited_score=edited_score, note=note)
        await self._persist_qualification(lead_id, result)
        return {"lead_id": str(lead_id), "qualification": result.to_dict()}

    async def convert(self, lead_id: UUID) -> dict[str, Any]:
        from domain.events.catalog import LEAD_CONVERTED
        from infrastructure.database.models.crm import Contact
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.timeutil import utcnow

        class LeadRepository(TenantRepository[Lead]):
            model = Lead

        contact_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = LeadRepository(uow.session, self.tenant_id)
            lead = await repo.get_scoped_or_404(lead_id, self.permissions_scope())
            assert_transition(lead.status, "converted")
            uow.session.add(
                Contact(
                    id=contact_id,
                    tenant_id=self.tenant_id,
                    first_name=lead.first_name,
                    last_name=lead.last_name,
                    email=lead.email,
                    phone=lead.phone,
                    source=lead.source,
                    custom_fields=dict(lead.capture or {}),
                    assignee_id=lead.assignee_id,
                    branch_id=lead.branch_id,
                    created_by=self.user_id,
                    version=1,
                )
            )
            lead.status = "converted"
            lead.converted_contact_id = contact_id
            lead.converted_at = utcnow()
            await repo.bump_version(lead, None)
            uow.collect(
                DomainEvent(
                    event_type=LEAD_CONVERTED,
                    tenant_id=self.tenant_id,
                    resource_type="lead",
                    resource_id=lead_id,
                    actor_id=self.user_id,
                    payload={"contact_id": str(contact_id)},
                )
            )
        return {"lead_id": str(lead_id), "contact_id": str(contact_id), "status": "converted"}


def _json_safe(value: Any) -> Any:
    """Coerce a payload into JSONB-storable primitives.

    Pydantic hands the service real `UUID` and `datetime` objects; asyncpg's JSONB
    codec cannot encode them, which previously raised on any lead captured with an
    assignee or branch.
    """
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _serialize(lead: Any) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "email": lead.email,
        "phone": lead.phone,
        "source": lead.source,
        "status": lead.status,
        "qualification_score": lead.qualification_score,
        "category": lead.category,
        "reviewer_state": lead.reviewer_state,
        "capture": lead.capture,
        "assignee_id": str(lead.assignee_id) if lead.assignee_id else None,
        "version": lead.version,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }
