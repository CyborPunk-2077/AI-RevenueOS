"""UUIDv7 generation (RFC 9562) - time ordered primary keys for every table."""

from __future__ import annotations

import os
import time
from uuid import UUID

_UUID7_VARIANT = 0b10


def uuid7(when_ms: int | None = None) -> UUID:
    """Generate a UUIDv7: 48-bit unix millisecond timestamp + 74 bits of randomness."""
    ts = when_ms if when_ms is not None else int(time.time() * 1000)
    if ts < 0 or ts >= (1 << 48):
        raise ValueError("timestamp out of range for UUIDv7")
    rand = os.urandom(10)
    rand_a = int.from_bytes(rand[:2], "big") & 0x0FFF
    rand_b = int.from_bytes(rand[2:], "big") & ((1 << 62) - 1)
    value = (ts << 80) | (0x7 << 76) | (rand_a << 64) | (_UUID7_VARIANT << 62) | rand_b
    return UUID(int=value)


def uuid7_timestamp_ms(value: UUID) -> int:
    """Extract the embedded millisecond timestamp from a UUIDv7."""
    if value.version != 7:
        raise ValueError("not a UUIDv7")
    return value.int >> 80
