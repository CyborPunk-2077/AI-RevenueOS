"""RS256 access tokens and opaque rotating refresh tokens with reuse detection."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from shared.exceptions import TokenExpired, Unauthenticated
from shared.utils.timeutil import utcnow

ACCESS_TTL_SECONDS = 900
REFRESH_TTL_SECONDS = 604_800
MAX_SESSIONS_PER_USER = 10
IDLE_REAUTH_SECONDS = 7_200
HARD_REAUTH_SECONDS = 28_800
ALGORITHM = "RS256"


def generate_keypair() -> tuple[str, str]:
    """Development/test convenience. Production keys are KMS-protected."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


@dataclass(frozen=True, slots=True)
class AccessClaims:
    sub: str
    tenant_id: str
    tenant_slug: str
    email: str
    name: str
    roles: list[str]
    permissions: list[str]
    scope: str = "self"
    branch_ids: list[str] = field(default_factory=list)
    team_ids: list[str] = field(default_factory=list)
    jti: str = ""
    session_id: str = ""
    mfa_verified: bool = False
    authenticated_at: int = 0
    actor_type: str = "user"


class TokenService:
    def __init__(
        self,
        *,
        private_key: str,
        public_key: str,
        issuer: str,
        kid: str = "local-dev",
        access_ttl: int = ACCESS_TTL_SECONDS,
    ) -> None:
        if not private_key or not public_key:
            raise RuntimeError("RS256 signing material is required; HS secrets are forbidden")
        self._private = private_key
        self._public = public_key
        self._issuer = issuer
        self._kid = kid
        self._access_ttl = access_ttl

    # -- access token --------------------------------------------------
    def issue_access_token(self, claims: AccessClaims) -> tuple[str, datetime]:
        now = utcnow()
        expires = now + timedelta(seconds=self._access_ttl)
        payload: dict[str, Any] = {
            "sub": claims.sub,
            "tenant_id": claims.tenant_id,
            "tenant_slug": claims.tenant_slug,
            "email": claims.email,
            "name": claims.name,
            "roles": claims.roles,
            "permissions": claims.permissions,
            "scope": claims.scope,
            "branch_ids": claims.branch_ids,
            "team_ids": claims.team_ids,
            "jti": claims.jti or str(uuid4()),
            "sid": claims.session_id,
            "mfa": claims.mfa_verified,
            "auth_time": claims.authenticated_at or int(now.timestamp()),
            "actor_type": claims.actor_type,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "iss": self._issuer,
            "aud": "airevenueos-api",
        }
        token = jwt.encode(payload, self._private, algorithm=ALGORITHM, headers={"kid": self._kid})
        return token, expires

    def decode_access_token(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._public,
                algorithms=[ALGORITHM],  # never accept alg=none or HS256
                issuer=self._issuer,
                audience="airevenueos-api",
                options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpired() from exc
        except jwt.InvalidTokenError as exc:
            raise Unauthenticated("The access token is invalid.") from exc

    def jwks(self) -> dict[str, Any]:
        public = serialization.load_pem_public_key(self._public.encode())
        if not isinstance(public, rsa.RSAPublicKey):
            raise RuntimeError("only RSA signing keys are supported; RS256 is mandated")
        numbers = public.public_numbers()

        def b64(value: int) -> str:
            import base64

            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": ALGORITHM,
                    "kid": self._kid,
                    "n": b64(numbers.n),
                    "e": b64(numbers.e),
                }
            ]
        }


# -- refresh tokens ----------------------------------------------------


def generate_refresh_token() -> tuple[str, str, str]:
    """Returns (plaintext, sha256 hash, jti). Only the hash is ever persisted."""
    jti = str(uuid4())
    secret = secrets.token_urlsafe(48)
    plaintext = f"{jti}.{secret}"
    return plaintext, hash_refresh_token(plaintext), jti


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def parse_refresh_token(plaintext: str) -> str:
    jti, _, secret = plaintext.partition(".")
    if not jti or not secret:
        raise Unauthenticated("The refresh token is malformed.")
    return jti


@dataclass(frozen=True, slots=True)
class RotationOutcome:
    accepted: bool
    reuse_detected: bool = False
    revoke_family: UUID | None = None
    reason: str | None = None


def evaluate_rotation(
    *,
    stored_hash: str | None,
    presented_hash: str,
    revoked_at: datetime | None,
    expires_at: datetime | None,
    family_id: UUID | None,
    now: datetime | None = None,
) -> RotationOutcome:
    """Reuse of an already-rotated token revokes the entire session family."""
    moment = now or utcnow()
    if stored_hash is None or stored_hash != presented_hash:
        return RotationOutcome(False, reason="unknown refresh token")
    if revoked_at is not None:
        # The token exists but was already rotated - this is replay.
        return RotationOutcome(
            False,
            reuse_detected=True,
            revoke_family=family_id,
            reason="refresh token reuse detected; the session family was revoked",
        )
    if expires_at is not None and expires_at <= moment:
        return RotationOutcome(False, reason="refresh token expired")
    return RotationOutcome(True)


def reauth_required(
    *, authenticated_at: datetime, last_activity_at: datetime, now: datetime | None = None
) -> tuple[bool, str | None]:
    moment = now or utcnow()
    if (moment - authenticated_at).total_seconds() > HARD_REAUTH_SECONDS:
        return True, "hard_reauth"
    if (moment - last_activity_at).total_seconds() > IDLE_REAUTH_SECONDS:
        return True, "idle_reauth"
    return False, None


def sessions_to_evict(
    session_ids_oldest_first: list[str], limit: int = MAX_SESSIONS_PER_USER
) -> list[str]:
    excess = len(session_ids_oldest_first) - limit + 1
    return session_ids_oldest_first[:excess] if excess > 0 else []


# -- operations requiring step-up authentication -----------------------
STEP_UP_OPERATIONS = frozenset(
    {
        "billing.update",
        "subscription.checkout",
        "export.create",
        "tenant.delete",
        "tenant.transfer_ownership",
        "api_key.create",
        "security.settings",
        "payment.refund_high_value",
        "privacy.delete",
        "user.impersonate",
    }
)


def requires_step_up(
    operation: str,
    *,
    mfa_verified: bool,
    authenticated_at: datetime,
    now: datetime | None = None,
    window_seconds: int = 900,
) -> bool:
    if operation not in STEP_UP_OPERATIONS:
        return False
    if not mfa_verified:
        return True
    return ((now or utcnow()) - authenticated_at).total_seconds() > window_seconds
