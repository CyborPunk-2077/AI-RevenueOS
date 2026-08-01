"""Money is always integer minor units plus an ISO currency code."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

SUPPORTED = {"INR": 2, "USD": 2, "AED": 2}
DEFAULT_CURRENCY = "INR"


class MoneyError(ValueError):
    """Raised for unsupported currency or invalid amount."""


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        if self.currency not in SUPPORTED:
            raise MoneyError(f"unsupported currency {self.currency}")
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise MoneyError("amount_minor must be an integer")

    @classmethod
    def from_major(
        cls, major: str | int | float | Decimal, currency: str = DEFAULT_CURRENCY
    ) -> Money:
        if currency not in SUPPORTED:
            raise MoneyError(f"unsupported currency {currency}")
        exp = SUPPORTED[currency]
        quant = Decimal(1).scaleb(-exp)
        value = Decimal(str(major)).quantize(quant, rounding=ROUND_HALF_UP)
        return cls(int(value.scaleb(exp)), currency)

    def to_major(self) -> Decimal:
        return Decimal(self.amount_minor).scaleb(-SUPPORTED[self.currency])

    def _check(self, other: Money) -> None:
        if other.currency != self.currency:
            raise MoneyError("cannot combine different currencies")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def format(self) -> str:
        symbol = {"INR": "\u20b9", "USD": "$", "AED": "AED "}[self.currency]
        return f"{symbol}{self.to_major():,.2f}"
