"""Tests for the middleware system: registration, execution, blocking, recursion guard.

Covers:
- t.middleware.add() registers handler, returns ID
- t.middleware.remove(id) removes handler
- Middleware fires in registration order
- pre_commit middleware fires before commit
- post_commit middleware fires after commit
- pre_compile middleware fires before compile
- pre_compress, pre_merge, pre_gc middleware fire
- pre_transition and post_transition middleware fire
- Middleware can block via BlockedError (pre_ events)
- BlockedError in post_* propagates as exception
- Recursion guard: same-event re-entry skipped
- Cross-event middleware fires normally
- Invalid event name raises ValueError
- MiddlewareContext has correct fields
"""

from __future__ import annotations

import pytest

from tract import (
    BlockedError,
    DialogueContent,
    InstructionContent,
    Tract,
)
from tract.middleware import MiddlewareContext, VALID_EVENTS


# ---------------------------------------------------------------------------
# Registration and removal
# ---------------------------------------------------------------------------


class TestMiddlewareRegistration:
    """t.middleware.add() and t.middleware.remove()."""

    def test_use_returns_id(self):
        """t.middleware.add() returns a string handler ID."""
        with Tract.open() as t:
            handler_id = t.middleware.add("pre_commit", lambda ctx: None)
            assert isinstance(handler_id, str)
            assert len(handler_id) > 0

    def test_use_returns_unique_ids(self):
        """Each t.middleware.add() call returns a unique ID."""
        with Tract.open() as t:
            id1 = t.middleware.add("pre_commit", lambda ctx: None)
            id2 = t.middleware.add("pre_commit", lambda ctx: None)
            assert id1 != id2

    def test_remove_middleware_by_id(self):
        """t.middleware.remove(id) removes the handler."""
        calls = []
        with Tract.open() as t:
            handler_id = t.middleware.add("post_commit", lambda ctx: calls.append("fired"))
            t.user("Before removal")
            assert len(calls) == 1
            t.middleware.remove(handler_id)
            t.user("After removal")
            assert len(calls) == 1  # handler no longer fires

    def test_remove_nonexistent_raises(self):
        """Removing a nonexistent handler ID raises ValueError."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="not found"):
                t.middleware.remove("nonexistent-id")

    def test_invalid_event_raises(self):
        """Registering on an invalid event raises ValueError."""
        with Tract.open() as t:
            with pytest.raises(ValueError, match="Unknown middleware event"):
                t.middleware.add("invalid_event", lambda ctx: None)

    def test_valid_events_are_recognized(self):
        """All valid events from VALID_EVENTS are accepted."""
        with Tract.open() as t:
            for event in VALID_EVENTS:
                handler_id = t.middleware.add(event, lambda ctx: None)
                assert isinstance(handler_id, str)


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------


class TestMiddlewareOrder:
    """Middleware fires in registration order."""

    def test_handlers_fire_in_order(self):
        """Multiple handlers on the same event fire in registration order."""
        order = []
        with Tract.open() as t:
            t.middleware.add("post_commit", lambda ctx: order.append("first"))
            t.middleware.add("post_commit", lambda ctx: order.append("second"))
            t.middleware.add("post_commit", lambda ctx: order.append("third"))
            t.user("trigger")
            assert order == ["first", "second", "third"]

    def test_different_events_independent(self):
        """Handlers on different events fire independently."""
        pre_calls = []
        post_calls = []
        with Tract.open() as t:
            t.middleware.add("pre_commit", lambda ctx: pre_calls.append(1))
            t.middleware.add("post_commit", lambda ctx: post_calls.append(1))
            t.user("trigger")
            assert len(pre_calls) == 1
            assert len(post_calls) == 1


# ---------------------------------------------------------------------------
# Event firing
# ---------------------------------------------------------------------------


class TestMiddlewareEvents:
    """Middleware fires at the right operation boundaries."""

    def test_pre_commit_fires_before_commit(self):
        """pre_commit fires before the commit is stored."""
        events = []
        with Tract.open() as t:
            def pre_handler(ctx):
                # At this point, head should not yet reflect the new commit
                events.append(("pre", t.head))
            t.middleware.add("pre_commit", pre_handler)
            old_head = t.head
            t.user("Hello")
            assert events[0] == ("pre", old_head)

    def test_post_commit_fires_after_commit(self):
        """post_commit fires after the commit is stored."""
        events = []
        with Tract.open() as t:
            def post_handler(ctx):
                events.append(("post", ctx.commit))
            t.middleware.add("post_commit", post_handler)
            info = t.user("Hello")
            assert len(events) == 1
            assert events[0][1] is not None
            assert events[0][1].commit_hash == info.commit_hash

    def test_pre_compile_fires(self):
        """pre_compile fires when compile() is called."""
        fired = []
        with Tract.open() as t:
            t.middleware.add("pre_compile", lambda ctx: fired.append(True))
            t.user("Hello")
            t.compile()
            assert len(fired) == 1

    def test_pre_transition_fires(self):
        """pre_transition fires during transition()."""
        events = []
        with Tract.open() as t:
            t.user("Setup")
            t.middleware.add("pre_transition", lambda ctx: events.append(("pre", ctx.target)))
            t.transition("feature")
            assert len(events) == 1
            assert events[0] == ("pre", "feature")

    def test_post_transition_fires(self):
        """post_transition fires after transition()."""
        events = []
        with Tract.open() as t:
            t.user("Setup")
            t.middleware.add("post_transition", lambda ctx: events.append(("post", ctx.target)))
            t.transition("feature")
            assert len(events) == 1
            assert events[0] == ("post", "feature")


# ---------------------------------------------------------------------------
# Blocking behavior
# ---------------------------------------------------------------------------


class TestMiddlewareBlocking:
    """Middleware can block operations via BlockedError."""

    def test_pre_commit_blocks(self):
        """pre_commit handler raising BlockedError prevents commit."""
        with Tract.open() as t:
            def blocker(ctx):
                raise BlockedError("pre_commit", "Not allowed")
            t.middleware.add("pre_commit", blocker)
            with pytest.raises(BlockedError, match="Not allowed"):
                t.user("Should be blocked")
            # Verify no commit was made
            assert t.head is None

    def test_pre_compile_blocks(self):
        """pre_compile handler raising BlockedError prevents compile."""
        with Tract.open() as t:
            t.user("Hello")
            t.middleware.add("pre_compile", lambda ctx: (_ for _ in ()).throw(
                BlockedError("pre_compile", "Compile blocked")
            ))
            with pytest.raises(BlockedError, match="Compile blocked"):
                t.compile()

    def test_pre_transition_blocks(self):
        """pre_transition handler raising BlockedError prevents transition."""
        with Tract.open() as t:
            t.user("Setup")
            def blocker(ctx):
                raise BlockedError("pre_transition", "Cannot transition")
            t.middleware.add("pre_transition", blocker)
            with pytest.raises(BlockedError, match="Cannot transition"):
                t.transition("feature")
            # Should still be on main
            assert t.current_branch == "main"

    def test_blocked_error_has_event_and_reasons(self):
        """BlockedError carries event and reasons attributes."""
        err = BlockedError("pre_commit", ["reason1", "reason2"])
        assert err.event == "pre_commit"
        assert err.reasons == ["reason1", "reason2"]

    def test_blocked_error_single_reason(self):
        """BlockedError accepts a single string reason."""
        err = BlockedError("pre_commit", "single reason")
        assert err.reasons == ["single reason"]

    def test_post_commit_error_propagates(self):
        """BlockedError in post_commit propagates as exception."""
        with Tract.open() as t:
            def post_blocker(ctx):
                raise BlockedError("post_commit", "Post-commit error")
            t.middleware.add("post_commit", post_blocker)
            with pytest.raises(BlockedError, match="Post-commit error"):
                t.user("Hello")

    def test_blocking_skips_remaining_handlers(self):
        """After a handler blocks, remaining handlers are skipped."""
        calls = []
        with Tract.open() as t:
            def first(ctx):
                calls.append("first")
                raise BlockedError("pre_commit", "blocked")
            def second(ctx):
                calls.append("second")
            t.middleware.add("pre_commit", first)
            t.middleware.add("pre_commit", second)
            with pytest.raises(BlockedError):
                t.user("trigger")
            assert calls == ["first"]  # second never called


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------


class TestMiddlewareRecursionGuard:
    """Same-event re-entry is skipped; cross-event fires normally."""

    def test_same_event_reentry_skipped(self):
        """A pre_commit handler that triggers another commit skips re-entry."""
        calls = []
        with Tract.open() as t:
            def recursive_handler(ctx):
                calls.append("enter")
                # This would trigger pre_commit again, but recursion guard prevents it
                t.commit(DialogueContent(role="system", text="inner"))
            t.middleware.add("pre_commit", recursive_handler)
            t.user("outer")
            # The handler fires once for outer, and the inner commit
            # does NOT re-trigger the pre_commit handler
            assert calls.count("enter") == 1

    def test_cross_event_fires_normally(self):
        """A pre_commit handler that triggers compile fires pre_compile."""
        compile_calls = []
        with Tract.open() as t:
            t.user("Setup")  # Need at least one commit for compile
            t.middleware.add("pre_compile", lambda ctx: compile_calls.append(True))
            def commit_handler(ctx):
                t.compile()  # This fires pre_compile (different event)
            t.middleware.add("post_commit", commit_handler)
            t.user("trigger")
            # pre_compile should have fired from within the post_commit handler
            assert len(compile_calls) >= 1


# ---------------------------------------------------------------------------
# MiddlewareContext fields
# ---------------------------------------------------------------------------


class TestMiddlewareContext:
    """MiddlewareContext dataclass has correct fields."""

    def test_context_fields_on_pre_commit(self):
        """pre_commit context has event, tract, branch, head, pending."""
        captured = []
        with Tract.open() as t:
            t.user("Setup")  # Establish a head
            def handler(ctx):
                captured.append(ctx)
            t.middleware.add("pre_commit", handler)
            t.user("Hello")
            assert len(captured) == 1
            ctx = captured[0]
            assert ctx.event == "pre_commit"
            assert ctx.tract is t
            assert ctx.branch == "main"
            assert ctx.head is not None
            assert ctx.pending is not None

    def test_context_fields_on_post_commit(self):
        """post_commit context has commit set to CommitInfo."""
        captured = []
        with Tract.open() as t:
            t.middleware.add("post_commit", lambda ctx: captured.append(ctx))
            info = t.user("Hello")
            ctx = captured[0]
            assert ctx.event == "post_commit"
            assert ctx.commit is not None
            assert ctx.commit.commit_hash == info.commit_hash

    def test_context_target_on_transition(self):
        """Transition context has target set."""
        captured = []
        with Tract.open() as t:
            t.user("Setup")
            t.middleware.add("pre_transition", lambda ctx: captured.append(ctx))
            t.transition("feature")
            ctx = captured[0]
            assert ctx.target == "feature"

    def test_context_is_frozen(self):
        """MiddlewareContext is frozen (immutable)."""
        from dataclasses import FrozenInstanceError
        with Tract.open() as t:
            captured = []
            t.middleware.add("post_commit", lambda ctx: captured.append(ctx))
            t.user("Hello")
            ctx = captured[0]
            with pytest.raises(FrozenInstanceError):
                ctx.event = "other"
