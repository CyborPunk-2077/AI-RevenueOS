"""Envelope encryption: KMS master key -> tenant KEK -> per-record DEK.

AES-256-GCM with a fresh 12-byte nonce per write. KEKs rotate every 90 days and the
master key annually; ciphertext records their versions so rotation is non-breaking.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12
KEY_BYTES = 32
KEK_ROTATION_DAYS = 90
MASTER_ROTATION_DAYS = 365
VERSION_PREFIX = "v1"


class DecryptionError(ValueError):
    """Raised when ciphertext is malformed, truncated or fails authentication."""


@dataclass(frozen=True, slots=True)
class Envelope:
    ciphertext: str
    key_version: int
    tenant_id: str

    def serialize(self) -> str:
        return f"{VERSION_PREFIX}:{self.key_version}:{self.tenant_id}:{self.ciphertext}"

    @staticmethod
    def parse(value: str) -> Envelope:
        parts = value.split(":", 3)
        if len(parts) != 4 or parts[0] != VERSION_PREFIX:
            raise DecryptionError("unrecognised ciphertext envelope")
        return Envelope(parts[3], int(parts[1]), parts[2])


class EnvelopeEncryptor:
    """The master key is supplied by KMS or Secrets Manager and never persisted here."""

    def __init__(self, master_key: bytes | str) -> None:
        raw = master_key.encode() if isinstance(master_key, str) else master_key
        if len(raw) < 32:
            raise ValueError("master key must be at least 32 bytes")
        self._master = raw

    def _derive_kek(self, tenant_id: str, key_version: int) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_BYTES,
            salt=f"airevenueos:kek:{key_version}".encode(),
            info=tenant_id.encode(),
        ).derive(self._master)

    def encrypt(self, plaintext: str | bytes, *, tenant_id: str, key_version: int = 1) -> str:
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        dek = os.urandom(KEY_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        record = AESGCM(dek).encrypt(nonce, data, tenant_id.encode())

        kek_nonce = os.urandom(NONCE_BYTES)
        wrapped = AESGCM(self._derive_kek(tenant_id, key_version)).encrypt(
            kek_nonce, dek, tenant_id.encode()
        )
        blob = base64.urlsafe_b64encode(
            len(wrapped).to_bytes(2, "big") + kek_nonce + wrapped + nonce + record
        ).decode()
        return Envelope(blob, key_version, tenant_id).serialize()

    def decrypt(self, value: str, *, tenant_id: str) -> bytes:
        envelope = Envelope.parse(value)
        if envelope.tenant_id != tenant_id:
            raise DecryptionError("ciphertext belongs to a different tenant")
        try:
            raw = base64.urlsafe_b64decode(envelope.ciphertext.encode())
            wrapped_len = int.from_bytes(raw[:2], "big")
            cursor = 2
            kek_nonce = raw[cursor : cursor + NONCE_BYTES]
            cursor += NONCE_BYTES
            wrapped = raw[cursor : cursor + wrapped_len]
            cursor += wrapped_len
            nonce = raw[cursor : cursor + NONCE_BYTES]
            record = raw[cursor + NONCE_BYTES :]
            dek = AESGCM(self._derive_kek(tenant_id, envelope.key_version)).decrypt(
                kek_nonce, wrapped, tenant_id.encode()
            )
            return AESGCM(dek).decrypt(nonce, record, tenant_id.encode())
        except DecryptionError:
            raise
        except Exception as exc:
            raise DecryptionError("ciphertext could not be authenticated") from exc

    def decrypt_str(self, value: str, *, tenant_id: str) -> str:
        return self.decrypt(value, tenant_id=tenant_id).decode()

    def rotate(self, value: str, *, tenant_id: str, new_key_version: int) -> str:
        plaintext = self.decrypt(value, tenant_id=tenant_id)
        return self.encrypt(plaintext, tenant_id=tenant_id, key_version=new_key_version)


def mask_secret(value: str, *, visible: int = 4) -> str:
    """Credential lists show a mask only; the plaintext is revealed exactly once."""
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    sensitive = ("secret", "token", "key", "password", "credential")
    return {
        k: (mask_secret(str(v)) if any(s in k.lower() for s in sensitive) else v)
        for k, v in config.items()
    }
