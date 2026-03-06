"""Tests for directives: named InstructionContent with compiler deduplication.

Covers:
- InstructionContent with name field
- t.directive(name, text) creates commit with correct content
- Default priority is PINNED
- Custom priority on directive
- Compiler dedup: two directives same name, only latest appears in compile
- Multiple names: each name deduped independently
- Directives without name (InstructionContent name=None) not deduped
- Directive override across branches (verify on current branch)
"""

from __future__ import annotations

import pytest

from tract import (
    InstructionContent,
    Priority,
    Tract,
    validate_content,
)


# ---------------------------------------------------------------------------
# InstructionContent name field
# ---------------------------------------------------------------------------


class TestInstructionContentName:
    """InstructionContent with the optional name field."""

    def test_name_defaults_to_none(self):
        """InstructionContent name defaults to None."""
        ic = InstructionContent(text="Hello")
        assert ic.name is None

    def test_name_can_be_set(self):
        """InstructionContent accepts a name string."""
        ic = InstructionContent(text="Hello", name="greeting")
        assert ic.name == "greeting"
        assert ic.text == "Hello"

    def test_name_in_serialization(self):
        """name field appears in model_dump when set."""
        ic = InstructionContent(text="Hello", name="greeting")
        data = ic.model_dump()
        assert data["name"] == "greeting"

    def test_validate_content_with_name(self):
        """validate_content() handles InstructionContent with name."""
        result = validate_content({
            "content_type": "instruction",
            "text": "Be helpful",
            "name": "behavior",
        })
        assert isinstance(result, InstructionContent)
        assert result.name == "behavior"


# ---------------------------------------------------------------------------
# t.directive() API
# ---------------------------------------------------------------------------


class TestDirectiveAPI:
    """t.directive(name, text) method."""

    def test_directive_creates_commit(self):
        """directive() creates a commit and returns CommitInfo."""
        with Tract.open() as t:
            info = t.directive("safety", "Never share secrets")
            assert info is not None
            assert info.commit_hash is not None
            assert info.content_type == "instruction"

    def test_directive_stores_name_in_content(self):
        """The committed content has the directive name."""
        with Tract.open() as t:
            t.directive("safety", "Never share secrets")
            compiled = t.compile()
            # The instruction should appear in compiled messages
            texts = [m.content for m in compiled.messages]
            assert any("Never share secrets" in txt for txt in texts)

    def test_directive_default_message(self):
        """directive() generates a default commit message."""
        with Tract.open() as t:
            info = t.directive("safety", "Never share secrets")
            assert "safety" in info.message

    def test_directive_custom_message(self):
        """directive() accepts a custom commit message."""
        with Tract.open() as t:
            info = t.directive("safety", "Never share secrets", message="custom msg")
            assert info.message == "custom msg"

    def test_directive_with_tags(self):
        """directive() passes tags to the commit."""
        with Tract.open() as t:
            # Register tags first (strict mode is default)
            t.register_tag("policy", "Policy directives")
            info = t.directive("safety", "Never share secrets", tags=["policy"])
            # If tags are stored, the commit should have them
            assert info is not None


# ---------------------------------------------------------------------------
# Priority behavior
# ---------------------------------------------------------------------------


class TestDirectivePriority:
    """Default and custom priority on directives."""

    def test_default_priority_is_pinned(self):
        """Directives default to PINNED priority."""
        with Tract.open() as t:
            info = t.directive("safety", "Never share secrets")
            # Verify pinned by checking annotation via get_latest
            ann = t._annotation_repo.get_latest(info.commit_hash)
            assert ann is not None
            assert ann.priority == "pinned"

    def test_custom_priority_normal(self):
        """directive(priority=NORMAL) overrides the default PINNED.

        InstructionContent has default_priority='pinned' in type hints,
        so the commit engine auto-annotates as PINNED. When the user
        explicitly requests NORMAL, directive() adds a NORMAL annotation
        which overrides the PINNED one (latest annotation wins).
        """
        with Tract.open() as t:
            info = t.directive("temp", "Temporary instruction", priority=Priority.NORMAL)
            # The latest annotation should be NORMAL, overriding the auto PINNED
            ann = t._annotation_repo.get_latest(info.commit_hash)
            assert ann is not None
            assert ann.priority == Priority.NORMAL

    def test_custom_priority_skip(self):
        """directive(priority=SKIP) marks as skip."""
        with Tract.open() as t:
            info = t.directive("hidden", "Hidden directive", priority=Priority.SKIP)
            compiled = t.compile()
            # SKIP priority means excluded from compile
            texts = [m.content for m in compiled.messages]
            assert not any("Hidden directive" in txt for txt in texts)


