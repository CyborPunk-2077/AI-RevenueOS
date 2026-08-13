"""Origin handling is the whole authentication story for an embedded widget."""

from __future__ import annotations

import pytest

from application.communications.webchat import (
    _PUBLIC_KEY,
    MAX_MESSAGE_CHARS,
    SESSION_TTL,
    new_public_key,
    normalise_origin,
    origin_allowed,
)

ALLOWED = ["https://sharma-textiles.in", "https://www.sharma-textiles.in"]


class TestOriginNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://Example.IN", "https://example.in"),
            ("https://example.in/", "https://example.in"),
            ("https://example.in/contact?utm=1", "https://example.in"),
            ("https://example.in:8443", "https://example.in:8443"),
            (None, ""),
            ("   ", ""),
        ],
    )
    def test_scheme_host_and_port_survive_everything_else(
        self, raw: str | None, expected: str
    ) -> None:
        assert normalise_origin(raw) == expected


class TestAllowList:
    def test_a_listed_origin_is_allowed(self) -> None:
        assert origin_allowed("https://sharma-textiles.in", ALLOWED) is True

    def test_comparison_ignores_case_and_trailing_slash(self) -> None:
        assert origin_allowed("https://Sharma-Textiles.in/", ALLOWED) is True

    def test_a_subdomain_is_not_the_same_origin(self) -> None:
        """`www.` is a different origin to a browser, so it is one here too."""
        assert origin_allowed("https://shop.sharma-textiles.in", ALLOWED) is False

    def test_a_lookalike_domain_is_refused(self) -> None:
        assert origin_allowed("https://sharma-textiles.in.evil.example", ALLOWED) is False

    def test_http_is_not_https(self) -> None:
        assert origin_allowed("http://sharma-textiles.in", ALLOWED) is False

    def test_an_empty_allow_list_permits_nobody(self) -> None:
        """Fail closed: an empty list is an unfinished configuration, not consent."""
        assert origin_allowed("https://sharma-textiles.in", []) is False

    def test_a_missing_origin_header_is_refused(self) -> None:
        assert origin_allowed("", ALLOWED) is False


class TestPublicKey:
    def test_keys_are_prefixed_and_unguessable(self) -> None:
        key = new_public_key()
        assert key.startswith("wck_")
        assert len(key) == 36

    def test_two_keys_never_collide(self) -> None:
        assert len({new_public_key() for _ in range(200)}) == 200

    def test_every_generated_key_passes_the_lookup_guard(self) -> None:
        """The two halves must agree, or a widget cannot find itself.

        `_widget_by_key` refuses anything that does not match this pattern before
        it goes near the database. The pattern allowed only letters and digits
        while the generator draws from the URL-safe base64 alphabet, so a key
        containing `-` or `_` - roughly two in three of them - was rejected as
        malformed and its widget answered "not available" to its own site. Two
        hundred keys, because one is a coin toss.
        """
        assert all(_PUBLIC_KEY.match(new_public_key()) for _ in range(200))


class TestLimits:
    def test_a_visitor_session_is_short_lived(self) -> None:
        """A bearer token on a stranger's browser should not outlive the visit."""
        assert SESSION_TTL.total_seconds() <= 4 * 3600

    def test_messages_are_bounded(self) -> None:
        assert 0 < MAX_MESSAGE_CHARS <= 4_000
