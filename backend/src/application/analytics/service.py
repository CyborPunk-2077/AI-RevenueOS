"""Tenant-safe analytics, durable rollups, and honest export intents.

Dashboard reads are calculated from the caller's scoped CRM rows.  Daily rollups
are tenant-wide materializations for scheduled/admin reporting; they are never
used to widen a self-, team-, or branch-scoped principal's view.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.auth.permissions import Scope
from domain.base import DomainEvent
from domain.events.catalog import ANALYTICS_EXPORT_REQUESTED
from shared.exceptions import NotFound, ProviderUnavailable, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import local_day_bounds

MAX_REPORT_DAYS = 366


def _validate_range(start_day: date, end_day: date) -> None:
    if end_day < start_day:
        raise ValidationError("The end date must be on or after the start date.")
    if (end_day - start_day).days >= MAX_REPORT_DAYS:
        raise ValidationError(f"A report may cover at most {MAX_REPORT_DAYS} days.")


def _zero_days(start_day: date, end_day: date) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    cursor = start_day
    while cursor <= end_day:
        result[cursor.isoformat()] = {"leads": 0, "won_amount_minor": 0}
        cursor += timedelta(days=1)
    return result


@dataclass(slots=True)
class AnalyticsService(_PrincipalScoped):
    """Read metrics only from rows visible to the authenticated principal."""

    async def dashboard(
        self, start_day: date, end_day: date, *, timezone: str = "Asia/Kolkata"
    ) -> dict[str, Any]:
        _validate_range(start_day, end_day)
        start_at, _ = local_day_bounds(start_day, timezone)
        _, end_at = local_day_bounds(end_day, timezone)

        from sqlalchemy import case, false, func, select

        from infrastructure.database.models.appointments import Appointment
        from infrastructure.database.models.communications import Conversation, Message
        from infrastructure.database.models.crm import Deal, SlaRecord
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.models.payments import Payment, Refund
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class LeadRepo(TenantRepository[Lead]):
            model = Lead

        class DealRepo(TenantRepository[Deal]):
            model = Deal

        class ConversationRepo(TenantRepository[Conversation]):
            model = Conversation

        class SlaRepo(TenantRepository[SlaRecord]):
            model = SlaRecord

        perms = self.permissions_scope()
        async with tenant_session(self.tenant_id) as session:
            lead_scope = LeadRepo(session, self.tenant_id).scoped_query(perms).subquery()
            lead_row = (
                await session.execute(
                    select(
                        func.count().label("created"),
                        func.count().filter(lead_scope.c.status == "qualified").label("qualified"),
                        func.count().filter(lead_scope.c.status == "converted").label("converted"),
                        func.count().filter(lead_scope.c.category == "hot").label("hot"),
                        func.count().filter(lead_scope.c.category == "warm").label("warm"),
                        func.count().filter(lead_scope.c.category == "cold").label("cold"),
                        func.avg(
                            func.extract(
                                "epoch", lead_scope.c.first_response_at - lead_scope.c.created_at
                            )
                        )
                        .filter(lead_scope.c.first_response_at.is_not(None))
                        .label("avg_response"),
                    ).where(
                        lead_scope.c.created_at >= start_at,
                        lead_scope.c.created_at < end_at,
                    )
                )
            ).one()

            source_rows = await session.execute(
                select(lead_scope.c.source, func.count())
                .where(lead_scope.c.created_at >= start_at, lead_scope.c.created_at < end_at)
                .group_by(lead_scope.c.source)
                .order_by(func.count().desc(), lead_scope.c.source.asc())
                .limit(20)
            )

            deal_scope = DealRepo(session, self.tenant_id).scoped_query(perms).subquery()

            # Open value per stage, in board order. `is_lost` stages are excluded:
            # a lost column carries no pipeline, and including it would make the
            # total on this chart disagree with `pipeline_amount_minor` below.
            from infrastructure.database.models.crm import Stage

            stage_rows = (
                await session.execute(
                    select(
                        Stage.name,
                        Stage.position,
                        func.coalesce(func.sum(deal_scope.c.amount_minor), 0),
                        func.count(deal_scope.c.id),
                    )
                    .select_from(Stage)
                    .join(deal_scope, deal_scope.c.stage_id == Stage.id, isouter=True)
                    .where(
                        Stage.tenant_id == self.tenant_id,
                        Stage.is_lost.is_(False),
                    )
                    .group_by(Stage.name, Stage.position)
                    .order_by(Stage.position)
                )
            ).all()
            deal_row = (
                await session.execute(
                    select(
                        func.count().filter(deal_scope.c.status == "won").label("won"),
                        func.count().filter(deal_scope.c.status == "lost").label("lost"),
                        func.coalesce(
                            func.sum(deal_scope.c.amount_minor).filter(
                                deal_scope.c.status == "won"
                            ),
                            0,
                        ).label("won_amount"),
                        func.coalesce(
                            func.sum(deal_scope.c.amount_minor).filter(
                                deal_scope.c.status == "open"
                            ),
                            0,
                        ).label("pipeline"),
                    ).where(
                        case(
                            (deal_scope.c.status.in_(("won", "lost")), deal_scope.c.closed_at),
                            else_=deal_scope.c.created_at,
                        )
                        >= start_at,
                        case(
                            (deal_scope.c.status.in_(("won", "lost")), deal_scope.c.closed_at),
                            else_=deal_scope.c.created_at,
                        )
                        < end_at,
                    )
                )
            ).one()
            performance_rows = await session.execute(
                select(
                    deal_scope.c.assignee_id,
                    func.count().filter(deal_scope.c.status == "won"),
                    func.coalesce(
                        func.sum(deal_scope.c.amount_minor).filter(deal_scope.c.status == "won"),
                        0,
                    ),
                    func.count().filter(deal_scope.c.status == "open"),
                )
                .where(
                    case(
                        (
                            deal_scope.c.status.in_(("won", "lost")),
                            deal_scope.c.closed_at,
                        ),
                        else_=deal_scope.c.created_at,
                    )
                    >= start_at,
                    case(
                        (
                            deal_scope.c.status.in_(("won", "lost")),
                            deal_scope.c.closed_at,
                        ),
                        else_=deal_scope.c.created_at,
                    )
                    < end_at,
                )
                .group_by(deal_scope.c.assignee_id)
                .order_by(
                    func.coalesce(
                        func.sum(deal_scope.c.amount_minor).filter(deal_scope.c.status == "won"),
                        0,
                    ).desc()
                )
                .limit(20)
            )

            sla_scope = SlaRepo(session, self.tenant_id).scoped_query(perms).subquery()
            sla_row = (
                await session.execute(
                    select(
                        func.count(),
                        func.count().filter(sla_scope.c.resolved_at.is_not(None)),
                        func.count().filter(sla_scope.c.breached_at.is_not(None)),
                    ).where(
                        sla_scope.c.started_at >= start_at,
                        sla_scope.c.started_at < end_at,
                    )
                )
            ).one()

            appointment_stmt = select(Appointment).where(
                Appointment.tenant_id == self.tenant_id,
                Appointment.deleted_at.is_(None),
                Appointment.start_at >= start_at,
                Appointment.start_at < end_at,
            )
            if self.scope is Scope.SELF:
                appointment_stmt = appointment_stmt.where(Appointment.organizer_id == self.user_id)
            elif self.scope is Scope.BRANCH:
                ids = [UUID(item) for item in self.branch_ids]
                appointment_stmt = appointment_stmt.where(Appointment.branch_id.in_(ids))
            elif self.scope is not Scope.GLOBAL:
                # Appointments do not carry team ownership. A team-scoped caller
                # therefore gets no aggregate rather than a tenant-wide one.
                appointment_stmt = appointment_stmt.where(false())
            appointment_scope = appointment_stmt.subquery()
            appointment_row = (
                await session.execute(
                    select(
                        func.count(),
                        func.count().filter(appointment_scope.c.status == "completed"),
                        func.count().filter(appointment_scope.c.status == "no_show"),
                    )
                )
            ).one()

            conversation_scope = ConversationRepo(session, self.tenant_id).scoped_query(perms)
            conversation_ids = conversation_scope.with_only_columns(Conversation.id).subquery()
            message_row = (
                await session.execute(
                    select(
                        func.count().filter(Message.direction == "inbound"),
                        func.count().filter(Message.direction == "outbound"),
                        func.count().filter(Message.status == "failed"),
                    ).where(
                        Message.tenant_id == self.tenant_id,
                        Message.conversation_id.in_(select(conversation_ids.c.id)),
                        Message.created_at >= start_at,
                        Message.created_at < end_at,
                    )
                )
            ).one()

            payment_filter = [
                Payment.tenant_id == self.tenant_id,
                Payment.created_at >= start_at,
                Payment.created_at < end_at,
            ]
            refund_filter = [
                Refund.tenant_id == self.tenant_id,
                Refund.created_at >= start_at,
                Refund.created_at < end_at,
            ]
            if self.scope is not Scope.GLOBAL:
                scoped_deal_ids = select(deal_scope.c.id)
                payment_filter.append(Payment.deal_id.in_(scoped_deal_ids))
                refund_filter.append(
                    Refund.payment_id.in_(
                        select(Payment.id).where(
                            *payment_filter[:1], Payment.deal_id.in_(scoped_deal_ids)
                        )
                    )
                )
            captured = int(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
                            *payment_filter, Payment.status.in_(("captured", "refunded"))
                        )
                    )
                ).scalar_one()
            )
            refunded = int(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                            *refund_filter
                        )
                    )
                ).scalar_one()
            )

            # Bucket from the tenant-local range origin. PostgreSQL installations
            # on Windows do not consistently ship IANA alias names (for example
            # Asia/Kolkata), so asking the database to resolve the zone would make
            # an otherwise valid tenant setting fail at runtime. India has no DST;
            # the API's Python zoneinfo calculation establishes the exact origin.
            day_expr = func.floor(func.extract("epoch", lead_scope.c.created_at - start_at) / 86400)
            lead_days = await session.execute(
                select(day_expr, func.count())
                .where(lead_scope.c.created_at >= start_at, lead_scope.c.created_at < end_at)
                .group_by(day_expr)
            )
            close_day = func.floor(func.extract("epoch", deal_scope.c.closed_at - start_at) / 86400)
            revenue_days = await session.execute(
                select(close_day, func.coalesce(func.sum(deal_scope.c.amount_minor), 0))
                .where(
                    deal_scope.c.status == "won",
                    deal_scope.c.closed_at >= start_at,
                    deal_scope.c.closed_at < end_at,
                )
                .group_by(close_day)
            )

        days = _zero_days(start_day, end_day)
        for index, count in lead_days:
            key = (start_day + timedelta(days=int(index))).isoformat()
            days[key]["leads"] = int(count)
        for index, amount in revenue_days:
            key = (start_day + timedelta(days=int(index))).isoformat()
            days[key]["won_amount_minor"] = int(amount)

        return {
            "period": {
                "start": start_day.isoformat(),
                "end": end_day.isoformat(),
                "timezone": timezone,
            },
            "leads": {
                "created": int(lead_row.created),
                "qualified": int(lead_row.qualified),
                "converted": int(lead_row.converted),
                "hot": int(lead_row.hot),
                "warm": int(lead_row.warm),
                "cold": int(lead_row.cold),
                "conversion_rate": round(int(lead_row.converted) / int(lead_row.created), 4)
                if int(lead_row.created)
                else 0.0,
                "avg_first_response_seconds": (
                    round(float(lead_row.avg_response), 1)
                    if lead_row.avg_response is not None
                    else None
                ),
            },
            "revenue": {
                "deals_won": int(deal_row.won),
                "deals_lost": int(deal_row.lost),
                "won_amount_minor": int(deal_row.won_amount),
                "pipeline_amount_minor": int(deal_row.pipeline),
                "payments_captured_minor": captured,
                "refunds_minor": refunded,
            },
            "appointments": {
                "scheduled": int(appointment_row[0]),
                "completed": int(appointment_row[1]),
                "no_show": int(appointment_row[2]),
            },
            "conversations": {
                "inbound": int(message_row[0]),
                "outbound": int(message_row[1]),
                "failed": int(message_row[2]),
            },
            "sla": {
                "tracked": int(sla_row[0]),
                "resolved": int(sla_row[1]),
                "breached": int(sla_row[2]),
                "breach_rate": round(int(sla_row[2]) / int(sla_row[0]), 4)
                if int(sla_row[0])
                else 0.0,
            },
            "team_performance": [
                {
                    "assignee_id": str(row[0]) if row[0] else None,
                    "deals_won": int(row[1]),
                    "won_amount_minor": int(row[2]),
                    "open_deals": int(row[3]),
                }
                for row in performance_rows
            ],
            "lead_sources": [
                {"source": source or "unknown", "count": int(count)}
                for source, count in source_rows
            ],
            "pipeline_by_stage": [
                {
                    "stage": name,
                    "position": int(position),
                    "amount_minor": int(amount),
                    "deal_count": int(count),
                }
                for name, position, amount, count in stage_rows
            ],
            "daily": [{"day": day, **values} for day, values in days.items()],
            "scope": self.scope.value,
        }

    async def request_export(
        self, start_day: date, end_day: date, *, storage_ready: bool
    ) -> dict[str, Any]:
        """Record a blocked export intent when private object storage is unavailable."""
        _validate_range(start_day, end_day)
        if storage_ready:
            raise ProviderUnavailable(
                "Analytics export transport is not activated.",
                details={"activation_prerequisite": "Complete the storage activation runbook."},
            )

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.operational import ExportJob
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        export_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                ExportJob(
                    id=export_id,
                    tenant_id=self.tenant_id,
                    export_type="analytics_csv",
                    filters={"start": start_day.isoformat(), "end": end_day.isoformat()},
                    status="blocked",
                    error="Private export storage is not configured.",
                    requested_by=self.user_id,
                )
            )
            AuditRecorder(uow.session).record(
                action="export.created",
                resource_type="export",
                resource_id=export_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"type": "analytics_csv", "status": "blocked"},
            )
            uow.collect(
                DomainEvent(
                    event_type=ANALYTICS_EXPORT_REQUESTED,
                    tenant_id=self.tenant_id,
                    resource_type="export",
                    resource_id=export_id,
                    actor_id=self.user_id,
                    payload={"status": "blocked"},
                )
            )
        return await self.get_export(export_id)

    async def get_export(self, export_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.operational import ExportJob
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ExportRepo(TenantRepository[ExportJob]):
            model = ExportJob
            soft_delete = False

        async with tenant_session(self.tenant_id) as session:
            row = await ExportRepo(session, self.tenant_id).get(export_id, self.permissions_scope())
            if row is None or row.requested_by != self.user_id:
                raise NotFound("Export not found.")
            return {
                "id": str(row.id),
                "type": row.export_type,
                "status": row.status,
                "filters": dict(row.filters or {}),
                "row_count": row.row_count,
                "error": row.error,
                "download_available": bool(row.s3_key and row.status == "completed"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }


@dataclass(slots=True)
class RollupService:
    """Idempotently materialize one tenant-local calendar day."""

    tenant_id: UUID

    async def refresh_day(self, day: date, *, timezone: str = "Asia/Kolkata") -> None:
        from sqlalchemy import delete, func, select
        from sqlalchemy.dialects.postgresql import insert

        from infrastructure.database.models.analytics import (
            DailyConversationRollup,
            DailyLeadRollup,
            DailyRevenueRollup,
        )
        from infrastructure.database.models.communications import (
            CommunicationPreference,
            Conversation,
            Message,
        )
        from infrastructure.database.models.crm import Deal
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.models.payments import Payment, Refund
        from infrastructure.database.session import tenant_session

        start_at, end_at = local_day_bounds(day, timezone)
        async with tenant_session(self.tenant_id) as session:
            # Delete then rebuild inside one transaction so sources/channels that
            # disappeared do not survive as stale rows from an earlier refresh.
            for model in (DailyLeadRollup, DailyRevenueRollup, DailyConversationRollup):
                await session.execute(
                    delete(model).where(model.tenant_id == self.tenant_id, model.day == day)
                )
            leads = await session.execute(
                select(
                    Lead.source,
                    func.count(),
                    func.count().filter(Lead.status == "qualified"),
                    func.count().filter(Lead.status == "contacted"),
                    func.count().filter(Lead.status == "converted"),
                    func.count().filter(Lead.status == "disqualified"),
                    func.count().filter(Lead.category == "hot"),
                    func.count().filter(Lead.category == "warm"),
                    func.count().filter(Lead.category == "cold"),
                    func.avg(
                        func.extract("epoch", Lead.first_response_at - Lead.created_at)
                    ).filter(Lead.first_response_at.is_not(None)),
                )
                .where(
                    Lead.deleted_at.is_(None), Lead.created_at >= start_at, Lead.created_at < end_at
                )
                .group_by(Lead.source)
            )
            for row in leads:
                values = {
                    "tenant_id": self.tenant_id,
                    "day": day,
                    "source": row[0] or "unknown",
                    "created_count": int(row[1]),
                    "qualified_count": int(row[2]),
                    "contacted_count": int(row[3]),
                    "converted_count": int(row[4]),
                    "disqualified_count": int(row[5]),
                    "hot_count": int(row[6]),
                    "warm_count": int(row[7]),
                    "cold_count": int(row[8]),
                    "avg_first_response_seconds": float(row[9]) if row[9] is not None else None,
                }
                stmt = insert(DailyLeadRollup).values(id=uuid7(), **values)
                await session.execute(
                    stmt.on_conflict_do_update(constraint="tenant_day_source", set_=values)
                )

            revenue = (
                await session.execute(
                    select(
                        func.count().filter(
                            Deal.status == "won",
                            Deal.closed_at >= start_at,
                            Deal.closed_at < end_at,
                        ),
                        func.count().filter(
                            Deal.status == "lost",
                            Deal.closed_at >= start_at,
                            Deal.closed_at < end_at,
                        ),
                        func.coalesce(
                            func.sum(Deal.amount_minor).filter(
                                Deal.status == "won",
                                Deal.closed_at >= start_at,
                                Deal.closed_at < end_at,
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(Deal.amount_minor).filter(Deal.status == "open"), 0),
                    ).where(Deal.deleted_at.is_(None))
                )
            ).one()
            captured = (
                await session.execute(
                    select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
                        Payment.captured_at >= start_at,
                        Payment.captured_at < end_at,
                        Payment.status.in_(("captured", "refunded")),
                    )
                )
            ).scalar_one()
            refunds = (
                await session.execute(
                    select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                        Refund.created_at >= start_at, Refund.created_at < end_at
                    )
                )
            ).scalar_one()
            rev_values = {
                "tenant_id": self.tenant_id,
                "day": day,
                "deals_won": int(revenue[0]),
                "deals_lost": int(revenue[1]),
                "won_amount_minor": int(revenue[2]),
                "pipeline_amount_minor": int(revenue[3]),
                "payments_captured_minor": int(captured),
                "refunds_minor": int(refunds),
            }
            rev_stmt = insert(DailyRevenueRollup).values(id=uuid7(), **rev_values)
            await session.execute(
                rev_stmt.on_conflict_do_update(constraint="tenant_day", set_=rev_values)
            )

            message_rows = list(
                await session.execute(
                    select(
                        Message.channel,
                        func.count().filter(Message.direction == "inbound"),
                        func.count().filter(Message.direction == "outbound"),
                        func.count().filter(Message.status == "delivered"),
                        func.count().filter(Message.status == "failed"),
                    )
                    .where(Message.created_at >= start_at, Message.created_at < end_at)
                    .group_by(Message.channel)
                )
            )
            handoff_rows = await session.execute(
                select(Conversation.primary_channel, func.count())
                .where(
                    Conversation.deleted_at.is_(None),
                    Conversation.handoff_at >= start_at,
                    Conversation.handoff_at < end_at,
                )
                .group_by(Conversation.primary_channel)
            )
            opt_out_rows = await session.execute(
                select(CommunicationPreference.channel, func.count())
                .where(
                    CommunicationPreference.opted_out.is_(True),
                    CommunicationPreference.opted_out_at >= start_at,
                    CommunicationPreference.opted_out_at < end_at,
                )
                .group_by(CommunicationPreference.channel)
            )
            handoffs = {row[0]: int(row[1]) for row in handoff_rows}
            opt_outs = {row[0]: int(row[1]) for row in opt_out_rows}
            messages = {row[0]: row for row in message_rows}
            for channel in sorted(set(messages) | set(handoffs) | set(opt_outs)):
                message_row = messages.get(channel)
                conv_values = {
                    "tenant_id": self.tenant_id,
                    "day": day,
                    "channel": channel,
                    "inbound_count": int(message_row[1]) if message_row else 0,
                    "outbound_count": int(message_row[2]) if message_row else 0,
                    "delivered_count": int(message_row[3]) if message_row else 0,
                    "failed_count": int(message_row[4]) if message_row else 0,
                    "handoff_count": handoffs.get(channel, 0),
                    "opt_out_count": opt_outs.get(channel, 0),
                }
                conv_stmt = insert(DailyConversationRollup).values(id=uuid7(), **conv_values)
                await session.execute(
                    conv_stmt.on_conflict_do_update(
                        constraint="tenant_day_channel", set_=conv_values
                    )
                )
