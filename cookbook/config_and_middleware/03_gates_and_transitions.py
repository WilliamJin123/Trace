"""Gates and Transitions

Transitions move work between branches. Middleware gates guard them:
  - pre_transition middleware can raise BlockedError to prevent transitions
  - post_transition middleware runs after a successful transition
  - Handoff modes control what context crosses the boundary

Three handoff modes:
  - "none"    -- switch branch, no context carried over
  - "full"    -- compile all context and commit as system message
  - "summary" -- adaptive compile (last K messages) as handoff

Demonstrates: t.transition(), handoff modes, pre_transition middleware
              as gates, post_transition logging, BlockedError

No LLM required.
"""

from tract import Tract, BlockedError, MiddlewareContext


def main() -> None:
    with Tract.open() as t:

        # --- Transition gate middleware ---

        print("=== Transition Gate ===\n")

        t.system("You are a coding assistant.")

        def review_gate(ctx: MiddlewareContext):
            """Require at least 5 commits before transitioning to review."""
            if ctx.target != "review":
                return
            commit_count = len(ctx.tract.log())
            if commit_count < 5:
                raise BlockedError(
                    "pre_transition",
                    [f"Need >= 5 commits for review (have {commit_count})"],
                )

        gate_id = t.use("pre_transition", review_gate)

        # Generic transition logging
        transition_log = []

        def log_transitions(ctx: MiddlewareContext):
            """Log all transitions."""
            transition_log.append(ctx.target)

        log_id = t.use("post_transition", log_transitions)

        print(f"  Gate registered: {gate_id}")
        print(f"  Logger registered: {log_id}")

        # --- Attempt transition too early ---

        print("\n=== Transition Blocked (too few commits) ===\n")

        try:
            t.transition("review")
            print("  Transition succeeded (unexpected)")
        except BlockedError as e:
            print(f"  Blocked: {e.reasons[0]}")
            print(f"  Current branch: {t.current_branch}")

        # --- Add enough content ---

        t.user("Implement a fibonacci function")
        t.assistant("Here is the implementation...")
        t.user("Add error handling")
        t.assistant("Updated with input validation...")

        print(f"\n  Commit count: {len(t.log())}")

        # --- Transition succeeds ---

        print("\n=== Transition Succeeds ===\n")

        result = t.transition("review")
        print(f"  Current branch: {t.current_branch}")
        print(f"  Transition log: {transition_log}")

        # --- Handoff modes ---

        print("\n=== Handoff Modes ===\n")

        # Switch back to add more content
        t.switch("main")
        t.user("More context for handoff demo")
        t.assistant("Acknowledged")

        # Transition with full handoff
        result = t.transition("full-handoff-branch", handoff="full")
        if result:
            print(f"  full handoff -> commit {result.commit_hash[:8]} on {t.current_branch}")

        # Switch back and try summary handoff
        t.switch("main")
        t.configure(handoff_summary_k=3)
        result = t.transition("summary-handoff-branch", handoff="summary")
        if result:
            print(f"  summary handoff -> commit {result.commit_hash[:8]} on {t.current_branch}")

        # Custom text handoff
        t.switch("main")
        result = t.transition("custom-handoff-branch", handoff="Key context: user needs fibonacci")
        if result:
            print(f"  custom handoff -> commit {result.commit_hash[:8]} on {t.current_branch}")

        # No handoff (just switch)
        t.switch("main")
        result = t.transition("bare-branch", handoff="none")
        print(f"  no handoff -> result={result}, branch={t.current_branch}")

        # --- Multiple gates ---

        print("\n=== Multiple Gates ===\n")

        t.switch("main")

        def production_gate(ctx: MiddlewareContext):
            """Require 'approved' config flag before production transition."""
            if ctx.target != "production":
                return
            if not ctx.tract.get_config("approved"):
                raise BlockedError(
                    "pre_transition",
                    ["Production requires approved=True in config"],
                )

        prod_gate_id = t.use("pre_transition", production_gate)

        try:
            t.transition("production")
            print("  Production transition succeeded (unexpected)")
        except BlockedError as e:
            print(f"  Blocked: {e.reasons[0]}")

        # Set approval config and retry
        t.configure(approved=True)
        t.transition("production")
        print(f"  After approval: transitioned to {t.current_branch}")

        # --- Gate summary ---

        print("\n=== Gate Summary ===\n")
        print(f"  Transitions logged: {transition_log}")
        print(f"  Branches created:")
        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"    {marker} {b.name}")


if __name__ == "__main__":
    main()
