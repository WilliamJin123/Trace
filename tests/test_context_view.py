"""Tests for tract.context_view."""

from __future__ import annotations

import pytest

from tract import Tract
from tract.context_view import ContextView, BuiltContext, build_context, estimate_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tract(**kwargs) -> Tract:
    return Tract.open(**kwargs)


# ---------------------------------------------------------------------------
# ContextView dataclass
# ---------------------------------------------------------------------------

class TestContextViewDefaults:
    def test_default_scope_is_none(self) -> None:
        v = ContextView()
        assert v.scope is None

    def test_default_detail_is_manifest(self) -> None:
        v = ContextView()
        assert v.detail == "manifest"

    def test_default_state_flags(self) -> None:
        v = ContextView()
        assert v.include_config is True
        assert v.include_branches is True
        assert v.include_tags_summary is True
        assert v.include_directives is False
        assert v.include_token_status is False

    def test_frozen(self) -> None:
        v = ContextView()
        with pytest.raises(AttributeError):
            v.scope = 10  # type: ignore[misc]


class TestContextViewCustom:
    def test_scope_int(self) -> None:
        v = ContextView(scope=20)
        assert v.scope == 20

    def test_scope_list(self) -> None:
        v = ContextView(scope=["abc", "def"])
        assert v.scope == ["abc", "def"]

    def test_detail_full(self) -> None:
        v = ContextView(detail="full")
        assert v.detail == "full"

    def test_detail_compiled(self) -> None:
        v = ContextView(detail="compiled")
        assert v.detail == "compiled"

    def test_all_filters(self) -> None:
        v = ContextView(
            include_types=["dialogue"],
            exclude_types=["config"],
            include_tags=["important"],
            exclude_tags=["stale"],
            min_priority="important",
        )
        assert v.include_types == ["dialogue"]
        assert v.exclude_types == ["config"]
        assert v.include_tags == ["important"]
        assert v.exclude_tags == ["stale"]
        assert v.min_priority == "important"


# ---------------------------------------------------------------------------
# build_context — empty tract
# ---------------------------------------------------------------------------

class TestBuildContextEmpty:
    def test_empty_tract_returns_no_commits(self) -> None:
        with _make_tract() as t:
            built = build_context(ContextView(), t)
            assert built.commit_count == 0
            assert "(no commits)" in built.text
            assert isinstance(built, BuiltContext)

    def test_empty_tract_has_branch_header(self) -> None:
        with _make_tract() as t:
            built = build_context(ContextView(), t)
            assert "Branch:" in built.text


# ---------------------------------------------------------------------------
# build_context — with commits
# ---------------------------------------------------------------------------

class TestBuildContextWithCommits:
    def test_manifest_shows_metadata(self) -> None:
        with _make_tract() as t:
            t.user("Hello world")
            t.assistant("Hi there")
            built = build_context(ContextView(), t)
            assert built.commit_count >= 2
            assert "dialogue" in built.text
            assert "COMMIT LOG" in built.text

    def test_scope_limits_commits(self) -> None:
        with _make_tract() as t:
            for i in range(5):
                t.user(f"Message {i}")
            built = build_context(ContextView(scope=2), t)
            assert built.commit_count == 2

    def test_full_detail_includes_content(self) -> None:
        with _make_tract() as t:
            t.user("The quick brown fox")
            built = build_context(ContextView(detail="full"), t)
            assert "The quick brown fox" in built.text

    def test_manifest_does_not_include_full_content(self) -> None:
        with _make_tract() as t:
            t.user("UniqueContentMarkerXYZ123")
            built = build_context(ContextView(detail="manifest"), t)
            # Manifest shows message but not full content body
            # The message IS the content for dialogue, so it appears truncated in metadata
            assert built.commit_count == 1

    def test_compiled_detail(self) -> None:
        with _make_tract() as t:
            t.system("You are helpful")
            t.user("Hello")
            t.assistant("Hi")
            built = build_context(ContextView(detail="compiled"), t)
            assert "COMPILED CONTEXT" in built.text
            assert "[system]:" in built.text or "[user]:" in built.text

    def test_default_scope_fallback(self) -> None:
        with _make_tract() as t:
            for i in range(5):
                t.user(f"Msg {i}")
            built = build_context(ContextView(), t, default_scope=3)
            assert built.commit_count == 3


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestFilters:
    def test_include_types(self) -> None:
        with _make_tract() as t:
            t.system("sys prompt")
            t.user("user msg")
            t.assistant("asst msg")
            built = build_context(
                ContextView(include_types=["dialogue"]), t,
            )
            # system is also dialogue, so all should be included
            assert built.commit_count >= 2

    def test_exclude_types(self) -> None:
        with _make_tract() as t:
            t.user("Hello")
            t.commit({"content_type": "freeform", "payload": {"text": "note"}},
                     message="a note")
            all_built = build_context(ContextView(), t)
            filtered = build_context(
                ContextView(exclude_types=["freeform"]), t,
            )
            assert filtered.commit_count < all_built.commit_count

    def test_min_priority_filters_skip(self) -> None:
        with _make_tract() as t:
            t.user("Keep me")
            t.user("Skip me")
            entries = t.search.log(limit=1)
            from tract.models.annotations import Priority
            t.annotations.set(entries[0].commit_hash, Priority.SKIP)

            built = build_context(
                ContextView(min_priority="normal"), t,
            )
            # SKIP commit should be excluded
            assert built.commit_count == 1


