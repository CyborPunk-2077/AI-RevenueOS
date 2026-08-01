"""RFC 6238 TOTP plus bcrypt-hashed recovery codes."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass

RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_BYTES = 5
TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_DRIFT_WINDOWS = 1
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_totp_secret(length: int = 20) -> str:
    raw = secrets.token_bytes(length)
    return _b32encode(raw)


def _b32encode(raw: bytes) -> str:
    bits = "".join(f"{byte:08b}" for byte in raw)
    padded = bits + "0" * (-len(bits) % 5)
    return "".join(_B32[int(padded[i : i + 5], 2)] for i in range(0, len(padded), 5))


def _b32decode(secret: str) -> bytes:
    cleaned = secret.strip().replace(" ", "").upper().rstrip("=")
    bits = "".join(f"{_B32.index(ch):05b}" for ch in cleaned if ch in _B32)
    usable = len(bits) - (len(bits) % 8)
    return bytes(int(bits[i : i + 8], 2) for i in range(0, usable, 8))


def totp_at(secret: str, counter: int) -> str:
    key = _b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def current_totp(secret: str, *, at: float | None = None) -> str:
    return totp_at(secret, int((at if at is not None else time.time()) // TOTP_PERIOD))


def verify_totp(
    secret: str, code: str, *, at: float | None = None, drift: int = TOTP_DRIFT_WINDOWS
) -> bool:
    """Constant-time comparison across a small drift window."""
    candidate = (code or "").strip().replace(" ", "")
    if not candidate.isdigit() or len(candidate) != TOTP_DIGITS:
        return False
    counter = int((at if at is not None else time.time()) // TOTP_PERIOD)
    return any(
        hmac.compare_digest(totp_at(secret, counter + offset), candidate)
        for offset in range(-drift, drift + 1)
    )


def provisioning_uri(secret: str, *, account: str, issuer: str = "AI RevenueOS") -> str:
    from urllib.parse import quote

    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )


@dataclass(frozen=True, slots=True)
class RecoveryCodes:
    plaintext: list[str]
    hashes: list[str]


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> RecoveryCodes:
    import bcrypt

    plaintext = [
        "-".join(secrets.token_hex(RECOVERY_CODE_BYTES)[i : i + 5] for i in (0, 5)).upper()
        for _ in range(count)
    ]
    hashes = [
        bcrypt.hashpw(code.encode(), bcrypt.gensalt(rounds=12)).decode() for code in plaintext
    ]
    return RecoveryCodes(plaintext, hashes)


def verify_recovery_code(code: str, hashes: list[str]) -> int | None:
    """Returns the index of the consumed code, or None. Codes are single use."""
    import bcrypt

    candidate = (code or "").strip().upper().encode()
    for index, stored in enumerate(hashes):
        try:
            if bcrypt.checkpw(candidate, stored.encode()):
                return index
        except ValueError:
            continue
    return None