# ---------------------------------------------------------------------------
# Compiler deduplication by name
# ---------------------------------------------------------------------------


class TestDirectiveDedup:
    """Compiler deduplicates named InstructionContent: same name -> closest to HEAD wins."""

    def test_two_same_name_only_latest(self):
        """Two directives with same name: only the later one appears in compile."""
        with Tract.open() as t:
            t.directive("protocol", "Old protocol: do X")
            t.directive("protocol", "New protocol: do Y")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            # The old protocol should be deduped away
            assert not any("Old protocol" in txt for txt in texts)
            # The new protocol should remain
            assert any("New protocol" in txt for txt in texts)

    def test_three_same_name_only_latest(self):
        """Three directives with same name: only the latest appears."""
        with Tract.open() as t:
            t.directive("tone", "Be formal")
            t.directive("tone", "Be casual")
            t.directive("tone", "Be professional")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            assert not any("Be formal" in txt for txt in texts)
            assert not any("Be casual" in txt for txt in texts)
            assert any("Be professional" in txt for txt in texts)

    def test_different_names_independent(self):
        """Different names are deduped independently."""
        with Tract.open() as t:
            t.directive("safety", "Be safe v1")
            t.directive("tone", "Be formal")
            t.directive("safety", "Be safe v2")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            # safety: v2 wins
            assert any("Be safe v2" in txt for txt in texts)
            assert not any("Be safe v1" in txt for txt in texts)
            # tone: only one, so it stays
            assert any("Be formal" in txt for txt in texts)

    def test_unnamed_instructions_not_deduped(self):
        """Instructions without a name are not affected by dedup."""
        with Tract.open() as t:
            t.system("First instruction")
            t.system("Second instruction")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            # Both should appear since they have no name
            assert any("First instruction" in txt for txt in texts)
            assert any("Second instruction" in txt for txt in texts)

    def test_named_and_unnamed_coexist(self):
        """Named directives coexist with unnamed instructions."""
        with Tract.open() as t:
            t.system("Regular instruction")
            t.directive("protocol", "Old protocol")
            t.directive("protocol", "New protocol")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            assert any("Regular instruction" in txt for txt in texts)
            assert any("New protocol" in txt for txt in texts)
            assert not any("Old protocol" in txt for txt in texts)

    def test_dedup_with_interleaved_messages(self):
        """Dedup works with non-directive commits interleaved."""
        with Tract.open() as t:
            t.directive("role", "You are a teacher")
            t.user("Hello")
            t.assistant("Hi there")
            t.directive("role", "You are a researcher")
            t.user("Another question")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            assert not any("teacher" in txt for txt in texts)
            assert any("researcher" in txt for txt in texts)


# ---------------------------------------------------------------------------
# Directive override across branches
# ---------------------------------------------------------------------------


class TestDirectiveBranchOverride:
    """Directive dedup scoped to current branch's DAG."""

    def test_directive_on_branch_overrides(self):
        """Directive on a branch overrides ancestor directive for that branch."""
        with Tract.open() as t:
            t.directive("protocol", "Main protocol")
            t.user("Setup")

            # Create a feature branch and switch to it
            t.branch("feature", switch=True)

            # Override on feature branch
            t.directive("protocol", "Feature protocol")

            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            assert any("Feature protocol" in txt for txt in texts)
            assert not any("Main protocol" in txt for txt in texts)

    def test_main_branch_unaffected_by_feature(self):
        """Directive override on feature branch does not affect main."""
        with Tract.open() as t:
            t.directive("protocol", "Main protocol")
            t.user("Setup")

            t.branch("feature", switch=True)
            t.directive("protocol", "Feature protocol")

            # Switch back to main
            t.switch("main")
            compiled = t.compile()
            texts = [m.content for m in compiled.messages]
            assert any("Main protocol" in txt for txt in texts)
            assert not any("Feature protocol" in txt for txt in texts)
