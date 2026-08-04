"""An invitation must never grant more authority than the inviter holds."""

from __future__ import annotations

import pytest

from application.auth.invitations import ASSIGNABLE_ROLES, assignable_roles
from domain.auth.permissions import Role


class TestPrivilegeCeiling:
    def test_an_owner_can_staff_the_whole_organisation(self) -> None:
        assert Role.OWNER in assignable_roles(("owner",))
        assert Role.VIEWER in assignable_roles(("owner",))

    def test_an_admin_cannot_mint_an_owner(self) -> None:
        """Otherwise one request turns an admin into a peer of the account holder."""
        assert Role.OWNER not in assignable_roles(("admin",))
        assert Role.ADMIN in assignable_roles(("admin",))

    def test_a_manager_cannot_mint_an_admin(self) -> None:
        allowed = assignable_roles(("manager",))
        assert allowed == frozenset({Role.MEMBER, Role.VIEWER})

    @pytest.mark.parametrize("role", ["member", "viewer", "support"])
    def test_roles_without_staffing_authority_can_invite_nobody(self, role: str) -> None:
        assert assignable_roles((role,)) == frozenset()

    def test_an_unknown_role_grants_nothing_rather_than_everything(self) -> None:
        """A role string from a stale token must fail closed."""
        assert assignable_roles(("archivist",)) == frozenset()
        assert assignable_roles(("archivist", "manager")) == frozenset({Role.MEMBER, Role.VIEWER})

    def test_multiple_roles_take_the_widest_ceiling(self) -> None:
        assert assignable_roles(("viewer", "admin")) == ASSIGNABLE_ROLES[Role.ADMIN]

    def test_every_role_in_the_matrix_has_an_explicit_entry(self) -> None:
        """A new role must be classified deliberately, not default to permissive."""
        assert set(ASSIGNABLE_ROLES) == set(Role)

    def test_no_role_can_assign_something_outside_the_role_enum(self) -> None:
        for granted in ASSIGNABLE_ROLES.values():
            assert granted <= set(Role)
