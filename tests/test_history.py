"""Tests for history operations -- StatusInfo dataclass and status queries.

Tests the StatusInfo dataclass from tract.operations.history and how it
integrates with Tract.status() across different tract states.
"""

from __future__ import annotations

import pytest

from tract import (
    DialogueContent,
    InstructionContent,
    StatusInfo,
    Tract,
    TractConfig,
    TokenBudgetConfig,
)
from tests.conftest import make_tract, populate_tract


# ==================================================================
# StatusInfo dataclass behavior
# ==================================================================

class TestStatusInfoDataclass:
    """Tests for the StatusInfo dataclass itself (formatting, fields)."""

    def test_str_empty_tract(self):
        """__str__ on empty tract status shows 'None' for head."""
        info = StatusInfo(
            head_hash=None,
            branch_name=None,
            is_detached=False,
            commit_count=0,
            token_count=0,
            token_budget_max=None,
            token_source="",
            recent_commits=[],
        )
        s = str(info)
        assert "None" in s
        assert "detached" in s
        assert "0 commits" in s
        assert "0" in s

    def test_str_with_branch_and_commits(self):
        """__str__ shows branch name and commit info."""
        info = StatusInfo(
            head_hash="abcdef1234567890abcdef1234567890",
            branch_name="main",
            is_detached=False,
            commit_count=5,
            token_count=1234,
            token_budget_max=None,
            token_source="tiktoken:cl100k_base",
            recent_commits=[],
        )
        s = str(info)
        assert "main" in s
        assert "abcdef12" in s  # truncated to 8 chars
        assert "5 commits" in s
        assert "1234" in s

    def test_str_with_budget_shows_percentage(self):
        """__str__ includes budget and percentage when budget is set."""
        info = StatusInfo(
            head_hash="abcdef1234567890",
            branch_name="main",
            is_detached=False,
            commit_count=3,
            token_count=2500,
            token_budget_max=5000,
            token_source="tiktoken:cl100k_base",
            recent_commits=[],
        )
        s = str(info)
        assert "5000" in s
        assert "50%" in s

    def test_str_detached_shows_detached(self):
        """__str__ shows 'detached' when no branch name."""
        info = StatusInfo(
            head_hash="abcdef1234567890",
            branch_name=None,
            is_detached=True,
            commit_count=1,
            token_count=100,
            token_budget_max=None,
            token_source="",
            recent_commits=[],
        )
        s = str(info)
        assert "detached" in s

    def test_frozen_dataclass(self):
        """StatusInfo is frozen (immutable)."""
        info = StatusInfo(
            head_hash=None,
            branch_name=None,
            is_detached=False,
            commit_count=0,
            token_count=0,
            token_budget_max=None,
            token_source="",
            recent_commits=[],
        )
        with pytest.raises(AttributeError):
            info.head_hash = "something"

    def test_default_recent_commits(self):
        """recent_commits defaults to empty list."""
        info = StatusInfo(
            head_hash=None,
            branch_name=None,
            is_detached=False,
            commit_count=0,
            token_count=0,
            token_budget_max=None,
            token_source="",
        )
        assert info.recent_commits == []


# ==================================================================
# Status queries through Tract.status()
# ==================================================================

class TestStatusEmptyTract:
    """Tests for Tract.status() on an empty tract."""

    def test_empty_tract_head_is_none(self):
        t = make_tract()
        info = t.search.status()
        assert info.head_hash is None

    def test_empty_tract_branch_is_none(self):
        t = make_tract()
        info = t.search.status()
        # No commits yet, so no branch resolution
        assert info.branch_name is None

    def test_empty_tract_not_detached(self):
        t = make_tract()
        info = t.search.status()
        assert info.is_detached is False

    def test_empty_tract_zero_counts(self):
        t = make_tract()
        info = t.search.status()
        assert info.commit_count == 0
        assert info.token_count == 0

    def test_empty_tract_no_budget(self):
        t = make_tract()
        info = t.search.status()
        assert info.token_budget_max is None

    def test_empty_tract_no_recent_commits(self):
        t = make_tract()
        info = t.search.status()
        assert info.recent_commits == []


# ==================================================================
# Status with various commit states
# ==================================================================