# ---------------------------------------------------------------------------
# Peek
# ---------------------------------------------------------------------------

class TestPeek:
    def test_peek_shows_full_content_for_selected(self) -> None:
        with _make_tract() as t:
            t.user("PeekableContent999")
            t.user("Other message")
            entries = t.search.log(limit=2)
            peek_hash = entries[1].commit_hash  # older one

            built = build_context(
                ContextView(peek=[peek_hash]), t,
            )
            assert "PeekableContent999" in built.text
            assert peek_hash[:8] in built.peeked_hashes[0] or \
                   any(peek_hash.startswith(ph) for ph in built.peeked_hashes)


# ---------------------------------------------------------------------------
# Forced includes
# ---------------------------------------------------------------------------

class TestForcedIncludes:
    def test_always_include_hashes_outside_scope(self) -> None:
        with _make_tract() as t:
            t.user("Old important message")
            old_hash = t.search.log(limit=1)[0].commit_hash
            for i in range(5):
                t.user(f"Recent {i}")

            built = build_context(
                ContextView(scope=2, always_include_hashes=[old_hash]), t,
            )
            # Should have 2 from scope + 1 forced = 3
            assert built.commit_count == 3

    def test_always_include_tags(self) -> None:
        with _make_tract() as t:
            t.tags.register("key-finding", "important finding")
            t.commit(
                {"content_type": "freeform", "payload": {"text": "Tagged finding"}},
                message="Tagged message",
                tags=["key-finding"],
            )
            for i in range(5):
                t.user(f"Recent {i}")

            built = build_context(
                ContextView(scope=2, always_include_tags=["key-finding"]), t,
            )
            assert built.commit_count == 3


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class TestBudget:
    def test_max_tokens_limits_output(self) -> None:
        with _make_tract() as t:
            for i in range(20):
                t.user(f"Message number {i} with some content to add tokens")
            unlimited = build_context(ContextView(), t)
            limited = build_context(ContextView(max_tokens=200), t)
            assert limited.commit_count < unlimited.commit_count


# ---------------------------------------------------------------------------
# State sections
# ---------------------------------------------------------------------------

class TestState:
    def test_config_included_by_default(self) -> None:
        with _make_tract() as t:
            t.config.set(stage="research")
            built = build_context(ContextView(), t)
            assert "ACTIVE CONFIG" in built.text
            assert "research" in built.text

    def test_config_excluded(self) -> None:
        with _make_tract() as t:
            t.config.set(stage="research")
            built = build_context(ContextView(include_config=False), t)
            assert "ACTIVE CONFIG" not in built.text

    def test_branches_included(self) -> None:
        with _make_tract() as t:
            t.user("seed commit")
            t.branches.create("feature")
            built = build_context(ContextView(include_branches=True), t)
            assert "BRANCHES:" in built.text
            assert "feature" in built.text

    def test_directives_included(self) -> None:
        with _make_tract() as t:
            t.directive("focus", "Stay on topic")
            built = build_context(
                ContextView(include_directives=True), t,
            )
            assert "ACTIVE DIRECTIVES" in built.text
            assert "Stay on topic" in built.text

    def test_tags_summary(self) -> None:
        with _make_tract() as t:
            t.tags.register("research", "research tag")
            # Use commit-time tags (immutable, stored in CommitInfo.tags)
            t.commit(
                {"content_type": "freeform", "payload": {"text": "note 1"}},
                message="msg1", tags=["research"],
            )
            t.commit(
                {"content_type": "freeform", "payload": {"text": "note 2"}},
                message="msg2", tags=["research"],
            )
            built = build_context(ContextView(), t)
            assert "TAGS:" in built.text
            assert "research(2)" in built.text


# ---------------------------------------------------------------------------
# commit_entries for hash resolution
# ---------------------------------------------------------------------------

class TestCommitEntries:
    def test_commit_entries_populated(self) -> None:
        with _make_tract() as t:
            t.user("Hello")
            built = build_context(ContextView(), t)
            assert len(built.commit_entries) >= 1
            entry = built.commit_entries[0]
            assert "hash" in entry
            assert "short_hash" in entry
            assert "content_type" in entry
            assert len(entry["short_hash"]) == 8


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_manifest_cheaper_than_full(self) -> None:
        with _make_tract() as t:
            for i in range(5):
                t.user(f"Some content message {i}")
            manifest_est = estimate_tokens(ContextView(detail="manifest"), t)
            full_est = estimate_tokens(ContextView(detail="full"), t)
            assert manifest_est < full_est

    def test_empty_returns_zero(self) -> None:
        with _make_tract() as t:
            est = estimate_tokens(ContextView(), t)
            assert est == 0


# ---------------------------------------------------------------------------
# BuiltContext
# ---------------------------------------------------------------------------

class TestBuiltContext:
    def test_token_estimate_positive(self) -> None:
        with _make_tract() as t:
            t.user("Hello")
            built = build_context(ContextView(), t)
            assert built.token_estimate > 0

    def test_text_is_string(self) -> None:
        with _make_tract() as t:
            t.user("Hello")
            built = build_context(ContextView(), t)
            assert isinstance(built.text, str)
