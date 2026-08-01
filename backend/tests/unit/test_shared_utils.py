"""Utilities carry the highest coverage bar (95/90) because everything depends on them."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from shared.utils.ids import uuid7, uuid7_timestamp_ms
from shared.utils.money import Money, MoneyError
from shared.utils.phone import InvalidPhone, mask_phone, normalize_phone, try_normalize_phone
from shared.utils.text import (
    canonical_json,
    content_hash,
    is_reserved_slug,
    normalize_email,
    normalize_name_key,
    slugify,
)
from shared.utils.timeutil import (
    UTC,
    ensure_utc,
    iso,
    local_day_bounds,
    resolve_local_instant,
    to_local,
)

UTC = UTC


class TestUuid7:
    def test_version_and_variant(self) -> None:
        value = uuid7()
        assert value.version == 7
        assert (value.int >> 62) & 0b11 == 0b10

    def test_is_time_ordered(self) -> None:
        values = [uuid7(when_ms=1_700_000_000_000 + i) for i in range(50)]
        assert values == sorted(values)

    def test_timestamp_roundtrip(self) -> None:
        assert uuid7_timestamp_ms(uuid7(when_ms=1_712_345_678_901)) == 1_712_345_678_901

    def test_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            uuid7(when_ms=-1)

    def test_uniqueness_under_same_millisecond(self) -> None:
        batch = {uuid7(when_ms=1_700_000_000_000) for _ in range(2_000)}
        assert len(batch) == 2_000


class TestIndianPhone:
    @pytest.mark.parametrize(
        "raw",
        [
            "9876543210",
            "+919876543210",
            "09876543210",
            "919876543210",
            "+91 98765 43210",
            "+91-98765-43210",
            "0091 9876543210",
        ],
    )
    def test_accepts_valid_indian_forms(self, raw: str) -> None:
        assert normalize_phone(raw) == "+919876543210"

    @pytest.mark.parametrize("raw", ["5876543210", "123", "98765432101", "abcdefghij", "+91123"])
    def test_rejects_invalid(self, raw: str) -> None:
        with pytest.raises(InvalidPhone):
            normalize_phone(raw)

    def test_international_passthrough(self) -> None:
        assert normalize_phone("+971501234567") == "+971501234567"

    def test_try_normalize_is_total(self) -> None:
        assert try_normalize_phone("garbage") is None
        assert try_normalize_phone(None) is None
        assert try_normalize_phone("9876543210") == "+919876543210"

    def test_mask_keeps_last_four_only(self) -> None:
        masked = mask_phone("+919876543210")
        assert masked.endswith("3210")
        assert "98765" not in masked


class TestMoney:
    def test_minor_unit_construction(self) -> None:
        assert Money.from_major("1234.56").amount_minor == 123_456
        assert Money.from_major(Decimal("0.005")).amount_minor == 1  # half-up

    def test_arithmetic_and_currency_guard(self) -> None:
        assert (Money(100) + Money(250)).amount_minor == 350
        with pytest.raises(MoneyError):
            Money(100) + Money(100, "USD")

    def test_rejects_unsupported_currency_and_float_amount(self) -> None:
        with pytest.raises(MoneyError):
            Money(100, "XXX")
        with pytest.raises(MoneyError):
            Money(True)  # type: ignore[arg-type]

    def test_format_uses_rupee_symbol(self) -> None:
        assert Money.from_major("50000").format() == "\u20b950,000.00"


class TestText:
    def test_slugify_and_reserved(self) -> None:
        assert slugify("Sharma & Co. Realty Pvt Ltd") == "sharma-co-realty-pvt-ltd"
        assert is_reserved_slug("api") is True
        with pytest.raises(ValueError):
            slugify("!!!")

    def test_email_normalisation(self) -> None:
        assert normalize_email("  Asha@Example.IN ") == "asha@example.in"
        with pytest.raises(ValueError):
            normalize_email("not-an-email")

    def test_name_key_is_diacritic_insensitive(self) -> None:
        assert normalize_name_key("Ravi  Shankar") == normalize_name_key("RAVI SHANKAR")

    def test_canonical_json_is_order_and_whitespace_stable(self) -> None:
        a = {"b": 1, "a": {"y": [1, 2], "x": "caf\u00e9"}}
        b = {"a": {"x": "cafe\u0301", "y": [1, 2]}, "b": 1.0}
        assert canonical_json(a) == canonical_json(b)
        assert content_hash(a) == content_hash(b)


class TestTimeUtilities:
    def test_naive_datetimes_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            ensure_utc(datetime(2026, 1, 1, 12, 0))

    def test_local_day_bounds_for_kolkata(self) -> None:
        start, end = local_day_bounds(date(2026, 8, 1), "Asia/Kolkata")
        assert start == datetime(2026, 7, 31, 18, 30, tzinfo=UTC)
        assert end - start == timedelta(days=1)

    def test_dst_spring_forward_moves_to_next_valid_instant(self) -> None:
        # 02:30 on 2026-03-08 does not exist in America/New_York.
        resolved = resolve_local_instant(date(2026, 3, 8), time(2, 30), "America/New_York")
        assert to_local(resolved, "America/New_York").hour == 3

    def test_dst_fall_back_uses_later_occurrence(self) -> None:
        resolved = resolve_local_instant(date(2026, 11, 1), time(1, 30), "America/New_York")
        assert to_local(resolved, "America/New_York").utcoffset() == timedelta(hours=-5)

    def test_iso_renders_zulu(self) -> None:
        assert iso(datetime(2026, 8, 1, 6, 30, tzinfo=UTC)) == "2026-08-01T06:30:00Z"
