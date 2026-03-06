"""Tests for ConfigContent, MetadataContent, and the compilable flag.

Covers:
- ConfigContent creation, validation, immutability, and content_type literal
- MetadataContent creation, defaults, and validation
- ContentTypeHints.compilable flag for built-in types
- Config and metadata commits excluded from compile output
"""

import pytest

from tract import Tract
from tract.exceptions import ContentValidationError
from tract.models.content import (
    BUILTIN_CONTENT_TYPES,
    BUILTIN_TYPE_HINTS,
    ContentTypeHints,
    ConfigContent,
    MetadataContent,
    validate_content,
)


# ---------------------------------------------------------------------------
# ConfigContent
# ---------------------------------------------------------------------------


class TestConfigContent:
    def test_creation_all_fields(self):
        """ConfigContent with settings dict validates."""
        c = ConfigContent(
            settings={"model": "gpt-4o", "temperature": 0.7, "max_tokens": 8000},
        )
        assert c.settings["model"] == "gpt-4o"
        assert c.settings["temperature"] == 0.7
        assert c.settings["max_tokens"] == 8000

    def test_creation_minimal(self):
        """ConfigContent with a single key-value setting."""
        c = ConfigContent(settings={"temperature": 0.3})
        assert c.settings == {"temperature": 0.3}

    def test_content_type_literal(self):
        """content_type is always 'config'."""
        c = ConfigContent(settings={"key": "value"})
        assert c.content_type == "config"

    def test_frozen(self):
        """ConfigContent is immutable (frozen model)."""
        c = ConfigContent(settings={"key": "value"})
        with pytest.raises(Exception):
            c.settings = {"other": "value"}

    def test_validate_content(self):
        """ConfigContent validates through validate_content()."""
        data = {
            "content_type": "config",
            "settings": {"model": "gpt-4o"},
        }
        result = validate_content(data)
        assert isinstance(result, ConfigContent)

    def test_missing_required_field(self):
        """ConfigContent without 'settings' raises ContentValidationError."""
        with pytest.raises(ContentValidationError):
            validate_content({
                "content_type": "config",
            })

    def test_round_trip(self):
        """ConfigContent survives model_dump -> model_validate."""
        c = ConfigContent(
            settings={"model": "gpt-4o", "temperature": 0.5},
        )
        dumped = c.model_dump()
        restored = ConfigContent.model_validate(dumped)
        assert restored == c


# ---------------------------------------------------------------------------
# MetadataContent
# ---------------------------------------------------------------------------


class TestMetadataContent:
    def test_creation_with_dict_data(self):
        """MetadataContent with explicit data dict."""
        m = MetadataContent(kind="tag", data={"key": "value"})
        assert m.kind == "tag"
        assert m.data == {"key": "value"}

    def test_creation_default_data(self):
        """MetadataContent defaults data to empty dict."""
        m = MetadataContent(kind="marker")
        assert m.data == {}

    def test_creation_with_path(self):
        """MetadataContent with optional path."""
        m = MetadataContent(kind="artifact_ref", data={"file": "out.md"}, path="/outputs/out.md")
        assert m.path == "/outputs/out.md"

    def test_no_path_default(self):
        """MetadataContent path defaults to None."""
        m = MetadataContent(kind="tag")
        assert m.path is None

    def test_content_type_literal(self):
        """content_type is always 'metadata'."""
        m = MetadataContent(kind="x")
        assert m.content_type == "metadata"

    def test_validate_content(self):
        """MetadataContent validates through validate_content()."""
        data = {"content_type": "metadata", "kind": "tag", "data": {"k": "v"}}
        result = validate_content(data)
        assert isinstance(result, MetadataContent)

    def test_round_trip(self):
        """MetadataContent survives model_dump -> model_validate."""
        m = MetadataContent(kind="artifact_ref", data={"a": 1}, path="/x")
        dumped = m.model_dump()
        restored = MetadataContent.model_validate(dumped)
        assert restored == m


# ---------------------------------------------------------------------------
# Compilable flag
# ---------------------------------------------------------------------------


class TestCompilableFlag:
    def test_compilable_defaults_true(self):
        """ContentTypeHints.compilable defaults to True."""
        assert ContentTypeHints().compilable is True

    def test_config_not_compilable(self):
        """Config type hint has compilable=False."""
        assert BUILTIN_TYPE_HINTS["config"].compilable is False

    def test_metadata_not_compilable(self):
        """Metadata type hint has compilable=False."""
        assert BUILTIN_TYPE_HINTS["metadata"].compilable is False

    def test_instruction_compilable(self):
        """Instruction type hint has compilable=True (default)."""
        assert BUILTIN_TYPE_HINTS["instruction"].compilable is True

    def test_dialogue_compilable(self):
        """Dialogue type hint has compilable=True (default)."""
        assert BUILTIN_TYPE_HINTS["dialogue"].compilable is True

    def test_config_in_builtin_set(self):
        """'config' is in the BUILTIN_CONTENT_TYPES set."""
        assert "config" in BUILTIN_CONTENT_TYPES

    def test_metadata_in_builtin_set(self):
        """'metadata' is in the BUILTIN_CONTENT_TYPES set."""
        assert "metadata" in BUILTIN_CONTENT_TYPES


# ---------------------------------------------------------------------------
# Non-compilable commits excluded from compile output
# ---------------------------------------------------------------------------


class TestConfigNotCompiled:
    """Config commits should be excluded from compile output."""

    def test_config_excluded_from_compile(self):
        """A config commit should not appear in compiled messages."""
        t = Tract.open()
        t.user("Hello")
        t.configure(temperature=0.3)
        t.assistant("World")
        compiled = t.compile()
        # Should have 2 messages (user + assistant), NOT 3
        texts = [m.content for m in compiled.messages]
        assert "Hello" in texts
        assert "World" in texts
        assert len(compiled.messages) == 2

    def test_metadata_excluded_from_compile(self):
        """A metadata commit should not appear in compiled messages."""
        t = Tract.open()
        t.user("Hello")
        t.commit({
            "content_type": "metadata",
            "kind": "tag",
            "data": {"important": True},
        })
        t.assistant("World")
        compiled = t.compile()
        assert len(compiled.messages) == 2

    def test_config_not_counted_in_commit_count(self):
        """Config commits should not be counted in compiled commit_count."""
        t = Tract.open()
        t.user("Hello")
        t.configure(model="gpt-4o")
        t.assistant("World")
        compiled = t.compile()
        assert compiled.commit_count == 2

    def test_metadata_not_counted_in_commit_count(self):
        """Metadata commits should not be counted in compiled commit_count."""
        t = Tract.open()
        t.user("First")
        t.commit({
            "content_type": "metadata",
            "kind": "marker",
            "data": {"step": 1},
        })
        t.user("Second")
        compiled = t.compile()
        assert compiled.commit_count == 2
