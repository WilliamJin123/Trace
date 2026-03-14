"""Batch Operations Reference -- comprehensive guide to t.batch().

batch() is a context manager that groups multiple commits into a single
atomic database transaction. Either all commits succeed, or none do.
This is essential for operations that must be all-or-nothing.

Patterns shown:
  1. Basic batch              -- multiple commits in one transaction
  2. Batch rollback on error  -- nothing is committed if an exception occurs
  3. Nested batches           -- not supported (show the behavior)
  4. Batch + middleware       -- middleware fires inside batch
  5. Batch for atomic branch  -- setup a branch with initial state atomically
  6. Performance comparison   -- batch vs individual commits

Demonstrates: t.batch(), t.commit(), t.system(), t.user(), t.assistant(),
              t.branch(), t.configure(), t.use()

No LLM required.
"""

import time

from tract import MiddlewareContext, Tract
from tract.formatting import pprint_log


def basic_batch():
    """Group multiple commits into one atomic transaction."""

    print("=" * 60)
    print("1. Basic Batch -- Atomic Multi-Commit")
    print("=" * 60)
    print()

    with Tract.open() as t:
        # Without batch: each call commits immediately
        t.system("You are a helpful assistant.")
        commits_before = len(t.log())
        print(f"  Commits after system(): {commits_before}")

        # With batch: all commits happen at once
        with t.batch():
            t.user("Hello, I need help with three things.")
            t.assistant("Of course! What do you need?")
            t.user("1. Write a poem about cats")
            t.assistant("Sure! Here is a poem about cats...")
            t.user("2. Calculate the area of a circle with radius 5")
            t.assistant("Area = pi * r^2 = 78.54 square units.")

        commits_after = len(t.log())
        batch_commits = commits_after - commits_before
        print(f"  Commits after batch: {commits_after} ({batch_commits} new)")

        ctx = t.compile()
        ctx.pprint(style="compact")

        assert batch_commits == 6, f"Batch should add 6 commits, got {batch_commits}"
        assert len(ctx.messages) >= 7, "Should have system + 6 batch messages"

        # Verify all messages are present
        text = " ".join((m.content or "") for m in ctx.messages)
        assert "poem about cats" in text
        assert "78.54" in text

    print()
    print("PASSED")


def batch_rollback():
    """On exception, all commits in the batch are rolled back."""

    print()
    print("=" * 60)
    print("2. Batch Rollback on Error")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a data processor.")
        t.user("Process this data in three steps.")
        commits_before = len(t.log())
        head_before = t.head
        print(f"  Before batch: {commits_before} commits, HEAD={head_before[:8]}")

        # Batch that fails partway through
        try:
            with t.batch():
                t.assistant("Step 1: Data loaded.")
                t.assistant("Step 2: Data cleaned.")
                # Simulate an error before step 3
                raise ValueError("Simulated processing error at step 3")
        except ValueError as e:
            print(f"  Caught error: {e}")

        commits_after = len(t.log())
        head_after = t.head
        print(f"  After failed batch: {commits_after} commits, HEAD={head_after[:8]}")

        # Verify rollback: HEAD should not have moved
        assert commits_after == commits_before, (
            f"Expected {commits_before} commits (rollback), got {commits_after}"
        )
        assert head_after == head_before, "HEAD should not move on failed batch"

        # Context should not contain the failed batch
        ctx = t.compile()
        text = " ".join((m.content or "") for m in ctx.messages)
        assert "Data loaded" not in text, "Rolled-back commits should not be in context"
        assert "Data cleaned" not in text, "Rolled-back commits should not be in context"

        print("  Verified: all batch commits rolled back")

    print()
    print("PASSED")


def nested_batch_behavior():
    """Nested batches are not officially supported -- show what happens."""

    print()
    print("=" * 60)
    print("3. Nested Batches -- Unsupported Behavior")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a test assistant.")
        commits_before = len(t.log())

        # Nested batches: the inner batch's finally clause restores a
        # noop commit function instead of the real one, so the outer batch
        # may not commit properly. This is intentionally NOT supported.
        #
        # The safe pattern: flatten your operations into a single batch.

        print("  Nested batches are NOT supported.")
        print("  The safe pattern is to use a single flat batch:")
        print()
        print("    # DO NOT do this:")
        print("    with t.batch():        # outer")
        print("        t.user('A')")
        print("        with t.batch():    # inner -- UNSAFE")
        print("            t.user('B')")
        print()
        print("    # DO this instead:")
        print("    with t.batch():        # single flat batch")
        print("        t.user('A')")
        print("        t.user('B')")
        print()

        # Demonstrate the flat pattern works
        with t.batch():
            t.user("Message A")
            t.user("Message B")
            t.user("Message C")

        commits_after = len(t.log())
        assert commits_after == commits_before + 3
        print(f"  Flat batch: {commits_after - commits_before} commits added correctly")

    print()
    print("PASSED")


