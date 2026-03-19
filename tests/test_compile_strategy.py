"""Tests for compile strategy: full, messages, adaptive.

Covers:
- Full strategy (default) returns complete content
- Messages strategy returns commit messages only
- Adaptive strategy splits full/messages at strategy_k boundary
- Edge cases: invalid strategy, empty tract, DAG immutability
- Strategy interaction with non-compilable content types (rules)
"""

import pytest

from tract import Tract


def _make_tract_with_commits(n: int) -> Tract:
    """Create a tract with n user/assistant commit pairs (2n total commits)."""
    t = Tract.open()
    for i in range(n):
        t.user(f"User message {i}")
        t.assistant(f"Assistant response {i}")
    return t


# ---------------------------------------------------------------------------
# Full strategy
# ---------------------------------------------------------------------------


class TestFullStrategy:
    def test_full_is_default(self):
        """Default compile uses full strategy."""
        t = _make_tract_with_commits(3)
        compiled = t.compile()
        assert compiled.commit_count == 6
        assert any("User message 0" in m.content for m in compiled.messages)

    def test_full_explicit(self):
        """strategy='full' produces the same result as default."""
        t = _make_tract_with_commits(3)
        default = t.compile()
        explicit = t.compile(strategy="full")
        assert default.token_count == explicit.token_count
        assert default.commit_count == explicit.commit_count


# ---------------------------------------------------------------------------
# Messages strategy
# ---------------------------------------------------------------------------


class TestMessagesStrategy:
    def test_messages_returns_commits(self):
        """strategy='messages' returns entries for all commits."""
        t = _make_tract_with_commits(3)
        compiled = t.compile(strategy="messages")
        assert compiled.commit_count == 6
        assert compiled.token_count > 0

    def test_messages_has_correct_count(self):
        """Messages strategy includes all compilable commits."""
        t = _make_tract_with_commits(5)
        compiled = t.compile(strategy="messages")
        assert compiled.commit_count == 10

    def test_messages_content_differs_from_full_for_long_text(self):
        """Messages strategy differs from full for long content.

        The fallback commit message truncates at 500 chars, so content
        exceeding that limit will produce different output under messages
        vs full strategy.
        """
        long_text = "A" * 600  # exceeds 500-char auto-message truncation
        t = Tract.open()
        t.user(long_text)
        full = t.compile(strategy="full")
        messages = t.compile(strategy="messages")
        assert full.commit_count == messages.commit_count
        full_texts = [m.content for m in full.messages]
        msg_texts = [m.content for m in messages.messages]
        # Full keeps the 600-char text; messages truncates to ~500
        assert full_texts != msg_texts


# ---------------------------------------------------------------------------
# Adaptive strategy
# ---------------------------------------------------------------------------


class TestAdaptiveStrategy:
    def test_adaptive_returns_all_commits(self):
        """Adaptive strategy returns the same number of commits as full."""
        t = _make_tract_with_commits(5)
        full = t.compile(strategy="full")
        adaptive = t.compile(strategy="adaptive", strategy_k=2)
        assert adaptive.commit_count == full.commit_count

    def test_adaptive_k_larger_than_commits(self):
        """When k > total commits, adaptive behaves like full."""
        t = _make_tract_with_commits(3)
        full = t.compile(strategy="full")
        adaptive = t.compile(strategy="adaptive", strategy_k=100)
        assert adaptive.token_count == full.token_count

    def test_adaptive_k1(self):
        """k=1 means only the very last commit is full."""
        t = _make_tract_with_commits(5)
        compiled = t.compile(strategy="adaptive", strategy_k=1)
        assert compiled.commit_count == 10
        assert compiled.token_count > 0

    def test_adaptive_default_k(self):
        """Default k is 5; calling without strategy_k should work."""
        t = _make_tract_with_commits(3)
        compiled = t.compile(strategy="adaptive")
        assert compiled.commit_count == 6

    def test_adaptive_produces_valid_output(self):
        """Adaptive strategy produces well-formed CompiledContext."""
        t = _make_tract_with_commits(4)
        compiled = t.compile(strategy="adaptive", strategy_k=3)
        assert compiled.commit_count == 8
        assert compiled.token_count > 0
        assert len(compiled.messages) > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestStrategyEdgeCases:
    def test_invalid_strategy_raises(self):
        """Unknown strategy raises ValueError."""
        t = _make_tract_with_commits(1)
        with pytest.raises(ValueError, match="Invalid compile strategy"):
            t.compile(strategy="unknown")

    def test_empty_tract_full(self):
        """Full strategy on empty tract returns empty context."""
        t = Tract.open()
        compiled = t.compile(strategy="full")
        assert compiled.commit_count == 0

    def test_empty_tract_messages(self):
        """Messages strategy on empty tract returns empty context."""
        t = Tract.open()
        compiled = t.compile(strategy="messages")
        assert compiled.commit_count == 0

    def test_empty_tract_adaptive(self):
        """Adaptive strategy on empty tract returns empty context."""
        t = Tract.open()
        compiled = t.compile(strategy="adaptive")
        assert compiled.commit_count == 0

    def test_strategy_does_not_mutate_dag(self):
        """Compiling with any strategy does not change the DAG."""
        t = _make_tract_with_commits(3)
        log_before = [c.commit_hash for c in t.log()]
        t.compile(strategy="messages")
        t.compile(strategy="adaptive", strategy_k=2)
        log_after = [c.commit_hash for c in t.log()]
        assert log_before == log_after

    def test_single_commit_all_strategies(self):
        """All strategies work with a single commit."""
        t = Tract.open()
        t.user("Only message")
        for s in ("full", "messages", "adaptive"):
            compiled = t.compile(strategy=s)
            assert compiled.commit_count == 1


# ---------------------------------------------------------------------------
# Strategy interaction with non-compilable types
# ---------------------------------------------------------------------------


class TestStrategyWithNonCompilable:
    def test_config_excluded_full(self):
        """Config commits are excluded from compile output with full strategy."""
        t = Tract.open()
        t.user("Hello")
        t.config.set(temperature=0.3)
        t.assistant("World")
        compiled = t.compile(strategy="full")
        assert len(compiled.messages) == 2

    def test_config_excluded_messages(self):
        """Config commits are excluded from compile output with messages strategy."""
        t = Tract.open()
        t.user("Hello")
        t.config.set(temperature=0.3)
        t.assistant("World")
        compiled = t.compile(strategy="messages")
        assert len(compiled.messages) == 2

    def test_config_excluded_adaptive(self):
        """Config commits are excluded from compile output with adaptive strategy."""
        t = Tract.open()
        t.user("Hello")
        t.config.set(temperature=0.3)
        t.assistant("World")
        compiled = t.compile(strategy="adaptive")
        assert len(compiled.messages) == 2
