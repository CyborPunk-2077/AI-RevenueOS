"""Tenant repository reads cannot silently omit the principal's effective scope."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from infrastructure.database.repositories.base import TenantRepository

APPLICATION_ROOT = Path(__file__).resolve().parents[2] / "src" / "application"


def test_every_public_repository_read_requires_effective_permissions() -> None:
    for method_name in ("get", "get_or_404", "count", "paginate_cursor", "soft_delete_by_id"):
        signature = inspect.signature(getattr(TenantRepository, method_name))
        assert "perms" in signature.parameters
    assert not hasattr(TenantRepository, "base_query")
    assert not hasattr(TenantRepository, "apply_scope")


def test_application_services_cannot_reach_private_unscoped_query_builders() -> None:
    violations: list[str] = []
    for path in APPLICATION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "base_query",
                "apply_scope",
                "_tenant_query",
                "_apply_scope",
            }:
                violations.append(f"{path.relative_to(APPLICATION_ROOT)}:{node.lineno}")
    assert violations == []
