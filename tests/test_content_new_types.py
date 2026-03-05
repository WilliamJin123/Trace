"""Tests for RuleContent, MetadataContent, and the compilable flag.

Covers:
- RuleContent creation, validation, immutability, and content_type literal
- MetadataContent creation, defaults, and validation
- ContentTypeHints.compilable flag for built-in types
- Rule and metadata commits excluded from compile output
"""

import pytest

from tract import Tract
from tract.exceptions import ContentValidationError
from tract.models.content import (
    BUILTIN_CONTENT_TYPES,
    BUILTIN_TYPE_HINTS,
    ContentTypeHints,
    MetadataContent,
    RuleContent,
    validate_content,
)


# ---------------------------------------------------------------------------
# RuleContent
# ---------------------------------------------------------------------------


class TestRuleContent:
    def test_creation_all_fields(self):
        """RuleContent with all fields validates."""
        r = RuleContent(
            name="auto_compress",
            trigger="commit",
            condition={"type": "threshold", "metric": "total_tokens", "op": ">", "value": 8000},
            action={"type": "operation", "op": "compress"},
        )
        assert r.name == "auto_compress"
        assert r.trigger == "commit"
        assert r.condition is not None
        assert r.action["type"] == "operation"

    def test_creation_minimal(self):
        """RuleContent with only required fields (condition=None)."""
        r = RuleContent(
            name="temp",
            trigger="active",
            action={"type": "set_config", "key": "temperature", "value": 0.3},
        )
        assert r.condition is None

    def test_content_type_literal(self):
        """content_type is always 'rule'."""
        r = RuleContent(name="x", trigger="active", action={"type": "set_config"})
        assert r.content_type == "rule"

    def test_frozen(self):
        """RuleContent is immutable (frozen model)."""
        r = RuleContent(name="x", trigger="active", action={"type": "set_config"})
        with pytest.raises(Exception):
            r.name = "y"

    def test_validate_content(self):
        """RuleContent validates through validate_content()."""
        data = {
            "content_type": "rule",
            "name": "x",
            "trigger": "active",
            "action": {"type": "set_config"},
        }
        result = validate_content(data)
        assert isinstance(result, RuleContent)

    def test_missing_required_field(self):
        """RuleContent without 'name' raises ContentValidationError."""
        with pytest.raises(ContentValidationError):
            validate_content({
                "content_type": "rule",
                "trigger": "active",
                "action": {"type": "set_config"},
            })

    def test_round_trip(self):
        """RuleContent survives model_dump -> model_validate."""
        r = RuleContent(
            name="test_rule",
            trigger="commit",
            condition={"x": 1},
            action={"type": "noop"},
        )
        dumped = r.model_dump()
        restored = RuleContent.model_validate(dumped)
        assert restored == r


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

    def test_rule_not_compilable(self):
        """Rule type hint has compilable=False."""
        assert BUILTIN_TYPE_HINTS["rule"].compilable is False

    def test_metadata_not_compilable(self):
        """Metadata type hint has compilable=False."""
        assert BUILTIN_TYPE_HINTS["metadata"].compilable is False

    def test_instruction_compilable(self):
        """Instruction type hint has compilable=True (default)."""
        assert BUILTIN_TYPE_HINTS["instruction"].compilable is True

    def test_dialogue_compilable(self):
        """Dialogue type hint has compilable=True (default)."""
        assert BUILTIN_TYPE_HINTS["dialogue"].compilable is True

    def test_rule_in_builtin_set(self):
        """'rule' is in the BUILTIN_CONTENT_TYPES set."""
        assert "rule" in BUILTIN_CONTENT_TYPES

    def test_metadata_in_builtin_set(self):
        """'metadata' is in the BUILTIN_CONTENT_TYPES set."""
        assert "metadata" in BUILTIN_CONTENT_TYPES


# ---------------------------------------------------------------------------
# Non-compilable commits excluded from compile output
# ---------------------------------------------------------------------------


class TestRuleNotCompiled:
    """Rule commits should be excluded from compile output."""

    def test_rule_excluded_from_compile(self):
        """A rule commit should not appear in compiled messages."""
        t = Tract.open()
        t.user("Hello")
        t.commit({
            "content_type": "rule",
            "name": "temp",
            "trigger": "active",
            "action": {"type": "set_config", "key": "temperature", "value": 0.3},
        })
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

    def test_rule_not_counted_in_commit_count(self):
        """Rule commits should not be counted in compiled commit_count."""
        t = Tract.open()
        t.user("Hello")
        t.commit({
            "content_type": "rule",
            "name": "r1",
            "trigger": "active",
            "action": {"type": "noop"},
        })
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