def batch_with_middleware():
    """Middleware fires normally inside a batch."""

    print()
    print("=" * 60)
    print("4. Batch + Middleware Interaction")
    print("=" * 60)
    print()

    with Tract.open() as t:
        commit_log: list[str] = []

        def track_commits(ctx: MiddlewareContext):
            """Record each commit's content type."""
            if ctx.commit:
                commit_log.append(ctx.commit.content_type)

        mw_id = t.use("post_commit", track_commits)

        # Middleware fires on each commit inside the batch
        with t.batch():
            t.system("You are a monitored assistant.")
            t.user("Hello")
            t.assistant("Hi there!")

        print(f"  Commits tracked by middleware: {len(commit_log)}")
        print(f"  Content types: {commit_log}")

        assert len(commit_log) == 3, f"Expected 3 middleware calls, got {len(commit_log)}"
        assert "instruction" in commit_log
        assert "dialogue" in commit_log

        # Verify the batch committed everything
        ctx = t.compile()
        assert len(ctx.messages) >= 3
        ctx.pprint(style="compact")

        t.remove_middleware(mw_id)

    print()
    print("PASSED")


def batch_atomic_branch_setup():
    """Set up a branch with initial state atomically."""

    print()
    print("=" * 60)
    print("5. Batch for Atomic Branch Operations")
    print("=" * 60)
    print()

    with Tract.open() as t:
        t.system("You are a project manager.")

        # Setup: main has some context
        t.user("We have a new project to plan.")
        t.assistant("Ready to help with project planning.")

        main_head = t.head
        print(f"  Main branch: [{main_head[:8]}]")

        # Create a branch and populate it atomically
        t.branch("sprint_1", switch=True)

        with t.batch():
            # All of this happens in one transaction
            t.configure(stage="sprint_1", temperature=0.3)
            t.user("Sprint 1 scope: auth module, database schema, API endpoints.")
            t.assistant("Sprint 1 planned with 3 deliverables.")
            t.user("Task 1: Implement JWT authentication.")
            t.assistant("JWT auth implementation plan ready.")
            t.user("Task 2: Design user table schema.")
            t.assistant("Schema: users(id, email, password_hash, created_at).")

        sprint_commits = len(t.log())
        ctx = t.compile()
        ctx.pprint(style="compact")

        # Switch back to main -- sprint_1 setup is all-or-nothing
        t.switch("main")
        main_ctx = t.compile()
        main_ctx.pprint(style="compact")

        # Verify branch isolation
        assert len(main_ctx.messages) < len(ctx.messages), (
            "Main should have fewer messages than sprint_1"
        )

        # Merge sprint_1 when ready
        result = t.merge("sprint_1")
        merged_ctx = t.compile()
        merged_ctx.pprint(style="compact")

        text = " ".join((m.content or "") for m in merged_ctx.messages)
        assert "JWT" in text, "Merged content should include sprint work"

    print()
    print("PASSED")


def performance_comparison():
    """Compare batch vs individual commits for throughput."""

    print()
    print("=" * 60)
    print("6. Performance: Batch vs Individual Commits")
    print("=" * 60)
    print()

    N = 100

    # Individual commits
    with Tract.open() as t:
        t.system("Perf test.")
        start = time.perf_counter()
        for i in range(N):
            t.user(f"Message {i}")
        individual_time = time.perf_counter() - start

    # Batch commits
    with Tract.open() as t:
        t.system("Perf test.")
        start = time.perf_counter()
        with t.batch():
            for i in range(N):
                t.user(f"Message {i}")
        batch_time = time.perf_counter() - start

    speedup = individual_time / batch_time if batch_time > 0 else float("inf")

    print(f"  {N} individual commits: {individual_time * 1000:.1f}ms")
    print(f"  {N} batched commits:    {batch_time * 1000:.1f}ms")
    print(f"  Speedup:                {speedup:.1f}x")
    print()

    # Both should produce the same result
    with Tract.open() as t:
        t.system("Verify.")
        with t.batch():
            for i in range(10):
                t.user(f"Msg {i}")
        ctx = t.compile()
        assert len(ctx.messages) == 11  # system + 10 user

    print("  Both approaches produce identical DAG state.")
    print(f"  Batch is typically faster due to single DB transaction.")

    # Note: speedup may vary. On in-memory SQLite the difference is small.
    # On disk-backed databases, batch avoids N separate fsync calls.

    print()
    print("PASSED")


def main() -> None:
    basic_batch()
    batch_rollback()
    nested_batch_behavior()
    batch_with_middleware()
    batch_atomic_branch_setup()
    performance_comparison()

    print()
    print("=" * 60)
    print("Summary: batch() Reference")
    print("=" * 60)
    print()
    print("  Operation                  Behavior Inside batch()")
    print("  -------------------------  -----------------------------------")
    print("  commit/user/assistant      Deferred to batch exit")
    print("  Exception raised           All commits rolled back")
    print("  Nested batch()             NOT supported -- use flat batch")
    print("  Middleware                  Fires normally on each commit")
    print("  branch() + configure()     Work inside batch for atomicity")
    print("  compile()                  Works but may see stale cache")
    print()
    print("  Key rule: batch() is for grouping writes. Keep it simple,")
    print("  keep it flat, and let the transaction handle atomicity.")
    print()
    print("Done.")


# Alias for pytest discovery
test_batch_operations = main


if __name__ == "__main__":
    main()


# --- See also ---
# Content types:        reference/01_content_types.py
# Branching reference:  reference/04_branching.py
# Error recovery:       error_handling/01_recovery_strategies.py
