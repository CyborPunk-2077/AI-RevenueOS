"""Who may build a form, and who may put one on the open internet."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain.auth.permissions import ROLE_PERMISSIONS, SENSITIVE_PERMISSIONS, Role, perm

pytestmark = pytest.mark.contract

FORM: dict[str, Any] = {
    "name": "Contact us",
    "schema": {"fields": [{"name": "email", "type": "email", "required": True}]},
    "allowed_origins": ["https://example.in"],
}
FORM_ID = "018f0000-0000-7000-8000-000000000001"


class TestPublishingIsItsOwnPermission:
    def test_publishing_is_classed_as_sensitive(self) -> None:
        """It puts an unauthenticated write surface on the internet."""
        assert perm("form", "publish") in SENSITIVE_PERMISSIONS

    @pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MANAGER])
    def test_staffing_roles_can_publish(self, role: Role) -> None:
        assert perm("form", "publish") in ROLE_PERMISSIONS[role]

    @pytest.mark.parametrize("role", [Role.MEMBER, Role.VIEWER])
    def test_ordinary_roles_can_read_but_not_publish(self, role: Role) -> None:
        assert perm("form", "read") in ROLE_PERMISSIONS[role]
        assert perm("form", "publish") not in ROLE_PERMISSIONS[role]
        assert perm("form", "create") not in ROLE_PERMISSIONS[role]


class TestAtTheEdge:
    def test_an_anonymous_caller_cannot_list_forms(self, client: TestClient) -> None:
        assert client.get("/v1/forms").status_code == 401

    def test_a_viewer_cannot_create(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/forms", headers=viewer_headers, json=FORM)
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "form:create"

    def test_a_viewer_cannot_publish(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.post(f"/v1/forms/{FORM_ID}/publish", headers=viewer_headers)
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "form:publish"

    def test_a_member_cannot_publish(
        self, client: TestClient, member_headers: dict[str, str]
    ) -> None:
        response = client.post(f"/v1/forms/{FORM_ID}/publish", headers=member_headers)
        assert response.status_code == 403

    def test_a_viewer_cannot_archive(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        assert client.delete(f"/v1/forms/{FORM_ID}", headers=viewer_headers).status_code == 403


class TestPayloadIsStrict:
    def test_an_invalid_schema_is_refused_before_it_is_stored(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A form with no contactable field never reaches the database."""
        response = client.post(
            "/v1/forms",
            headers=auth_headers,
            json={**FORM, "schema": {"fields": [{"name": "message", "type": "textarea"}]}},
        )
        assert response.status_code == 422
        assert "cannot be contacted" in str(response.json()["error"]["details"]["problems"])

    def test_a_wildcard_origin_is_refused(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/forms", headers=auth_headers, json={**FORM, "allowed_origins": ["*"]}
        )
        assert response.status_code == 422

    def test_extra_fields_are_refused(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/forms", headers=auth_headers, json={**FORM, "is_published": True}
        )
        assert response.status_code == 422

    def test_the_routes_are_mounted_under_the_versioned_surface(self, client: TestClient) -> None:
        paths = client.get("/v1/openapi.json").json()["paths"]
        assert "/v1/forms" in paths
        assert "/v1/forms/{form_id}/publish" in paths
