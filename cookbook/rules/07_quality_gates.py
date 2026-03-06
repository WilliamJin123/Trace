"""Quality Gates

Gates use "require" and "block" actions, evaluated first in the pipeline.
  - require: blocks if the inner condition is NOT met
  - block:   blocks if the rule's condition IS met

Demonstrates: require action, block action, gate pipeline, pattern blocks
"""

from tract import Tract, BlockedByRuleError


def main():
    with Tract.open() as t:

        print("=== Require Gate ===\n")

        t.rule(
            "min-content-gate",
            trigger="transition:review",
            action={
                "type": "require",
                "condition": {
                    "type": "threshold",
                    "metric": "commit_count",
                    "op": ">=",
                    "value": 5,
                },
            },
        )

        t.system("You are a code reviewer.")
        t.user("Review this code.")

        # Not enough commits -- transition blocked
        result = t.transition("review")
        print(f"  Transition with 3 commits: {'allowed' if result else 'BLOCKED'}")

        # Add more content
        t.assistant("I see some issues.")
        t.user("What issues?")
        t.assistant("Missing error handling in the parse function.")

        # Now enough commits
        result = t.transition("review")
        print(f"  Transition with 6 commits: {'allowed' if result else 'BLOCKED'}")

        print("\n=== Block Gate ===\n")

        t.switch("main")

        t.rule(
            "no-compress-early",
            trigger="compress",
            condition={
                "type": "threshold",
                "metric": "commit_count",
                "op": "<",
                "value": 20,
            },
            action={"type": "block", "reason": "Too few commits to compress"},
        )

        print("  Block rule: no compression under 20 commits")
        print(f"  Current commits: {len(t.log())}")

        print("\n=== Combined Gates ===\n")

        t.rule(
            "production-gate",
            trigger="transition:production",
            action={
                "type": "require",
                "condition": {
                    "type": "all",
                    "conditions": [
                        {"type": "threshold", "metric": "commit_count", "op": ">=", "value": 3},
                        {"type": "tag", "tag": "approved", "present": True},
                    ],
                },
            },
        )

        print("  Production gate requires: commit_count >= 3 AND tag 'approved'")
        print("  (Tag conditions check ctx.commit; during transitions,")
        print("   combine with threshold metrics for reliable gating.)")

        print("\n=== Pattern-Based Block ===\n")

        t.rule(
            "no-secrets",
            trigger="commit",
            condition={"type": "pattern", "regex": r"(?i)(api[_-]?key|secret|password)\s*[:=]"},
            action={"type": "block", "reason": "Potential secret detected in commit"},
        )

        print("  Block rule: reject commits containing potential secrets")
        print("  Pattern: api_key, secret, password followed by : or =")

        print("\n=== Gate Summary ===\n")
        for trigger in ["commit", "compress", "transition:review", "transition:production"]:
            rules = t.rule_index.get_by_trigger(trigger)
            gates = [r for r in rules if r.action.get("type") in ("require", "block")]
            if gates:
                print(f"  {trigger}:")
                for g in gates:
                    print(f"    {g.name} -> {g.action['type']}")


if __name__ == "__main__":
    main()