class TestStatusWithCommits:
    """Tests for Tract.status() with commits present."""

    def test_single_commit(self):
        """Status after one commit."""
        t = make_tract()
        h = t.commit(InstructionContent(text="System")).commit_hash
        info = t.search.status()
        assert info.head_hash == h
        assert info.commit_count == 1
        assert info.branch_name == "main"
        assert info.is_detached is False
        assert len(info.recent_commits) == 1

    def test_multiple_commits_head_is_latest(self):
        """Head tracks the latest commit."""
        t = make_tract()
        hashes = populate_tract(t, 5)
        info = t.search.status()
        assert info.head_hash == hashes[-1]
        assert info.commit_count == 5

    def test_recent_commits_capped_at_3(self):
        """recent_commits never exceeds 3 entries."""
        t = make_tract()
        populate_tract(t, 10)
        info = t.search.status()
        assert len(info.recent_commits) == 3

    def test_recent_commits_newest_first(self):
        """recent_commits are in reverse chronological order."""
        t = make_tract()
        hashes = populate_tract(t, 5)
        info = t.search.status()
        assert info.recent_commits[0].commit_hash == hashes[4]
        assert info.recent_commits[1].commit_hash == hashes[3]
        assert info.recent_commits[2].commit_hash == hashes[2]

    def test_token_count_matches_compile(self):
        """Token count from status matches compile() output."""
        t = make_tract()
        populate_tract(t, 3)
        compiled = t.compile()
        info = t.search.status()
        assert info.token_count == compiled.token_count

    def test_token_source_populated(self):
        """Token source is set after commits."""
        t = make_tract()
        populate_tract(t, 1)
        info = t.search.status()
        assert info.token_source != ""


# ==================================================================
# Status with branches and detached HEAD
# ==================================================================

class TestStatusBranches:
    """Tests for Tract.status() with branch operations."""

    def test_new_branch_shows_branch_name(self):
        """After checking out a new branch, status reflects it."""
        t = make_tract()
        populate_tract(t, 2)
        t.branches.create("feature")
        t.branches.checkout("feature")
        info = t.search.status()
        assert info.branch_name == "feature"
        assert info.is_detached is False

    def test_detached_head_after_checkout_hash(self):
        """Checking out a specific commit enters detached HEAD state."""
        t = make_tract()
        hashes = populate_tract(t, 3)
        t.branches.checkout(hashes[0])
        info = t.search.status()
        assert info.is_detached is True
        assert info.branch_name is None
        assert info.head_hash == hashes[0]

    def test_detached_head_commit_count(self):
        """In detached state, commit count reflects the detached position."""
        t = make_tract()
        hashes = populate_tract(t, 5)
        t.branches.checkout(hashes[1])
        info = t.search.status()
        # Should count commits reachable from hashes[1]
        assert info.commit_count == 2
        assert info.head_hash == hashes[1]

    def test_reattach_after_detach(self):
        """Checking out a branch after detached HEAD reattaches."""
        t = make_tract()
        hashes = populate_tract(t, 3)
        t.branches.checkout(hashes[0])
        assert t.search.status().is_detached is True

        t.branches.checkout("main")
        info = t.search.status()
        assert info.is_detached is False
        assert info.branch_name == "main"
        assert info.head_hash == hashes[-1]

    def test_status_after_branch_commit(self):
        """Commits on a branch update status correctly."""
        t = make_tract()
        populate_tract(t, 2)
        t.branches.create("feature")
        t.branches.checkout("feature")
        feat_h = t.commit(
            DialogueContent(role="user", text="Feature work")
        ).commit_hash

        info = t.search.status()
        assert info.head_hash == feat_h
        assert info.branch_name == "feature"
        assert info.commit_count == 3  # 2 from main + 1 on feature


# ==================================================================
# Status with token budget
# ==================================================================

class TestStatusTokenBudget:
    """Tests for Tract.status() with token budget configuration."""

    def test_budget_reflected_in_status(self):
        """token_budget_max populated when budget is configured."""
        config = TractConfig(
            token_budget=TokenBudgetConfig(max_tokens=8000),
        )
        t = Tract.open(":memory:", config=config)
        populate_tract(t, 1)
        info = t.search.status()
        assert info.token_budget_max == 8000

    def test_no_budget_is_none(self):
        """token_budget_max is None without budget config."""
        t = make_tract()
        populate_tract(t, 1)
        info = t.search.status()
        assert info.token_budget_max is None

    def test_str_format_with_budget(self):
        """String representation includes budget info when set."""
        config = TractConfig(
            token_budget=TokenBudgetConfig(max_tokens=10000),
        )
        t = Tract.open(":memory:", config=config)
        populate_tract(t, 2)
        info = t.search.status()
        s = str(info)
        assert "10000" in s
        # Should show percentage
        assert "%" in s


# ==================================================================
# StatusInfo.pprint smoke test
# ==================================================================

class TestStatusPprint:
    """Smoke test for StatusInfo.pprint() method."""

    def test_pprint_does_not_raise(self, capsys):
        """pprint() should execute without error."""
        t = make_tract()
        populate_tract(t, 2)
        info = t.search.status()
        # Should not raise
        info.pprint()

    def test_pprint_empty_status_does_not_raise(self, capsys):
        """pprint() on empty tract should not raise."""
        t = make_tract()
        info = t.search.status()
        info.pprint()

    def test_pprint_with_max_chars(self, capsys):
        """pprint() with max_chars should not raise."""
        t = make_tract()
        populate_tract(t, 3)
        info = t.search.status()
        info.pprint(max_chars=50)
