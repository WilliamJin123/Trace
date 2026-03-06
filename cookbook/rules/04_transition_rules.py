"""Transition Rules

Transitions move work between branches using rules as gates and handoffs.
Two trigger forms:
  - "transition"          -- fires on ANY transition from this branch
  - "transition:{target}" -- fires only for a specific target branch

The pipeline: gates (require/block) -> work -> handoff (compile_filter)

Demonstrates: transition triggers, gate conditions, compile_filter action,
              t.transition(), branching
"""

from tract import Tract


def main():
    with Tract.open() as t:

        # --- Set up branches and rules ---

        print("=== Setting Up Workflow ===\n")

        t.system("You are a coding assistant.")

        # Gate: require at least 3 commits before transitioning to review
        t.rule(
            "review-gate",
            trigger="transition:review",
            action={
                "type": "require",
                "condition": {
                    "type": "threshold",
                    "metric": "commit_count",
                    "op": ">=",
                    "value": 6,
                },
            },
        )

        # Generic transition rule: log transitions
        t.rule(
            "transition-log",
            trigger="transition",
            action={"type": "set_config", "key": "last_transition", "value": "logged"},
        )

        # Compile filter for review transitions
        t.rule(
            "review-filter",
            trigger="transition:review",
            action={
                "type": "compile_filter",
                "mode": "full",
            },
        )

        print("  Rules created:")
        for trig in ["transition", "transition:review"]:
            for r in t.rule_index.get_by_trigger(trig):
                print(f"    [{trig}] {r.name} -> {r.action['type']}")

        # --- Try transition too early (gate blocks) ---

        print("\n=== Attempt Transition (too early) ===\n")

        result = t.transition("review")
        print(f"  Transition result: {result}")
        print(f"  Current branch:    {t.current_branch}")
        print("  (Blocked: not enough commits yet)")

        # --- Add enough content ---

        print("\n=== Adding Content ===\n")

        t.user("Implement a fibonacci function")
        t.assistant("Here is the implementation...")
        t.user("Add error handling")
        t.assistant("Updated with input validation...")

        print(f"  Commit count: {len(t.log())}")

        # --- Transition succeeds ---

        print("\n=== Transition to review ===\n")

        result = t.transition("review")
        if result:
            print(f"  Success! Handoff commit: {result.commit_hash[:8]}")
            print(f"  Current branch: {t.current_branch}")
            print(f"  Message: {result.message}")
        else:
            print("  Blocked by rules")

        # --- Show branches ---

        print("\n=== Branches ===\n")
        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"  {marker} {b.name}")

        # --- Review branch has the handoff context ---

        print("\n=== Review Branch Context ===\n")
        ctx = t.compile()
        print(f"  Messages on review branch: {len(ctx.messages)}")


if __name__ == "__main__":
    main()
