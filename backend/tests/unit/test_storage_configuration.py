"""Storage configuration is fail-closed and separate from live activation."""

from __future__ import annotations

import pytest

from shared.settings import FeatureFlagDefaults, Settings


def configured_storage_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "prod",
        "jwt_private_key": "private",
        "jwt_public_key": "public",
        "encryption_master_key": "master-key",
        "s3_bucket_uploads": "airevenueos-prod-uploads",
        "s3_bucket_documents": "airevenueos-prod-documents",
        "s3_bucket_exports": "airevenueos-prod-exports",
        "s3_region": "ap-south-1",
        "clamav_host": "clamav.internal",
        "features": FeatureFlagDefaults(storage_enabled=True),
    }
    values.update(overrides)
    return Settings(**values)


def test_storage_defaults_disabled_and_names_every_gap() -> None:
    settings = Settings(environment="local")
    assert settings.features.storage_enabled is False
    issues = settings.storage_configuration_issues()
    assert any("S3_BUCKET_UPLOADS" in issue for issue in issues)
    assert any("CLAMAV_HOST" in issue for issue in issues)


def test_complete_declarative_configuration_passes_validation() -> None:
    settings = configured_storage_settings()
    assert settings.storage_configuration_issues() == []
    settings.assert_production_safe()


def test_enabled_storage_fails_production_boot_with_placeholders() -> None:
    settings = configured_storage_settings(s3_bucket_uploads="airevenueos-local-uploads")
    with pytest.raises(RuntimeError, match="storage configuration incomplete"):
        settings.assert_production_safe()


def test_storage_buckets_must_be_distinct() -> None:
    settings = configured_storage_settings(s3_bucket_exports="airevenueos-prod-uploads")
    assert "storage buckets must be distinct" in settings.storage_configuration_issues()


def test_custom_endpoint_must_be_https() -> None:
    settings = configured_storage_settings(s3_endpoint_url="http://minio.internal")
    assert "S3_ENDPOINT_URL must use HTTPS" in settings.storage_configuration_issues()
