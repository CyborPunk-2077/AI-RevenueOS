"""Security controls: hashing, token lifecycle, MFA, encryption and RBAC."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from domain.auth.permissions import (
    ALL_PERMISSIONS,
    OWNER_ONLY,
    ROLE_PERMISSIONS,
    Role,
    Scope,
    permissions_for,
    validate_custom_role,
    widest_scope,
)
from infrastructure.auth.encryption import (
    DecryptionError,
    EnvelopeEncryptor,
    mask_secret,
    redact_config,
)
from infrastructure.auth.mfa import (
    RECOVERY_CODE_COUNT,
    current_totp,
    generate_recovery_codes,
    generate_totp_secret,
    provisioning_uri,
    verify_recovery_code,
    verify_totp,
)
from infrastructure.auth.passwords import (
    MAX_FAILED_ATTEMPTS,
    hash_password,
    hibp_prefix,
    is_in_history,
    lockout_state,
    needs_rehash,
    next_lockout,
    password_expired,
    push_history,
    validate_password,
    verify_password,
)
from infrastructure.auth.tokens import (
    AccessClaims,
    TokenService,
    evaluate_rotation,
    generate_keypair,
    generate_refresh_token,
    hash_refresh_token,
    reauth_required,
    requires_step_up,
    sessions_to_evict,
)
from shared.utils.timeutil import UTC

UTC = UTC
KEYS = generate_keypair()


@pytest.fixture(scope="module")
def token_service() -> TokenService:
    private, public = KEYS
    return TokenService(private_key=private, public_key=public, issuer="https://api.test")


class TestPasswordHashing:
    def test_hash_is_argon2id_with_specified_parameters(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert hashed.startswith("$argon2id$")
        assert "m=65536,t=3,p=4" in hashed

    def test_verify_round_trip_and_rejection(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed) is True
        assert verify_password("wrong password entirely", hashed) is False

    def test_salts_are_unique(self) -> None:
        assert hash_password("same password here") != hash_password("same password here")

    def test_malformed_hash_is_rejected_not_raised(self) -> None:
        assert verify_password("anything", "not-a-hash") is False
        assert needs_rehash("not-a-hash") is True


class TestPasswordPolicy:
    def test_minimum_length(self) -> None:
        assert validate_password("Short1!").ok is False
        assert validate_password("a-long-enough-passphrase").ok is True

    def test_common_password_rejected(self) -> None:
        assert validate_password("password123").ok is False

    def test_password_containing_email_local_part_rejected(self) -> None:
        result = validate_password("asharocks2026!!", email="asha@example.in")
        assert result.ok is False

    def test_password_containing_name_rejected(self) -> None:
        assert validate_password("ravishankar2026", full_name="Ravi Shankar").ok is False

    def test_low_entropy_rejected(self) -> None:
        assert validate_password("aaaaaaaaaaaaaa").ok is False

    def test_history_prevents_reuse(self) -> None:
        history = [hash_password("previous passphrase 1"), hash_password("previous passphrase 2")]
        assert is_in_history("previous passphrase 2", history) is True
        assert is_in_history("a brand new passphrase", history) is False

    def test_history_is_capped_at_five(self) -> None:
        history: list[str] = []
        for i in range(8):
            history = push_history(hash_password(f"passphrase number {i}"), history)
        assert len(history) == 5

    def test_hibp_only_leaks_a_five_character_prefix(self) -> None:
        prefix, suffix = hibp_prefix("correct horse battery staple")
        assert len(prefix) == 5 and prefix.isupper()
        assert len(prefix) + len(suffix) == 40

    def test_admin_passwords_expire_after_ninety_days(self) -> None:
        old = datetime(2026, 1, 1, tzinfo=UTC)
        now = datetime(2026, 8, 1, tzinfo=UTC)
        assert password_expired(is_admin_role=True, password_changed_at=old, now=now) is True
        assert password_expired(is_admin_role=False, password_changed_at=old, now=now) is False

    def test_lockout_after_five_failures(self) -> None:
        assert lockout_state(MAX_FAILED_ATTEMPTS, None)[0] is True
        assert lockout_state(MAX_FAILED_ATTEMPTS - 1, None)[0] is False
        assert next_lockout(MAX_FAILED_ATTEMPTS - 1) is not None
        assert next_lockout(0) is None

    def test_lockout_reports_remaining_seconds(self) -> None:
        until = datetime.now(UTC) + timedelta(minutes=15)
        locked, seconds = lockout_state(5, until)
        assert locked is True and 800 < seconds <= 900


class TestAccessTokens:
    def _claims(self) -> AccessClaims:
        return AccessClaims(
            sub=str(uuid4()),
            tenant_id=str(uuid4()),
            tenant_slug="acme",
            email="asha@example.in",
            name="Asha",
            roles=["admin"],
            permissions=["lead:read", "lead:create"],
            scope="global",
            session_id="sess-1",
        )

    def test_round_trip_preserves_scope_claims(self, token_service: TokenService) -> None:
        claims = self._claims()
        token, expires = token_service.issue_access_token(claims)
        decoded = token_service.decode_access_token(token)
        assert decoded["tenant_id"] == claims.tenant_id
        assert decoded["permissions"] == claims.permissions
        assert decoded["scope"] == "global"
        assert 890 <= (expires - datetime.now(UTC)).total_seconds() <= 900

    def test_algorithm_is_rs256_and_kid_is_present(self, token_service: TokenService) -> None:
        import jwt

        token, _ = token_service.issue_access_token(self._claims())
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"
        assert header["kid"]

    def test_alg_none_token_is_rejected(self, token_service: TokenService) -> None:
        import jwt

        from shared.exceptions import Unauthenticated

        forged = jwt.encode({"sub": "x", "jti": "y"}, key="", algorithm="none")
        with pytest.raises(Unauthenticated):
            token_service.decode_access_token(forged)

    def test_hs256_confusion_attack_is_rejected(self, token_service: TokenService) -> None:
        import jwt

        from shared.exceptions import Unauthenticated

        forged = jwt.encode(
            {
                "sub": "x",
                "jti": "y",
                "iss": "https://api.test",
                "aud": "airevenueos-api",
                "exp": 9_999_999_999,
                "iat": 1,
            },
            key="an-attacker-chosen-hmac-secret",
            algorithm="HS256",
        )
        with pytest.raises(Unauthenticated):
            token_service.decode_access_token(forged)

    def test_expired_token_raises_token_expired(self) -> None:
        from shared.exceptions import TokenExpired

        private, public = KEYS
        short = TokenService(
            private_key=private, public_key=public, issuer="https://api.test", access_ttl=-1
        )
        token, _ = short.issue_access_token(self._claims())
        with pytest.raises(TokenExpired):
            short.decode_access_token(token)

    def test_wrong_issuer_is_rejected(self, token_service: TokenService) -> None:
        from shared.exceptions import Unauthenticated

        private, public = KEYS
        other = TokenService(private_key=private, public_key=public, issuer="https://evil.test")
        token, _ = other.issue_access_token(self._claims())
        with pytest.raises(Unauthenticated):
            token_service.decode_access_token(token)

    def test_hs_secret_construction_is_refused(self) -> None:
        with pytest.raises(RuntimeError):
            TokenService(private_key="", public_key="", issuer="x")

    def test_jwks_exposes_only_public_material(self, token_service: TokenService) -> None:
        jwks = token_service.jwks()
        key = jwks["keys"][0]
        assert key["kty"] == "RSA" and key["alg"] == "RS256"
        assert "d" not in key and "p" not in key


class TestRefreshRotation:
    def test_only_the_hash_is_storable(self) -> None:
        plaintext, hashed, jti = generate_refresh_token()
        assert plaintext.startswith(jti)
        assert hashed == hash_refresh_token(plaintext)
        assert plaintext not in hashed

    def test_valid_rotation_is_accepted(self) -> None:
        _, hashed, _ = generate_refresh_token()
        outcome = evaluate_rotation(
            stored_hash=hashed,
            presented_hash=hashed,
            revoked_at=None,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            family_id=uuid4(),
        )
        assert outcome.accepted is True

    def test_reuse_of_a_rotated_token_revokes_the_family(self) -> None:
        _, hashed, _ = generate_refresh_token()
        family = uuid4()
        outcome = evaluate_rotation(
            stored_hash=hashed,
            presented_hash=hashed,
            revoked_at=datetime.now(UTC) - timedelta(minutes=1),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            family_id=family,
        )
        assert outcome.accepted is False
        assert outcome.reuse_detected is True
        assert outcome.revoke_family == family

    def test_expired_token_is_rejected(self) -> None:
        _, hashed, _ = generate_refresh_token()
        outcome = evaluate_rotation(
            stored_hash=hashed,
            presented_hash=hashed,
            revoked_at=None,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            family_id=uuid4(),
        )
        assert outcome.accepted is False and outcome.reuse_detected is False

    def test_unknown_token_is_rejected_without_family_revocation(self) -> None:
        outcome = evaluate_rotation(
            stored_hash=None,
            presented_hash="x",
            revoked_at=None,
            expires_at=None,
            family_id=uuid4(),
        )
        assert outcome.accepted is False and outcome.revoke_family is None

    def test_session_cap_evicts_the_oldest(self) -> None:
        sessions = [f"s{i}" for i in range(10)]
        assert sessions_to_evict(sessions) == ["s0"]
        assert sessions_to_evict([f"s{i}" for i in range(5)]) == []

    def test_idle_and_hard_reauth_windows(self) -> None:
        now = datetime.now(UTC)
        assert reauth_required(
            authenticated_at=now, last_activity_at=now - timedelta(hours=3), now=now
        ) == (True, "idle_reauth")
        assert reauth_required(
            authenticated_at=now - timedelta(hours=9), last_activity_at=now, now=now
        ) == (True, "hard_reauth")
        assert reauth_required(authenticated_at=now, last_activity_at=now, now=now) == (False, None)

    @pytest.mark.parametrize(
        "operation",
        [
            "billing.update",
            "export.create",
            "tenant.delete",
            "tenant.transfer_ownership",
            "api_key.create",
            "payment.refund_high_value",
        ],
    )
    def test_sensitive_operations_demand_step_up(self, operation: str) -> None:
        now = datetime.now(UTC)
        assert (
            requires_step_up(operation, mfa_verified=False, authenticated_at=now, now=now) is True
        )
        assert (
            requires_step_up(operation, mfa_verified=True, authenticated_at=now, now=now) is False
        )
        assert (
            requires_step_up(
                operation, mfa_verified=True, authenticated_at=now - timedelta(hours=1), now=now
            )
            is True
        )

    def test_ordinary_operation_does_not(self) -> None:
        assert (
            requires_step_up("lead.read", mfa_verified=False, authenticated_at=datetime.now(UTC))
            is False
        )


class TestMfa:
    def test_totp_verifies_within_the_drift_window(self) -> None:
        secret = generate_totp_secret()
        at = 1_800_000_000.0
        code = current_totp(secret, at=at)
        assert verify_totp(secret, code, at=at) is True
        assert verify_totp(secret, code, at=at + 30) is True
        assert verify_totp(secret, code, at=at + 120) is False

    def test_malformed_codes_rejected(self) -> None:
        secret = generate_totp_secret()
        for bad in ("", "abc", "12345", "1234567"):
            assert verify_totp(secret, bad) is False

    def test_different_secrets_do_not_collide(self) -> None:
        a, b = generate_totp_secret(), generate_totp_secret()
        assert current_totp(a, at=1_800_000_000) != current_totp(b, at=1_800_000_000)

    def test_provisioning_uri_shape(self) -> None:
        uri = provisioning_uri(generate_totp_secret(), account="asha@example.in")
        assert uri.startswith("otpauth://totp/")
        assert "digits=6" in uri and "period=30" in uri

    def test_eight_bcrypt_recovery_codes_are_issued(self) -> None:
        codes = generate_recovery_codes()
        assert len(codes.plaintext) == RECOVERY_CODE_COUNT == 8
        assert all(h.startswith("$2b$") for h in codes.hashes)
        assert all(code not in " ".join(codes.hashes) for code in codes.plaintext)

    def test_recovery_code_is_single_use(self) -> None:
        codes = generate_recovery_codes(count=3)
        index = verify_recovery_code(codes.plaintext[1], codes.hashes)
        assert index == 1
        remaining = [h for i, h in enumerate(codes.hashes) if i != index]
        assert verify_recovery_code(codes.plaintext[1], remaining) is None

    def test_unknown_recovery_code_returns_none(self) -> None:
        codes = generate_recovery_codes(count=2)
        assert verify_recovery_code("NOPE1-NOPE2", codes.hashes) is None


class TestEnvelopeEncryption:
    KEY = "a" * 48

    def test_round_trip(self) -> None:
        enc = EnvelopeEncryptor(self.KEY)
        tenant = str(uuid4())
        blob = enc.encrypt("razorpay_secret_value", tenant_id=tenant)
        assert enc.decrypt_str(blob, tenant_id=tenant) == "razorpay_secret_value"

    def test_ciphertext_never_contains_the_plaintext(self) -> None:
        enc = EnvelopeEncryptor(self.KEY)
        blob = enc.encrypt("super-secret-token", tenant_id=str(uuid4()))
        assert "super-secret-token" not in blob

    def test_nonce_is_fresh_per_write(self) -> None:
        enc = EnvelopeEncryptor(self.KEY)
        tenant = str(uuid4())
        assert enc.encrypt("same", tenant_id=tenant) != enc.encrypt("same", tenant_id=tenant)

    def test_cross_tenant_decryption_is_refused(self) -> None:
        enc = EnvelopeEncryptor(self.KEY)
        blob = enc.encrypt("secret", tenant_id=str(uuid4()))
        with pytest.raises(DecryptionError):
            enc.decrypt(blob, tenant_id=str(uuid4()))

    def test_tampered_ciphertext_fails_authentication(self) -> None:
        enc = EnvelopeEncryptor(self.KEY)
        tenant = str(uuid4())
        blob = enc.encrypt("secret", tenant_id=tenant)
        head, _, tail = blob.rpartition(":")
        middle = len(tail) // 2
        swap = "B" if tail[middle] != "B" else "C"
        tampered = f"{head}:{tail[:middle]}{swap}{tail[middle + 1 :]}"
        with pytest.raises(DecryptionError):
            enc.decrypt(tampered, tenant_id=tenant)

    def test_key_rotation_preserves_plaintext(self) -> None:
        enc = EnvelopeEncryptor(self.KEY)
        tenant = str(uuid4())
        v1 = enc.encrypt("secret", tenant_id=tenant, key_version=1)
        v2 = enc.rotate(v1, tenant_id=tenant, new_key_version=2)
        assert enc.decrypt_str(v2, tenant_id=tenant) == "secret"
        assert v2.split(":")[1] == "2"

    def test_short_master_key_is_refused(self) -> None:
        with pytest.raises(ValueError):
            EnvelopeEncryptor("too-short")

    def test_masking_and_config_redaction(self) -> None:
        assert mask_secret("rzp_live_abcdefgh") == "*************efgh"
        redacted = redact_config({"api_key": "abcdefgh", "region": "ap-south-1"})
        assert redacted["region"] == "ap-south-1"
        assert redacted["api_key"].endswith("efgh") and redacted["api_key"].startswith("*")


class TestRoleMatrix:
    def test_owner_holds_the_widest_permission_set(self) -> None:
        owner = ROLE_PERMISSIONS[Role.OWNER]
        for role in (Role.ADMIN, Role.MANAGER, Role.MEMBER, Role.VIEWER):
            assert ROLE_PERMISSIONS[role] < owner

    def test_permission_sets_narrow_down_the_hierarchy(self) -> None:
        assert len(ROLE_PERMISSIONS[Role.ADMIN]) > len(ROLE_PERMISSIONS[Role.MANAGER])
        assert len(ROLE_PERMISSIONS[Role.MANAGER]) > len(ROLE_PERMISSIONS[Role.MEMBER])
        assert len(ROLE_PERMISSIONS[Role.MEMBER]) > len(ROLE_PERMISSIONS[Role.VIEWER])

    def test_viewer_has_no_write_permissions(self) -> None:
        writes = {"create", "update", "delete", "send", "refund", "approve", "execute", "transfer"}
        assert not any(p.split(":")[1] in writes for p in ROLE_PERMISSIONS[Role.VIEWER])

    def test_owner_only_permissions_are_not_delegated(self) -> None:
        for role in (Role.ADMIN, Role.MANAGER, Role.MEMBER, Role.VIEWER, Role.SUPPORT):
            assert not (ROLE_PERMISSIONS[role] & OWNER_ONLY)

    def test_support_persona_is_read_scoped(self) -> None:
        assert all(p.endswith((":read", ":list")) for p in ROLE_PERMISSIONS[Role.SUPPORT])

    def test_union_across_multiple_roles(self) -> None:
        combined = permissions_for([Role.MEMBER, Role.MANAGER])
        assert combined == ROLE_PERMISSIONS[Role.MEMBER] | ROLE_PERMISSIONS[Role.MANAGER]

    def test_widest_scope_wins(self) -> None:
        assert widest_scope([Role.MEMBER, Role.ADMIN]) is Scope.GLOBAL
        assert widest_scope([Role.MEMBER]) is Scope.SELF

    def test_custom_role_rejects_unknown_permissions(self) -> None:
        with pytest.raises(ValueError, match="unknown"):
            validate_custom_role({"lead:read", "database:drop"})

    def test_custom_role_cannot_take_owner_only_rights(self) -> None:
        with pytest.raises(ValueError, match="owner-only"):
            validate_custom_role({"lead:read", "tenant:delete"})

    def test_custom_role_is_capped(self) -> None:
        with pytest.raises(ValueError, match="cap"):
            validate_custom_role(set(list(ALL_PERMISSIONS - OWNER_ONLY)[:250]))

    def test_valid_custom_role_passes(self) -> None:
        validate_custom_role({"lead:read", "lead:create", "contact:read"})
