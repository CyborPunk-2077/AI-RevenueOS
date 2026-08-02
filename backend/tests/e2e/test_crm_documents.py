"""Files and documents over HTTP against real PostgreSQL with RLS forced.

The assertion that matters most here is the one about *absence*: with no AWS
account, the upload path must not return a URL, must not claim the file is stored,
and must not let anything be downloaded. A test suite that only checked the happy
path would pass just as well against a version that invented a presigned URL, which
is exactly the failure mode this module exists to prevent.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.e2e.test_crm_contacts_accounts import (  # noqa: F401
    ACME_EMAIL,
    GLOBEX_EMAIL,
    client,
    demo_data,
    fake_redis,
    make_account,
    make_contact,
    sign_in,
    wired_engine,
)
from tests.e2e.test_crm_deals import make_deal

pytestmark = pytest.mark.postgres


def register_file(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {
        "name": f"quote-{uuid4().hex[:6]}.pdf",
        "size_bytes": 24_000,
        "mime_type": "application/pdf",
        **overrides,
    }
    response = client.post("/v1/files", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def make_document(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {"title": f"Proposal {uuid4().hex[:6]}", **overrides}
    response = client.post("/v1/documents", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestStorageIsHonestlyUnavailable:
    """No AWS account exists. Nothing may behave as if one does."""

    def test_the_status_endpoint_reports_not_configured_with_the_reason(
        self, client: TestClient
    ) -> None:
        headers = sign_in(client, ACME_EMAIL)
        data = client.get("/v1/files/storage-status", headers=headers).json()["data"]

        assert data["configured"] is False
        assert data["blocker"]
        # Named precisely enough that an operator knows what to go and create.
        assert any("S3_BUCKET_UPLOADS" in item for item in data["missing"])

    def test_registering_a_file_returns_no_upload_url(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        record = register_file(client, headers, entity_type="contact", entity_id=contact["id"])

        assert record["storage_ready"] is False
        # The key is absent entirely -- not null, not empty. There is nothing a
        # client could mistake for somewhere to PUT bytes.
        assert "upload" not in record
        assert record["blocker"]
        assert record["scan_status"] == "pending"
        assert record["downloadable"] is False
        assert record["storage_state"] == "not_stored"

    def test_download_is_refused_while_the_file_is_unscanned(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        record = register_file(client, headers)

        response = client.get(f"/v1/files/{record['id']}/download", headers=headers)
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["details"]["scan_status"] == "pending"
        assert "url" not in body.get("data", {})

    def test_a_document_records_no_storage_key(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        document = make_document(client, headers, contact_id=contact["id"])
        # Never invented: an s3 key implies bytes at that key.
        assert document["s3_key"] is None


class TestFileValidation:
    def test_an_executable_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/files",
            headers=headers,
            json={"name": "payload.exe", "size_bytes": 1024, "mime_type": "application/pdf"},
        )
        assert response.status_code == 422

    def test_a_double_extension_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/files",
            headers=headers,
            json={"name": "invoice.exe.pdf", "size_bytes": 1024, "mime_type": "application/pdf"},
        )
        assert response.status_code == 422

    def test_a_disallowed_mime_type_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/files",
            headers=headers,
            json={"name": "thing.bin", "size_bytes": 1024, "mime_type": "application/x-msdownload"},
        )
        assert response.status_code == 422

    def test_an_oversized_file_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/files",
            headers=headers,
            json={
                "name": "huge.pdf",
                "size_bytes": 60 * 1024 * 1024,
                "mime_type": "application/pdf",
            },
        )
        assert response.status_code == 422

    def test_the_filename_is_never_reflected_into_the_object_key(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        record = register_file(client, headers, name="../../etc/passwd.pdf")
        assert "passwd" not in record["object_key"]
        assert ".." not in record["object_key"]
        # Tenant prefixed, so a bucket policy can enforce isolation too.
        assert record["object_key"].startswith("tenants/")


class TestAttachmentAndListing:
    def test_files_and_documents_are_listed_on_their_contact(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        record = register_file(client, headers, entity_type="contact", entity_id=contact["id"])
        document = make_document(client, headers, contact_id=contact["id"])

        files = client.get(f"/v1/contacts/{contact['id']}/files", headers=headers).json()["data"][
            "files"
        ]
        assert [f["id"] for f in files] == [record["id"]]
        assert files[0]["owner_name"] == "Asha Kumar"

        documents = client.get(f"/v1/contacts/{contact['id']}/documents", headers=headers).json()[
            "data"
        ]["documents"]
        assert [d["id"] for d in documents] == [document["id"]]

    def test_a_document_can_hang_off_a_deal(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        document = make_document(client, headers, deal_id=deal["id"])

        listed = client.get(f"/v1/deals/{deal['id']}/documents", headers=headers).json()["data"][
            "documents"
        ]
        assert [d["id"] for d in listed] == [document["id"]]

    def test_a_document_must_be_attached_to_something(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post("/v1/documents", headers=headers, json={"title": "Orphan"})
        assert response.status_code == 422

    def test_a_document_can_reference_a_registered_file(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        record = register_file(client, headers, name="terms.pdf")
        document = make_document(client, headers, contact_id=contact["id"], file_id=record["id"])
        assert document["file_id"] == record["id"]
        assert document["file_name"] == "terms.pdf"

    def test_an_unknown_parent_is_a_404(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/files",
            headers=headers,
            json={
                "name": "x.pdf",
                "size_bytes": 100,
                "mime_type": "application/pdf",
                "entity_type": "contact",
                "entity_id": str(uuid4()),
            },
        )
        assert response.status_code == 404


class TestDocumentLifecycle:
    def test_status_transitions_stamp_their_own_timestamps(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        document = make_document(client, headers, contact_id=contact["id"])
        assert document["status"] == "draft"
        assert document["sent_at"] is None

        sent = client.patch(
            f"/v1/documents/{document['id']}",
            headers={**headers, "If-Match": f'W/"{document["version"]}"'},
            json={"status": "sent"},
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()["data"]
        assert body["status"] == "sent"
        # Stamped by the server, never accepted from the client.
        assert body["sent_at"] is not None
        assert body["version"] == document["version"] + 1

    def test_a_stale_version_is_rejected(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        document = make_document(client, headers, contact_id=contact["id"])
        client.patch(
            f"/v1/documents/{document['id']}",
            headers={**headers, "If-Match": 'W/"1"'},
            json={"title": "First"},
        )
        conflicted = client.patch(
            f"/v1/documents/{document['id']}",
            headers={**headers, "If-Match": 'W/"1"'},
            json={"title": "Second"},
        )
        assert conflicted.status_code == 412

    def test_an_unknown_status_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        document = make_document(client, headers, contact_id=contact["id"])
        response = client.patch(
            f"/v1/documents/{document['id']}", headers=headers, json={"status": "shredded"}
        )
        assert response.status_code == 422

    def test_delete_hides_it_from_listing(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        document = make_document(client, headers, contact_id=contact["id"])

        assert client.delete(f"/v1/documents/{document['id']}", headers=headers).status_code == 200
        assert client.get(f"/v1/documents/{document['id']}", headers=headers).status_code == 404
        listed = client.get(f"/v1/contacts/{contact['id']}/documents", headers=headers).json()[
            "data"
        ]["documents"]
        assert document["id"] not in [d["id"] for d in listed]

    def test_deleting_a_file_hides_it(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        record = register_file(client, headers, entity_type="contact", entity_id=contact["id"])
        assert client.delete(f"/v1/files/{record['id']}", headers=headers).status_code == 200
        assert client.get(f"/v1/files/{record['id']}", headers=headers).status_code == 404


class TestTenantIsolation:
    def test_another_tenant_cannot_see_or_touch_a_file(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        record = register_file(client, acme)

        # Indistinguishable from an id that never existed.
        assert client.get(f"/v1/files/{record['id']}", headers=globex).status_code == 404
        assert client.delete(f"/v1/files/{record['id']}", headers=globex).status_code == 404
        assert client.get(f"/v1/files/{record['id']}/download", headers=globex).status_code == 404

        listed = client.get("/v1/files", headers=globex).json()["data"]["files"]
        assert record["id"] not in [f["id"] for f in listed]

    def test_another_tenant_cannot_see_or_touch_a_document(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme)
        document = make_document(client, acme, contact_id=contact["id"])

        assert client.get(f"/v1/documents/{document['id']}", headers=globex).status_code == 404
        assert (
            client.patch(
                f"/v1/documents/{document['id']}", headers=globex, json={"title": "Theirs"}
            ).status_code
            == 404
        )
        listed = client.get("/v1/documents", headers=globex).json()["data"]["documents"]
        assert document["id"] not in [d["id"] for d in listed]

    def test_a_document_cannot_be_attached_to_another_tenants_contact(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme)

        response = client.post(
            "/v1/documents",
            headers=globex,
            json={"title": "Cross tenant", "contact_id": contact["id"]},
        )
        assert response.status_code == 404


class TestAuditAndEvents:
    def test_uploads_and_documents_are_audited_and_emit_an_event(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        """The trail and the event commit with the row, in the same transaction.

        The read binds `app.tenant_id` first. Without it these tables return
        nothing at all, which is RLS doing its job rather than a missing row.
        """
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        contact = make_contact(client, headers)
        record = register_file(client, headers)
        document = make_document(client, headers, contact_id=contact["id"])

        async def read() -> tuple[set[str], dict[str, Any]]:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                actions = (
                    (
                        await conn.execute(
                            text(
                                "SELECT action FROM audit.audit_logs "
                                "WHERE resource_id IN (:file_id, :document_id)"
                            ),
                            {"file_id": record["id"], "document_id": document["id"]},
                        )
                    )
                    .scalars()
                    .all()
                )
                events = (
                    await conn.execute(
                        text(
                            "SELECT event_type, payload FROM audit.event_outbox "
                            "WHERE resource_id IN (:file_id, :document_id)"
                        ),
                        {"file_id": record["id"], "document_id": document["id"]},
                    )
                ).all()
                return set(actions), {row[0]: row[1] for row in events}

        actions, events = asyncio.new_event_loop().run_until_complete(read())

        assert {"file.upload_requested", "document.create"} <= actions
        assert {"file.upload_requested", "document.created"} <= events.keys()
        # Both events tell downstream handlers plainly that no bytes exist yet.
        assert events["file.upload_requested"]["data"]["stored"] is False
        assert events["document.created"]["data"]["stored"] is False

    def test_the_audit_trail_is_invisible_to_another_tenant(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        import asyncio

        from sqlalchemy import text

        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        other_tenant = str(client.get("/v1/auth/me", headers=globex).json()["data"]["tenant_id"])
        record = register_file(client, acme)

        async def count_for_other_tenant() -> int:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": other_tenant},
                )
                found = await conn.execute(
                    text("SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid"),
                    {"rid": record["id"]},
                )
                return int(found.scalar_one())

        assert asyncio.new_event_loop().run_until_complete(count_for_other_tenant()) == 0
