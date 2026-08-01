"""Universal contract: envelope shape, error codes, security headers and CORS."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.exceptions import ERROR_CODES

pytestmark = pytest.mark.contract


class TestSuccessEnvelope:
    def test_shape(self, client: TestClient) -> None:
        body = client.get("/v1/plans").json()
        assert body["success"] is True
        assert "data" in body
        assert set(body["meta"]) >= {"request_id", "timestamp", "version"}
        assert body["meta"]["version"] == "v1"

    def test_request_id_is_echoed_when_supplied(self, client: TestClient) -> None:
        response = client.get("/v1/plans", headers={"X-Request-ID": "corr-123"})
        assert response.headers["X-Request-ID"] == "corr-123"
        assert response.json()["meta"]["request_id"] == "corr-123"

    def test_request_id_is_generated_when_absent(self, client: TestClient) -> None:
        assert client.get("/v1/plans").headers["X-Request-ID"]

    def test_timestamp_is_iso_utc(self, client: TestClient) -> None:
        from datetime import datetime

        stamp = client.get("/v1/plans").json()["meta"]["timestamp"]
        assert datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is not None


class TestFailureEnvelope:
    def test_unauthenticated_shape(self, client: TestClient) -> None:
        response = client.get("/v1/tenant")
        body = response.json()
        assert response.status_code == 401
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHENTICATED"
        assert "details" in body["error"]

    def test_invalid_token_is_unauthenticated(self, client: TestClient) -> None:
        response = client.get("/v1/tenant", headers={"Authorization": "Bearer not-a-token"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_forbidden_names_the_missing_permission(
        self, client: TestClient, viewer_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/leads",
            headers=viewer_headers,
            json={"first_name": "Asha", "email": "asha@example.in"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert response.json()["error"]["details"]["required_permission"] == "lead:create"

    def test_validation_error_lists_fields(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/leads", headers=auth_headers, json={"first_name": ""})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"]["fields"]

    def test_unknown_field_is_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/leads",
            headers=auth_headers,
            json={"first_name": "Asha", "email": "a@b.in", "is_admin": True},
        )
        assert response.status_code == 422

    def test_not_found_shape(self, client: TestClient) -> None:
        response = client.get("/v1/industry-templates/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_every_documented_error_code_exists(self) -> None:
        assert len(ERROR_CODES) == 13
        assert "QUOTA_EXCEEDED" in ERROR_CODES

    def test_internal_errors_do_not_leak_details(self, client: TestClient) -> None:
        # A non-existent route yields a stable envelope, never a stack trace.
        response = client.get("/v1/definitely-not-a-route")
        assert "Traceback" not in response.text


class TestSecurityHeaders:
    def test_headers_are_present(self, client: TestClient) -> None:
        headers = client.get("/health").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_hsts_is_absent_locally(self, client: TestClient) -> None:
        assert "Strict-Transport-Security" not in client.get("/health").headers


class TestCors:
    def test_trusted_origin_is_allowed(self, client: TestClient) -> None:
        response = client.options(
            "/v1/plans",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 204)
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_untrusted_origin_is_not_credentialed(self, client: TestClient) -> None:
        response = client.get("/v1/plans", headers={"Origin": "https://evil.example.com"})
        assert response.headers.get("access-control-allow-origin") != "https://evil.example.com"

    def test_unsafe_request_from_a_foreign_origin_is_refused(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/leads",
            headers={**auth_headers, "Origin": "https://evil.example.com"},
            json={"first_name": "Asha", "email": "a@b.in"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_null_origin_is_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/leads",
            headers={**auth_headers, "Origin": "null"},
            json={"first_name": "Asha", "email": "a@b.in"},
        )
        assert response.status_code == 403

    def test_webhook_routes_are_exempt_from_origin_enforcement(self, client: TestClient) -> None:
        response = client.post(
            "/v1/webhooks/inbound/razorpay",
            headers={"Origin": "https://api.razorpay.com"},
            content=b"{}",
        )
        # Rejected on signature, not on origin.
        assert response.status_code == 403
        assert "Signature" in response.json()["error"]["message"]


class TestBodyLimits:
    def test_oversized_body_is_rejected_before_parsing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/leads",
            headers={**auth_headers, "Content-Length": str(11 * 1024 * 1024)},
            json={"first_name": "Asha"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestHealthAndMeta:
    def test_health_exposes_no_provider_detail(self, client: TestClient) -> None:
        body = client.get("/health").json()["data"]
        assert body["status"] == "ok"
        assert "database_url" not in str(body)
        assert "secret" not in str(body).lower()

    def test_liveness_and_version(self, client: TestClient) -> None:
        assert client.get("/health/liveness").json()["data"]["status"] == "alive"
        assert client.get("/version").json()["data"]["api_version"] == "v1"

    def test_metrics_is_ip_restricted(self, client: TestClient) -> None:
        assert client.get("/health/metrics").status_code == 404

    def test_openapi_is_versioned(self, client: TestClient) -> None:
        spec = client.get("/v1/openapi.json").json()
        assert all(path.startswith(("/v1", "/health", "/version")) for path in spec["paths"])
