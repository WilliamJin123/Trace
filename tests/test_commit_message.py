"""Tests for tract.prompts.commit_message -- prompt construction for auto-commit messages.

Covers:
- COMMIT_MESSAGE_SYSTEM constant content
- _MAX_INPUT_CHARS truncation threshold
- build_commit_message_prompt: normal, empty, exact-boundary, and over-limit inputs
"""

from __future__ import annotations

from tract.prompts.commit_message import (
    COMMIT_MESSAGE_SYSTEM,
    _MAX_INPUT_CHARS,
    build_commit_message_prompt,
)


# ---------------------------------------------------------------------------
# COMMIT_MESSAGE_SYSTEM constant
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_is_string(self):
        assert isinstance(COMMIT_MESSAGE_SYSTEM, str)

    def test_instructs_concise_commit_messages(self):
        assert "one-sentence" in COMMIT_MESSAGE_SYSTEM.lower()

    def test_instructs_verb_start(self):
        assert "verb" in COMMIT_MESSAGE_SYSTEM.lower()

    def test_instructs_return_only_message(self):
        assert "ONLY" in COMMIT_MESSAGE_SYSTEM


# ---------------------------------------------------------------------------
# _MAX_INPUT_CHARS threshold
# ---------------------------------------------------------------------------

class TestMaxInputChars:
    def test_value(self):
        assert _MAX_INPUT_CHARS == 2000

    def test_is_int(self):
        assert isinstance(_MAX_INPUT_CHARS, int)


# ---------------------------------------------------------------------------
# build_commit_message_prompt -- normal cases
# ---------------------------------------------------------------------------

class TestBuildPromptNormal:
    def test_contains_content_type(self):
        result = build_commit_message_prompt("dialogue", "Hello world")
        assert "Content type: dialogue" in result

    def test_contains_text(self):
        result = build_commit_message_prompt("instruction", "Do this task")
        assert "Do this task" in result

    def test_contains_generation_instruction(self):
        result = build_commit_message_prompt("note", "some note")
        assert "one-sentence commit message" in result

    def test_short_text_not_truncated(self):
        text = "Short text"
        result = build_commit_message_prompt("dialogue", text)
        assert text in result
        assert "..." not in result

    def test_different_content_types(self):
        for ct in ("dialogue", "instruction", "tool_result", "custom_type"):
            result = build_commit_message_prompt(ct, "x")
            assert f"Content type: {ct}" in result


# ---------------------------------------------------------------------------
# build_commit_message_prompt -- truncation
# ---------------------------------------------------------------------------

class TestBuildPromptTruncation:
    def test_text_at_exact_limit_not_truncated(self):
        text = "a" * _MAX_INPUT_CHARS
        result = build_commit_message_prompt("dialogue", text)
        assert text in result
        assert "..." not in result

    def test_text_one_over_limit_is_truncated(self):
        text = "b" * (_MAX_INPUT_CHARS + 1)
        result = build_commit_message_prompt("dialogue", text)
        # Should contain exactly _MAX_INPUT_CHARS 'b' chars followed by "..."
        assert "b" * _MAX_INPUT_CHARS + "..." in result
        # The extra character must NOT appear
        assert "b" * (_MAX_INPUT_CHARS + 1) not in result

    def test_very_long_text_is_truncated(self):
        text = "z" * 10_000
        result = build_commit_message_prompt("dialogue", text)
        assert "..." in result
        # Only _MAX_INPUT_CHARS 'z' chars should survive (prefix has none)
        z_count = result.count("z")
        assert z_count == _MAX_INPUT_CHARS


# ---------------------------------------------------------------------------
# build_commit_message_prompt -- edge cases
# ---------------------------------------------------------------------------

class TestBuildPromptEdgeCases:
    def test_empty_text(self):
        result = build_commit_message_prompt("dialogue", "")
        assert "Content type: dialogue" in result
        # No truncation marker on empty string
        assert "..." not in result

    def test_empty_content_type(self):
        result = build_commit_message_prompt("", "some text")
        assert "Content type: " in result
        assert "some text" in result

    def test_text_with_newlines(self):
        text = "line1\nline2\nline3"
        result = build_commit_message_prompt("dialogue", text)
        assert "line1\nline2\nline3" in result

    def test_text_with_special_characters(self):
        text = 'He said "hello" & <goodbye>'
        result = build_commit_message_prompt("dialogue", text)
        assert text in result

    def test_unicode_text(self):
        text = "Hello world"
        result = build_commit_message_prompt("dialogue", text)
        assert text in result

    def test_return_type_is_str(self):
        result = build_commit_message_prompt("dialogue", "hi")
        assert isinstance(result, str)

    def test_truncation_boundary_with_multibyte(self):
        """Truncation is character-based, not byte-based."""
        # 2000 multi-byte chars should NOT be truncated
        text = "x" * _MAX_INPUT_CHARS
        result = build_commit_message_prompt("dialogue", text)
        assert "..." not in result
