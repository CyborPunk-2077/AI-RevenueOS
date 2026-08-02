"""Files and documents attached to CRM records.

**Object storage is not configured, and this module does not pretend otherwise.**
There is no AWS account (P0-5), so `request_upload` validates the metadata, records
the file with `scan_status = 'pending'`, and returns `storage_ready: false` with the
exact missing configuration. It does not mint a presigned URL, because a URL that
leads nowhere is worse than an honest refusal: the browser would report a successful
upload and the operator would believe a document exists.

Downloads are refused for the same reason, by the existing `assert_download_allowed`
-- a file is unavailable until a scanner marks it clean, and nothing can mark it
clean while neither storage nor ClamAV exists. That is correct fail-closed behaviour
and needs no special casing here.

What *is* real: the validation (size, MIME allow-list, dangerous and double
extensions, per-user daily allowance), the metadata record, the CRM linkage, the
tenant and role scoping, the audit trail and the outbox event. When AWS is
activated, `S3Storage.is_configured()` starts returning true and this same code path
issues a real presigned POST -- the API contract does not change, which is the whole
point of gating rather than stubbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.base import DomainEvent
from domain.events.catalog import (
    DOCUMENT_CREATED,
    DOCUMENT_DELETED,
    DOCUMENT_UPDATED,
    FILE_DELETED,
    FILE_UPLOAD_REQUESTED,
)
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound, ValidationError
from shared.pagination import Page
from shared.settings import get_settings
from shared.utils.ids import uuid7

logger = get_logger("application.crm.documents")

ENTITY_TYPES = ("contact", "account", "deal")
DOCUMENT_STATUSES = ("draft", "generated", "sent", "viewed", "signed", "expired", "void")
CLASSIFICATIONS = ("P0", "P1", "P2", "P3")


def build_storage() -> Any:
    """Built from settings on each call so activating AWS needs no logic change."""
    from infrastructure.integrations.storage import S3Storage

    settings = get_settings()
    return S3Storage(
        bucket=settings.s3_bucket_uploads,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
    )


def object_key_for(tenant_id: UUID, file_id: UUID, filename: str) -> str:
    """Tenant-prefixed and opaque.

    The tenant prefix lets a bucket policy enforce isolation at the storage layer
    too, and the user's filename is never reflected into the key -- a key is not a
    place to put attacker-controlled text.
    """
    suffix = ""
    if "." in filename:
        raw = filename.rsplit(".", 1)[-1].lower()
        if raw.isalnum() and len(raw) <= 8:
            suffix = f".{raw}"
    return f"tenants/{tenant_id}/uploads/{file_id}{suffix}"


def serialize_file(row: Any, *, owner_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "size_bytes": row.size_bytes,
        "mime_type": row.mime_type,
        "scan_status": row.scan_status,
        # Only a clean file is fetchable. Nothing can be scanned clean today, so
        # this is false everywhere -- deliberately, not as an oversight.
        "downloadable": row.scan_status == "clean",
        # This slice records an upload intent only. A planned object key and a
        # pending scan must never be presented as bytes that exist.
        "storage_state": "not_stored" if row.sha256 is None else "stored",
        "classification": row.classification,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id) if row.entity_id else None,
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "owner_name": owner_name,
        "object_key": row.object_key,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_document(row: Any, *, file_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "status": row.status,
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "deal_id": str(row.deal_id) if row.deal_id else None,
        "file_id": str(row.file_id) if row.file_id else None,
        "file_name": file_name,
        # Null until a file genuinely lands in object storage. Never invented.
        "s3_key": row.s3_key,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "viewed_at": row.viewed_at.isoformat() if row.viewed_at else None,
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@dataclass(slots=True)
class DocumentService(_PrincipalScoped):
    """File metadata and the documents that reference it."""

    # --- shared helpers -----------------------------------------------------

    async def _assert_parent_visible(self, entity_type: str | None, entity_id: UUID | None) -> None:
        """A parent outside the caller's scope must 404 exactly like a fake id."""
        if entity_type is None and entity_id is None:
            return
        if entity_type is None or entity_id is None:
            raise ValidationError("An entity type and entity id must be supplied together.")
        if entity_type not in ENTITY_TYPES:
            raise ValidationError(
                f"Unsupported entity type. Expected one of: {', '.join(ENTITY_TYPES)}."
            )

        from application.crm.deals import DealService
        from application.crm.service import AccountService, ContactService

        factory: Any = {
            "contact": ContactService,
            "account": AccountService,
            "deal": DealService,
        }[entity_type]
        service = factory(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        )
        # Raises NotFound for another tenant's record, another scope's record, and
        # an id that never existed -- the three cases must be indistinguishable.
        await service.get(entity_id)

    async def _owner_names(self, session: Any, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.users import User

        rows = await session.execute(
            select(User.id, User.full_name).where(
                User.id.in_(ids), User.tenant_id == self.tenant_id
            )
        )
        return {row[0]: row[1] for row in rows}

    async def _file_names(self, session: Any, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.documents import FileObject

        rows = await session.execute(
            select(FileObject.id, FileObject.name).where(
                FileObject.id.in_(ids), FileObject.tenant_id == self.tenant_id
            )
        )
        return {row[0]: row[1] for row in rows}

    async def _daily_bytes(self, session: Any) -> int:
        """What this user has already claimed today, for the daily allowance check."""
        from datetime import timedelta

        from sqlalchemy import func, select

        from infrastructure.database.models.documents import FileObject
        from shared.utils.timeutil import utcnow

        total = (
            await session.execute(
                select(func.coalesce(func.sum(FileObject.size_bytes), 0)).where(
                    FileObject.tenant_id == self.tenant_id,
                    FileObject.owner_id == self.user_id,
                    FileObject.created_at >= utcnow() - timedelta(days=1),
                    FileObject.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        return int(total or 0)

    # --- files --------------------------------------------------------------

    def storage_status(self) -> dict[str, Any]:
        """Reported honestly, naming the exact missing configuration."""
        settings = get_settings()
        adapter = dict(build_storage().activation_status())
        issues = settings.storage_configuration_issues()
        missing = list(adapter["missing"])
        missing.extend(issue for issue in issues if issue not in missing)
        if not settings.features.storage_enabled:
            missing.insert(0, "FEATURE_STORAGE_ENABLED=true (only after the activation runbook)")
        available = bool(settings.features.storage_enabled and adapter["configured"] and not issues)
        return {
            "provider": "s3",
            # Existing clients key their disabled control from `configured`.
            # It means usable, not merely that strings exist in the environment.
            "configured": available,
            "configuration_complete": bool(adapter["configured"] and not issues),
            "enabled": settings.features.storage_enabled,
            "missing": missing,
            "blocker": (
                None
                if available
                else "Object storage is disabled pending AWS, bucket-policy and malware-scanner "
                "activation. Metadata is recorded, but no upload URL is issued and no bytes "
                "are claimed as stored."
            ),
        }

    async def request_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate, record the metadata, and say plainly whether storage exists.

        Validation runs first and runs always. Rejecting an executable or an
        oversized file must not depend on whether a bucket happens to be
        configured, otherwise activating AWS would suddenly start accepting things
        that were previously refused for the wrong reason.
        """
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.documents import FileObject
        from infrastructure.database.session import tenant_session
        from infrastructure.integrations.storage import (
            PROTECTED_UPLOAD_LIMIT,
            validate_upload_request,
        )
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValidationError("A file name is required.")
        size_bytes = int(payload.get("size_bytes") or 0)
        declared_mime = str(payload.get("mime_type") or "application/octet-stream")
        classification = str(payload.get("classification") or "P2")
        if classification not in CLASSIFICATIONS:
            raise ValidationError(
                f"Unknown classification. Expected one of: {', '.join(CLASSIFICATIONS)}."
            )

        entity_type = payload.get("entity_type")
        entity_id = payload.get("entity_id")
        await self._assert_parent_visible(entity_type, entity_id)

        async with tenant_session(self.tenant_id) as session:
            already_today = await self._daily_bytes(session)

        verdict = validate_upload_request(
            declared_mime=declared_mime,
            size_bytes=size_bytes,
            filename=name,
            user_daily_bytes=already_today,
        )
        if not verdict.ok:
            raise ValidationError(
                verdict.reason or "This file cannot be uploaded.",
                details=dict(verdict.detail or {}),
            )

        storage = build_storage()
        activation = self.storage_status()
        configured = bool(activation["configured"])

        file_id = uuid7()
        key = object_key_for(self.tenant_id, file_id, name)
        settings = get_settings()

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                FileObject(
                    id=file_id,
                    tenant_id=self.tenant_id,
                    owner_id=self.user_id,
                    object_key=key,
                    bucket=settings.s3_bucket_uploads,
                    name=name[:300],
                    size_bytes=size_bytes,
                    mime_type=declared_mime,
                    declared_mime=declared_mime,
                    # Nothing has been scanned because nothing has been stored.
                    # `assert_download_allowed` refuses anything but `clean`.
                    scan_status="pending",
                    scan_detail={},
                    classification=classification,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    # A content digest can only be computed from content. There are
                    # no bytes while storage is disabled, so this must stay null.
                    sha256=None,
                )
            )
            AuditRecorder(uow.session).record(
                action="file.upload_requested",
                resource_type="file",
                resource_id=file_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={
                    "name": name,
                    "size_bytes": size_bytes,
                    "mime_type": declared_mime,
                    "stored": False,
                },
            )
            uow.collect(
                DomainEvent(
                    event_type=FILE_UPLOAD_REQUESTED,
                    tenant_id=self.tenant_id,
                    resource_type="file",
                    resource_id=file_id,
                    actor_id=self.user_id,
                    payload={
                        "name": name,
                        "size_bytes": size_bytes,
                        "mime_type": declared_mime,
                        "stored": False,
                    },
                )
            )

        record = await self.get_file(file_id)
        response: dict[str, Any] = {
            **record,
            "storage_ready": configured,
            "blocker": activation["blocker"],
            "missing_configuration": list(activation["missing"]),
        }

        if configured:
            presigned = await storage.presign_upload(
                tenant_id=self.tenant_id,
                key=key,
                content_type=declared_mime,
                max_bytes=PROTECTED_UPLOAD_LIMIT,
            )
            response["upload"] = {
                "url": presigned.url,
                "fields": dict(presigned.fields),
                "expires_at": presigned.expires_at.isoformat(),
                "max_bytes": presigned.max_bytes,
            }
        # When storage is absent there is no `upload` key at all. An empty string
        # or a null URL is something a client could still try to POST to.

        logger.info("file_upload_requested", file_id=str(file_id), storage_configured=configured)
        return response

    async def list_files(
        self,
        query: Any,
        *,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
    ) -> Page:
        from infrastructure.database.models.documents import FileObject
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class FileRepository(TenantRepository[FileObject]):
            model = FileObject

        if entity_type or entity_id:
            await self._assert_parent_visible(entity_type, entity_id)

        async with tenant_session(self.tenant_id) as session:
            repo = FileRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if entity_type and entity_id:
                stmt = stmt.where(
                    FileObject.entity_type == entity_type,
                    FileObject.entity_id == entity_id,
                )

            page = await repo.paginate_cursor(stmt, cursor=query.cursor, page_size=query.page_size)
            names = await self._owner_names(session, {f.owner_id for f in page.items if f.owner_id})
            page.items = [
                serialize_file(f, owner_name=names.get(f.owner_id) if f.owner_id else None)
                for f in page.items
            ]
            return page

    async def get_file(self, file_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.documents import FileObject
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class FileRepository(TenantRepository[FileObject]):
            model = FileObject

        async with tenant_session(self.tenant_id) as session:
            row = await FileRepository(session, self.tenant_id).get_scoped(
                file_id, self.permissions_scope()
            )
            if row is None:
                raise NotFound("File not found.")
            names = await self._owner_names(session, {row.owner_id} if row.owner_id else set())
            return serialize_file(row, owner_name=names.get(row.owner_id) if row.owner_id else None)

    async def download_url(self, file_id: UUID) -> dict[str, Any]:
        """Refused until the file is stored and scanned clean. No fake URL, ever.

        `assert_download_allowed` is the existing tested guard: cross-tenant is a
        403, anything not `clean` is a 422 carrying the real scan status.
        """
        from infrastructure.integrations.storage import assert_download_allowed

        record = await self.get_file(file_id)
        assert_download_allowed(
            scan_status=str(record["scan_status"]),
            file_tenant_id=self.tenant_id,
            requester_tenant_id=self.tenant_id,
        )
        # Unreachable until a scanner exists. Kept so activation needs no new code.
        storage = build_storage()
        url = await storage.presign_download(
            bucket=get_settings().s3_bucket_uploads, key=str(record["object_key"])
        )
        return {"url": url, "expires_in_seconds": 300}

    async def delete_file(self, file_id: UUID) -> dict[str, Any]:
        """Soft delete, so the audit trail can still resolve what was removed."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.documents import FileObject
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.timeutil import utcnow

        class FileRepository(TenantRepository[FileObject]):
            model = FileObject

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = FileRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped(file_id, self.permissions_scope())
            if row is None:
                raise NotFound("File not found.")
            row.deleted_at = utcnow()

            AuditRecorder(uow.session).record(
                action="file.delete",
                resource_type="file",
                resource_id=file_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values={"name": row.name, "object_key": row.object_key},
            )
            uow.collect(
                DomainEvent(
                    event_type=FILE_DELETED,
                    tenant_id=self.tenant_id,
                    resource_type="file",
                    resource_id=file_id,
                    actor_id=self.user_id,
                    payload={"name": row.name, "stored": row.sha256 is not None},
                )
            )
        logger.info("file_deleted", file_id=str(file_id))
        return {"deleted": True, "id": str(file_id)}

    # --- documents ----------------------------------------------------------

    async def list_documents(
        self,
        query: Any,
        *,
        status: str | None = None,
        contact_id: UUID | None = None,
        deal_id: UUID | None = None,
    ) -> Page:
        from infrastructure.database.models.documents import Document
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class DocumentRepository(TenantRepository[Document]):
            model = Document

        if status and status not in DOCUMENT_STATUSES:
            raise ValidationError(f"Unknown status: {status!r}.")
        if contact_id is not None:
            await self._assert_parent_visible("contact", contact_id)
        if deal_id is not None:
            await self._assert_parent_visible("deal", deal_id)

        async with tenant_session(self.tenant_id) as session:
            repo = DocumentRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if status:
                stmt = stmt.where(Document.status == status)
            if contact_id is not None:
                stmt = stmt.where(Document.contact_id == contact_id)
            if deal_id is not None:
                stmt = stmt.where(Document.deal_id == deal_id)

            page = await repo.paginate_cursor(stmt, cursor=query.cursor, page_size=query.page_size)
            names = await self._file_names(session, {d.file_id for d in page.items if d.file_id})
            page.items = [
                serialize_document(d, file_name=names.get(d.file_id) if d.file_id else None)
                for d in page.items
            ]
            return page

    async def get_document(self, document_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.documents import Document
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class DocumentRepository(TenantRepository[Document]):
            model = Document

        async with tenant_session(self.tenant_id) as session:
            row = await DocumentRepository(session, self.tenant_id).get_scoped(
                document_id, self.permissions_scope()
            )
            if row is None:
                raise NotFound("Document not found.")
            names = await self._file_names(session, {row.file_id} if row.file_id else set())
            return serialize_document(
                row, file_name=names.get(row.file_id) if row.file_id else None
            )

    async def create_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach a document to a contact and/or a deal."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.documents import Document
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValidationError("A title is required.")
        if not payload.get("contact_id") and not payload.get("deal_id"):
            raise ValidationError("A document must be attached to a contact or a deal.")

        if payload.get("contact_id"):
            await self._assert_parent_visible("contact", payload["contact_id"])
        if payload.get("deal_id"):
            await self._assert_parent_visible("deal", payload["deal_id"])
        if payload.get("file_id"):
            # 404s if the file belongs to another tenant or another scope.
            await self.get_file(payload["file_id"])

        document_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                Document(
                    id=document_id,
                    tenant_id=self.tenant_id,
                    title=title[:300],
                    status="draft",
                    contact_id=payload.get("contact_id"),
                    deal_id=payload.get("deal_id"),
                    file_id=payload.get("file_id"),
                    # Set only when a file genuinely lands in object storage.
                    s3_key=None,
                    content_metadata={},
                    created_by=self.user_id,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="document.create",
                resource_type="document",
                resource_id=document_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"title": title, "status": "draft"},
            )
            uow.collect(
                DomainEvent(
                    event_type=DOCUMENT_CREATED,
                    tenant_id=self.tenant_id,
                    resource_type="document",
                    resource_id=document_id,
                    actor_id=self.user_id,
                    payload={
                        "title": title,
                        "file_id": (str(payload["file_id"]) if payload.get("file_id") else None),
                        "stored": False,
                    },
                )
            )
        logger.info("document_created", document_id=str(document_id))
        return await self.get_document(document_id)

    async def update_document(
        self,
        document_id: UUID,
        changes: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder, diff_for_audit
        from infrastructure.database.models.documents import Document
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.timeutil import utcnow

        class DocumentRepository(TenantRepository[Document]):
            model = Document

        new_status = changes.get("status")
        if new_status is not None and new_status not in DOCUMENT_STATUSES:
            raise ValidationError(
                f"Unknown status. Expected one of: {', '.join(DOCUMENT_STATUSES)}."
            )
        if changes.get("file_id"):
            await self.get_file(changes["file_id"])

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = DocumentRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped_or_404(document_id, self.permissions_scope())
            before = serialize_document(row)

            if changes.get("title") is not None:
                row.title = str(changes["title"]).strip()[:300]
            if "file_id" in changes:
                row.file_id = changes["file_id"]
            if new_status is not None and new_status != row.status:
                row.status = new_status
                # Stamped from the server clock when the status genuinely changes,
                # never accepted from the client.
                if new_status == "sent" and row.sent_at is None:
                    row.sent_at = utcnow()
                elif new_status == "viewed" and row.viewed_at is None:
                    row.viewed_at = utcnow()
                elif new_status == "signed" and row.signed_at is None:
                    row.signed_at = utcnow()
                elif new_status == "void" and row.voided_at is None:
                    row.voided_at = utcnow()

            await repo.bump_version(row, expected_version)
            row.updated_by = self.user_id
            after = serialize_document(row)

            old_values, new_values = diff_for_audit(before, after)
            AuditRecorder(uow.session).record(
                action="document.update",
                resource_type="document",
                resource_id=document_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values=old_values,
                new_values=new_values,
            )
            uow.collect(
                DomainEvent(
                    event_type=DOCUMENT_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="document",
                    resource_id=document_id,
                    actor_id=self.user_id,
                    payload={"changed": sorted(new_values)},
                )
            )
        return await self.get_document(document_id)

    async def delete_document(self, document_id: UUID) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.documents import Document
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.timeutil import utcnow

        class DocumentRepository(TenantRepository[Document]):
            model = Document

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = DocumentRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped(document_id, self.permissions_scope())
            if row is None:
                raise NotFound("Document not found.")
            row.deleted_at = utcnow()
            AuditRecorder(uow.session).record(
                action="document.delete",
                resource_type="document",
                resource_id=document_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values={"title": row.title, "status": row.status},
            )
            uow.collect(
                DomainEvent(
                    event_type=DOCUMENT_DELETED,
                    tenant_id=self.tenant_id,
                    resource_type="document",
                    resource_id=document_id,
                    actor_id=self.user_id,
                    payload={"title": row.title},
                )
            )
        logger.info("document_deleted", document_id=str(document_id))
        return {"deleted": True, "id": str(document_id)}
