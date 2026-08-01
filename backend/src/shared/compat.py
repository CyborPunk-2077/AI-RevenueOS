"""Small compatibility shims. Target runtime is Python 3.12; 3.10 stays importable."""

from __future__ import annotations

import enum
import sys

if sys.version_info >= (3, 11):
    StrEnum = enum.StrEnum
else:  # pragma: no cover - 3.10 developer machines and CI matrix legs

    class StrEnum(str, enum.Enum):  # type: ignore[no-redef]
        def __str__(self) -> str:
            return str(self.value)


__all__ = ["StrEnum"]
