"""Who may configure the widget, and what the public surface refuses."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from domain.auth.permissions import ROLE_PERMISSIONS, Role, perm

pytestmark = pytest.mark.contract

WIDGET = {"allowed_origins": ["https://example.in"], "greeting": "Hello"}


class TestConfigurationIsAdminWork:
    @pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN])
    def test_admins_may_configure_a_channel(self, role: Role) -> None:
        assert perm("channel", "configure") in ROLE_PERMISSIONS[role]

    @pytest.mark.parametrize("role", [Role.MEMBER, Role.VIEWER, Role.MANAGER])
    def test_everyone_else_may_only_read(self, role: Role) -> None:
        assert perm("channel", "read") in ROLE_PERMISSIONS[role]
        assert perm("channel", "configure") not in ROLE_PERMISSIONS[role]

    def test_an_anonymous_caller_cannot_read_the_widget(self, client: TestClient) -> None:
        assert client.get("/v1/webchat/widget").status_code == 401

    def test_a_viewer_cannot_configure(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.put("/v1/webchat/widget", headers=viewer_headers, json=WIDGET)
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "channel:configure"

    def test_a_viewer_cannot_rotate_the_key(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/webchat/widget/rotate-key", headers=viewer_headers)
        assert response.status_code == 403

    def test_extra_fields_are_refused(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """`public_key` is issued by the server, never supplied."""
        response = client.put(
            "/v1/webchat/widget", headers=auth_headers, json={**WIDGET, "public_key": "wck_x"}
        )
        assert response.status_code == 422


class TestThePublicSurface:
    def test_the_routes_are_mounted_and_versioned(self, client: TestClient) -> None:
        paths = client.get("/v1/openapi.json").json()["paths"]
        assert "/v1/public/webchat/sessions" in paths
        assert "/v1/public/webchat/messages" in paths
        assert "/v1/public/webchat/config" in paths

    def test_the_public_routes_require_no_authentication(self, client: TestClient) -> None:
        """A stranger on someone else's website has no account to sign in with."""
        response = client.get("/v1/public/webchat/config", params={"public_key": "wck_nope"})
        assert response.status_code != 401

    def test_a_malformed_key_is_a_flat_not_found(self, client: TestClient) -> None:
        """Never distinguish "no such widget" from "widget is off"."""
        response = client.get(
            "/v1/public/webchat/config",
            params={"public_key": "not-a-key"},
            headers={"Origin": "https://example.in"},
        )
        assert response.status_code == 404
        assert "not available" in response.json()["error"]["message"]

    def test_starting_a_session_without_a_key_is_refused_at_the_boundary(
        self, client: TestClient
    ) -> None:
        response = client.post("/v1/public/webchat/sessions", json={"visitor_ref": "abc"})
        assert response.status_code == 422

    def test_an_oversized_message_is_refused_before_any_lookup(self, client: TestClient) -> None:
        response = client.post(
            "/v1/public/webchat/messages",
            json={"session_token": "018f0000-0000-7000-8000-000000000001.x", "body": "a" * 5000},
        )
        assert response.status_code == 422

    def test_a_malformed_session_token_ends_the_conversation_politely(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/v1/public/webchat/transcript", params={"session_token": "garbage-token"}
        )
        assert response.status_code == 404
        assert "ended" in response.json()["error"]["message"]
