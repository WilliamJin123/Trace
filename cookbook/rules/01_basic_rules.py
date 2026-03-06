"""Basic Rules

Rules are commits with: name, trigger, condition (optional), and action.

Demonstrates: t.rule(), triggers, tag/pattern/threshold conditions,
              set_config/block actions
"""

from tract import Tract


def main():
    with Tract.open() as t:

        # --- Different triggers ---

        print("=== Trigger Types ===\n")

        # Active: always in scope (config)
        t.rule("model", trigger="active",
               action={"type": "set_config", "key": "model", "value": "gpt-4o"})

        # Commit: fires on every commit
        t.rule("log-commits", trigger="commit",
               action={"type": "set_config", "key": "last_event", "value": "commit"})

        # Compile: fires when context is compiled
        t.rule("compile-note", trigger="compile",
               action={"type": "set_config", "key": "last_event", "value": "compile"})

        triggers = ["active", "commit", "compile", "compress", "merge", "gc",
                     "transition", "transition:review"]
        for trig in triggers:
            count = len(t.rule_index.get_by_trigger(trig))
            if count:
                print(f"  {trig:25s} -> {count} rule(s)")

        # --- Tag condition ---

        print("\n=== Tag Condition ===\n")

        t.rule(
            "block-draft-compress",
            trigger="compress",
            condition={"type": "tag", "tag": "draft", "present": True},
            action={"type": "block", "reason": "Cannot compress draft content"},
        )

        # Show the rule
        compress_rules = t.rule_index.get_by_trigger("compress")
        for r in compress_rules:
            print(f"  {r.name}: condition={r.condition}")

        # --- Pattern condition ---

        print("\n=== Pattern Condition ===\n")

        t.rule(
            "detect-code",
            trigger="commit",
            condition={"type": "pattern", "regex": r"```python"},
            action={"type": "set_config", "key": "has_code", "value": True},
        )

        commit_rules = t.rule_index.get_by_trigger("commit")
        for r in commit_rules:
            print(f"  {r.name}: condition={r.condition}")

        # --- Threshold condition ---

        print("\n=== Threshold Condition ===\n")

        t.rule(
            "auto-compress",
            trigger="commit",
            condition={"type": "threshold", "metric": "commit_count", "op": ">", "value": 50},
            action={"type": "operation", "op": "compress", "params": {}},
        )

        t.rule(
            "warn-long-branch",
            trigger="commit",
            condition={"type": "threshold", "metric": "branch_depth", "op": ">=", "value": 100},
            action={"type": "set_config", "key": "branch_warning", "value": "deep"},
        )

        commit_rules = t.rule_index.get_by_trigger("commit")
        for r in commit_rules:
            print(f"  {r.name}: action.type={r.action.get('type')}")

        # --- Combined: block action ---

        print("\n=== Block Action ===\n")

        t.rule(
            "read-only",
            trigger="commit",
            condition={"type": "tag", "tag": "locked", "present": True},
            action={"type": "block", "reason": "Branch is locked"},
        )

        all_rules = len(t.rule_index)
        print(f"  Total rules in index: {all_rules}")

        # --- Rules are commits ---

        print("\n=== Rules in the log ===\n")
        for ci in t.log():
            if ci.content_type == "rule":
                print(f"  {ci.commit_hash[:8]}  {ci.message}")


if __name__ == "__main__":
    main()
