"""A published form is the widest unauthenticated write surface in the product."""

from __future__ import annotations

from typing import Any

import pytest

from domain.leads.form_schema import (
    MAX_FIELDS,
    validate_form_schema,
    validate_origins,
)
from shared.exceptions import ValidationError


def schema(*fields: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"fields": list(fields), **extra}


EMAIL = {"name": "email", "type": "email", "required": True}


class TestFieldNames:
    def test_a_valid_schema_is_normalised_with_defaults(self) -> None:
        result = validate_form_schema(schema({"name": "email", "type": "email"}))
        field = result["fields"][0]
        assert field == {
            "name": "email",
            "type": "email",
            "label": "Email",
            "required": False,
            "options": [],
            "placeholder": None,
            "help_text": None,
        }
        assert result["submit_label"] == "Submit"

    @pytest.mark.parametrize("name", ["Email", "first name", "1st", "", "e" * 51, "first-name"])
    def test_names_are_identifiers_not_labels(self, name: str) -> None:
        """Field names become payload keys and dedupe inputs."""
        with pytest.raises(ValidationError):
            validate_form_schema(schema(EMAIL, {"name": name, "type": "text"}))

    def test_platform_names_are_reserved(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            validate_form_schema(schema(EMAIL, {"name": "tenant_id", "type": "text"}))
        assert "reserved" in str(excinfo.value.details["problems"][0])

    def test_a_duplicate_name_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_form_schema(schema(EMAIL, {"name": "email", "type": "text"}))


class TestContactability:
    def test_a_form_must_capture_email_or_phone(self) -> None:
        """A lead nobody can contact looks like working software until review."""
        with pytest.raises(ValidationError) as excinfo:
            validate_form_schema(schema({"name": "message", "type": "textarea"}))
        assert "cannot be contacted" in str(excinfo.value.details["problems"][0])

    def test_phone_alone_is_enough(self) -> None:
        assert validate_form_schema(schema({"name": "phone", "type": "phone"}))["fields"]


class TestFieldTypes:
    def test_an_unknown_type_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_form_schema(schema(EMAIL, {"name": "colour", "type": "colour_picker"}))

    def test_a_select_needs_options(self) -> None:
        with pytest.raises(ValidationError):
            validate_form_schema(schema(EMAIL, {"name": "budget", "type": "select"}))

    def test_options_are_dropped_from_types_that_cannot_use_them(self) -> None:
        result = validate_form_schema(
            schema(EMAIL, {"name": "note", "type": "text", "options": ["a", "b"]})
        )
        assert result["fields"][1]["options"] == []

    def test_a_hidden_field_cannot_be_required(self) -> None:
        """The visitor cannot fill in what they cannot see."""
        with pytest.raises(ValidationError):
            validate_form_schema(
                schema(EMAIL, {"name": "utm_source", "type": "hidden", "required": True})
            )


class TestLimits:
    def test_an_empty_form_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_form_schema({"fields": []})

    def test_too_many_fields_are_refused(self) -> None:
        fields = [{"name": f"field_{i}", "type": "text"} for i in range(MAX_FIELDS + 1)]
        with pytest.raises(ValidationError):
            validate_form_schema({"fields": fields})

    def test_every_problem_is_reported_at_once(self) -> None:
        """One error per save turns a ten-field form into ten round trips."""
        with pytest.raises(ValidationError) as excinfo:
            validate_form_schema(
                schema(
                    EMAIL,
                    {"name": "Bad Name", "type": "text"},
                    {"name": "colour", "type": "colour_picker"},
                    {"name": "budget", "type": "select"},
                )
            )
        assert len(excinfo.value.details["problems"]) == 3


class TestOrigins:
    def test_a_wildcard_is_refused(self) -> None:
        """`*` would let any site embed and post to the form."""
        with pytest.raises(ValidationError):
            validate_origins(["*"])

    def test_plain_http_is_refused_except_on_localhost(self) -> None:
        with pytest.raises(ValidationError):
            validate_origins(["http://example.in"])
        assert validate_origins(["http://localhost:3000"]) == ["http://localhost:3000"]

    def test_a_url_with_a_path_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_origins(["https://example.in/contact"])

    def test_trailing_slashes_are_normalised_away(self) -> None:
        assert validate_origins(["https://example.in/"]) == ["https://example.in"]

    def test_an_empty_list_is_allowed_and_stays_empty(self) -> None:
        assert validate_origins([]) == []
