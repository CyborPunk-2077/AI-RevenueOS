"""Permission catalog and the built-in role matrix, enforced server-side."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from shared.compat import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"
    SUPPORT = "support"  # platform persona; scoped, never cross-tenant


class Scope(StrEnum):
    """Scope predicate applied inside the query, never after fetching rows."""

    GLOBAL = "global"
    BRANCH = "branch"
    TEAM = "team"
    SELF = "self"


RESOURCES: Final[tuple[str, ...]] = (
    "tenant",
    "billing",
    "subscription",
    "user",
    "role",
    "branch",
    "team",
    "contact",
    "account",
    "lead",
    "deal",
    "pipeline",
    "task",
    "note",
    "activity",
    "tag",
    "custom_field",
    "saved_view",
    "import",
    "export",
    "conversation",
    "message",
    "channel",
    "message_template",
    "consent",
    "appointment",
    "appointment_type",
    "resource",
    "document",
    "document_template",
    "file",
    "signature",
    "payment",
    "invoice",
    "payment_link",
    "workflow",
    "approval",
    "analytics",
    "report",
    "ai",
    "prompt",
    "api_key",
    "webhook",
    "integration",
    "audit_log",
    "privacy_request",
    "notification",
    "support_access",
)

ACTIONS: Final[tuple[str, ...]] = (
    "create",
    "read",
    "update",
    "delete",
    "list",
    "export",
    "assign",
    "merge",
    "approve",
    "execute",
    "configure",
    "transfer",
    "impersonate",
    "send",
    "refund",
)


def perm(resource: str, action: str) -> str:
    return f"{resource}:{action}"


ALL_PERMISSIONS: Final[frozenset[str]] = frozenset(perm(r, a) for r in RESOURCES for a in ACTIONS)

_CRUD = ("create", "read", "update", "delete", "list")
_RU = ("read", "list")


def _expand(spec: dict[str, tuple[str, ...]]) -> frozenset[str]:
    return frozenset(perm(r, a) for r, actions in spec.items() for a in actions)


# Owner-only permissions may never be granted to a custom role.
OWNER_ONLY: Final[frozenset[str]] = frozenset(
    {
        perm("tenant", "delete"),
        perm("tenant", "transfer"),
        perm("billing", "configure"),
        perm("subscription", "delete"),
        perm("payment", "configure"),
        perm("support_access", "approve"),
    }
)

SENSITIVE_PERMISSIONS: Final[frozenset[str]] = OWNER_ONLY | frozenset(
    {
        perm("payment", "refund"),
        perm("export", "create"),
        perm("api_key", "create"),
        perm("user", "impersonate"),
        perm("audit_log", "export"),
        perm("privacy_request", "delete"),
        perm("tenant", "configure"),
    }
)

_OWNER = ALL_PERMISSIONS - {perm("user", "impersonate")}

_ADMIN = _expand(
    {
        "tenant": ("read", "update", "configure"),
        "billing": ("read",),
        "subscription": ("read", "update"),
        "user": (*_CRUD, "assign"),
        "role": (*_CRUD,),
        "branch": (*_CRUD,),
        "team": (*_CRUD,),
        "contact": (*_CRUD, "assign", "merge", "export"),
        "account": (*_CRUD, "merge", "export"),
        "lead": (*_CRUD, "assign", "merge", "export"),
        "deal": (*_CRUD, "assign", "export"),
        "pipeline": (*_CRUD,),
        "task": (*_CRUD, "assign"),
        "note": (*_CRUD,),
        "activity": _RU,
        "tag": (*_CRUD,),
        "custom_field": (*_CRUD,),
        "saved_view": (*_CRUD,),
        "import": ("create", "read", "list"),
        "export": ("create", "read", "list"),
        "conversation": (*_CRUD, "assign", "send"),
        "message": ("create", "read", "list", "send"),
        "channel": (*_CRUD, "configure"),
        "message_template": (*_CRUD,),
        "consent": ("create", "read", "list", "update"),
        "appointment": (*_CRUD, "assign"),
        "appointment_type": (*_CRUD,),
        "resource": (*_CRUD,),
        "document": (*_CRUD, "send"),
        "document_template": (*_CRUD,),
        "file": ("create", "read", "list", "delete"),
        "signature": ("create", "read", "list"),
        "payment": ("read", "list", "create"),
        "invoice": (*_CRUD,),
        "payment_link": (*_CRUD,),
        "workflow": (*_CRUD, "execute"),
        "approval": ("read", "list", "approve"),
        "analytics": ("read", "list", "export"),
        "report": (*_CRUD, "export"),
        "ai": ("read", "execute"),
        "prompt": _RU,
        "api_key": ("create", "read", "list", "delete"),
        "webhook": (*_CRUD,),
        "integration": (*_CRUD, "configure"),
        "audit_log": ("read", "list", "export"),
        "privacy_request": ("create", "read", "list"),
        "notification": ("read", "list", "update"),
    }
)

_MANAGER = _expand(
    {
        "tenant": ("read",),
        "user": ("read", "list"),
        "branch": _RU,
        "team": ("read", "list", "update"),
        "contact": ("create", "read", "update", "list", "assign", "merge", "export"),
        "account": ("create", "read", "update", "list"),
        "lead": ("create", "read", "update", "list", "assign", "merge", "export"),
        "deal": ("create", "read", "update", "list", "assign", "export"),
        "pipeline": _RU,
        "task": (*_CRUD, "assign"),
        "note": (*_CRUD,),
        "activity": _RU,
        "tag": ("create", "read", "list"),
        "custom_field": _RU,
        "saved_view": (*_CRUD,),
        "import": ("create", "read", "list"),
        "export": ("create", "read", "list"),
        "conversation": ("create", "read", "update", "list", "assign", "send"),
        "message": ("create", "read", "list", "send"),
        "channel": _RU,
        "message_template": ("create", "read", "list", "update"),
        "consent": ("create", "read", "list"),
        "appointment": (*_CRUD, "assign"),
        "appointment_type": _RU,
        "resource": _RU,
        "document": ("create", "read", "update", "list", "send"),
        "document_template": _RU,
        "file": ("create", "read", "list"),
        "signature": ("create", "read", "list"),
        "payment": ("read", "list"),
        "invoice": ("create", "read", "list", "update"),
        "payment_link": ("create", "read", "list"),
        "workflow": ("create", "read", "update", "list", "execute"),
        "approval": ("read", "list", "approve"),
        "analytics": ("read", "list", "export"),
        "report": (*_CRUD, "export"),
        "ai": ("read", "execute"),
        "audit_log": ("read", "list"),
        "notification": ("read", "list", "update"),
    }
)

_MEMBER = _expand(
    {
        "tenant": ("read",),
        "user": ("read",),
        "contact": ("create", "read", "update", "list"),
        "account": ("read", "list"),
        "lead": ("create", "read", "update", "list"),
        "deal": ("create", "read", "update", "list"),
        "pipeline": _RU,
        "task": ("create", "read", "update", "list"),
        "note": (*_CRUD,),
        "activity": _RU,
        "tag": ("read", "list"),
        "custom_field": _RU,
        "saved_view": (*_CRUD,),
        "conversation": ("read", "update", "list", "send"),
        "message": ("create", "read", "list", "send"),
        "consent": ("read", "list"),
        "appointment": ("create", "read", "update", "list"),
        "appointment_type": _RU,
        "document": ("create", "read", "list"),
        "document_template": _RU,
        "file": ("create", "read", "list"),
        "payment_link": ("create", "read", "list"),
        "invoice": ("read", "list"),
        "workflow": ("read", "list", "execute"),
        "analytics": ("read",),
        "report": ("read", "list"),
        "ai": ("read", "execute"),
        "notification": ("read", "list", "update"),
    }
)

_VIEWER = _expand(
    dict.fromkeys(
        (
            "tenant",
            "user",
            "branch",
            "team",
            "contact",
            "account",
            "lead",
            "deal",
            "pipeline",
            "task",
            "note",
            "activity",
            "tag",
            "saved_view",
            "conversation",
            "message",
            "channel",
            "consent",
            "appointment",
            "document",
            "payment",
            "invoice",
            "workflow",
            "analytics",
            "report",
            "audit_log",
            "notification",
        ),
        _RU,
    )
)

_SUPPORT = _expand(
    {
        "tenant": ("read",),
        "user": ("read", "list"),
        "audit_log": ("read", "list"),
        "conversation": ("read", "list"),
        "lead": ("read", "list"),
        "contact": ("read", "list"),
        "workflow": ("read", "list"),
        "payment": ("read", "list"),
        "notification": ("read", "list"),
    }
)

ROLE_PERMISSIONS: Final[dict[Role, frozenset[str]]] = {
    Role.OWNER: _OWNER,
    Role.ADMIN: _ADMIN,
    Role.MANAGER: _MANAGER,
    Role.MEMBER: _MEMBER,
    Role.VIEWER: _VIEWER,
    Role.SUPPORT: _SUPPORT,
}

DEFAULT_ROLE_SCOPE: Final[dict[Role, Scope]] = {
    Role.OWNER: Scope.GLOBAL,
    Role.ADMIN: Scope.GLOBAL,
    Role.MANAGER: Scope.TEAM,
    Role.MEMBER: Scope.SELF,
    Role.VIEWER: Scope.TEAM,
    Role.SUPPORT: Scope.GLOBAL,
}


@dataclass(frozen=True, slots=True)
class EffectivePermissions:
    permissions: frozenset[str]
    scope: Scope
    branch_ids: frozenset[str] = frozenset()
    team_ids: frozenset[str] = frozenset()
    # Required for `self` scope: "assigned to me" is a predicate on the acting
    # user, not on their teams. Without it a self-scoped query cannot be built.
    user_id: str | None = None

    def allows(self, resource: str, action: str) -> bool:
        return perm(resource, action) in self.permissions

    def require(self, resource: str, action: str) -> None:
        if not self.allows(resource, action):
            raise PermissionError(f"missing permission {perm(resource, action)}")


def permissions_for(roles: list[Role] | list[str]) -> frozenset[str]:
    """Union of granted permissions across every assigned role."""
    granted: set[str] = set()
    for raw in roles:
        role = Role(raw) if not isinstance(raw, Role) else raw
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)


def widest_scope(roles: list[Role] | list[str]) -> Scope:
    order = [Scope.SELF, Scope.TEAM, Scope.BRANCH, Scope.GLOBAL]
    best = Scope.SELF
    for raw in roles:
        role = Role(raw) if not isinstance(raw, Role) else raw
        candidate = DEFAULT_ROLE_SCOPE.get(role, Scope.SELF)
        if order.index(candidate) > order.index(best):
            best = candidate
    return best


def validate_custom_role(permissions: set[str], *, max_permissions: int = 200) -> None:
    """Custom roles are allowlisted, capped and can never grant owner-only rights."""
    unknown = permissions - ALL_PERMISSIONS
    if unknown:
        raise ValueError(f"unknown permissions: {sorted(unknown)[:5]}")
    forbidden = permissions & OWNER_ONLY
    if forbidden:
        raise ValueError(f"owner-only permissions cannot be delegated: {sorted(forbidden)}")
    if len(permissions) > max_permissions:
        raise ValueError("custom role exceeds the permitted permission cap")
