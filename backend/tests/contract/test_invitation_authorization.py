"""Authorisation at the invitation edge, and what the two open routes may reveal."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.contract

INVITE = {"email": "asha@example.in", "role": "member"}


class TestStaffingRequiresAuthority:
    def test_an_anonymous_caller_cannot_invite(self, client: TestClient) -> None:
        assert client.post("/v1/users/invitations", json=INVITE).status_code == 401

    def test_a_viewer_cannot_invite(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/users/invitations", headers=viewer_headers, json=INVITE)
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "user:create"

    def test_a_viewer_cannot_revoke(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.delete(
            "/v1/users/invitations/018f0000-0000-7000-8000-000000000001",
            headers=viewer_headers,
        )
        assert response.status_code == 403

    def test_the_route_is_mounted_under_the_versioned_surface(self, client: TestClient) -> None:
        """No implicit routes: every external path is versioned."""
        paths = client.get("/v1/openapi.json").json()["paths"]
        assert "/v1/users/invitations" in paths
        assert "/v1/invitations/accept" in paths


class TestPayloadIsStrict:
    def test_an_unknown_role_is_refused_at_the_boundary(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A role the matrix has never heard of must not reach the service."""
        response = client.post(
            "/v1/users/invitations",
            headers=auth_headers,
            json={"email": "asha@example.in", "role": "superuser"},
        )
        assert response.status_code == 422

    def test_extra_fields_are_refused(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """`is_owner: true` smuggled into the body must not be silently ignored."""
        response = client.post(
            "/v1/users/invitations",
            headers=auth_headers,
            json={**INVITE, "is_owner": True},
        )
        assert response.status_code == 422


class TestTheOpenRoutesAreNotAnOracle:
    """Preview and accept are unauthenticated by necessity; they must stay dull."""

    def test_a_malformed_token_is_a_flat_not_found(self, client: TestClient) -> None:
        response = client.get("/v1/invitations/preview", params={"token": "bogus.secret"})
        assert response.status_code == 404
        # The same message regardless of why: wrong, expired and already used must
        # not be distinguishable, or the endpoint enumerates invitations.
        assert "invalid, expired, or has already been used" in response.json()["error"]["message"]

    def test_accepting_a_malformed_token_says_exactly_the_same_thing(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/v1/invitations/accept",
            json={
                "token": "bogus.secret",
                "full_name": "Asha Menon",
                "password": "a-long-enough-passphrase-2026",
            },
        )
        assert response.status_code == 404
        assert "invalid, expired, or has already been used" in response.json()["error"]["message"]

    def test_a_weak_password_is_refused_before_any_lookup(self, client: TestClient) -> None:
        response = client.post(
            "/v1/invitations/accept",
            json={"token": "bogus.secret", "full_name": "Asha", "password": "aaaaaaaaaaaa"},
        )
        assert response.status_code == 422
