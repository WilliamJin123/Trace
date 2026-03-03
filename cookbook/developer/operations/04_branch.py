"""Branch Lifecycle -- Create, Switch, List, Delete

Two tiers of branch usage: manual lifecycle and automated tangent detection.

PART 1 -- Manual           Direct branch/switch/list/delete calls
PART 2 -- Automated        BranchTrigger detects content type tangents

Demonstrates: branch(), switch(), list_branches(), current_branch,
              branch(switch=False), delete_branch(force=True),
              BranchTrigger, configure_triggers(), t.on("trigger", handler)
"""

import sys
from pathlib import Path

from tract import Tract, BranchTrigger

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import cerebras as llm

MODEL_ID = llm.large


# =============================================================================
# PART 1 -- Manual: Direct API calls, no LLM, deterministic
# =============================================================================

def part1_manual():
    print("=" * 60)
    print("PART 1 -- Manual: Branch Lifecycle")
    print("=" * 60)
    print()
    print("  Try an experimental explanation style without affecting main.")
    print("  Branching is lightweight -- it's just a pointer to a commit,")
    print("  not a copy.")
    print()

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        # --- Build a conversation on main ---

        print("=== Main branch: start a conversation ===\n")

        t.system("You are a concise Python tutor. One paragraph max.")
        r1 = t.chat("Explain what a decorator is.")
        r1.pprint()

        main_messages = len(t.compile().messages)
        print(f"\n  Branch: {t.current_branch}  |  Messages: {main_messages}\n")

        # --- Branch: try a different explanation style ---

        print("=== Branch 'analogy': try a different angle ===\n")

        t.branch("analogy")
        print(f"  Switched to: {t.current_branch}")

        r2 = t.chat("Re-explain decorators using a real-world analogy, like gift wrapping.")
        r2.pprint()

        analogy_messages = len(t.compile().messages)
        print(f"\n  Branch: {t.current_branch}  |  Messages: {analogy_messages}\n")

        # --- List branches ---

        print("=== All branches ===\n")

        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"  {marker} {b.name:12s}  @ {b.commit_hash[:8]}")

        # --- Switch back to main ---

        print("\n=== Switch back to main ===\n")

        t.switch("main")
        ctx_main = t.compile()
        print(f"  Branch: {t.current_branch}  |  Messages: {len(ctx_main.messages)}")
        print(f"  (analogy branch had {analogy_messages} -- main is untouched)")

        # --- Peek at analogy from main ---

        print("\n=== Peek at analogy ===\n")

        t.switch("analogy")
        ctx_analogy = t.compile()
        print(f"  Branch: {t.current_branch}  |  Messages: {len(ctx_analogy.messages)}")
        ctx_analogy.pprint(style="chat")

        # --- Create a branch without switching ---

        t.switch("main")
        t.branch("draft", switch=False)
        print(f"\n=== Created 'draft' without switching ===")
        print(f"  Still on: {t.current_branch}")

        print("\n  All branches:")
        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"    {marker} {b.name}")

        # --- Clean up ---

        print("\n=== Clean up ===\n")

        t.delete_branch("analogy", force=True)
        t.delete_branch("draft", force=True)

        remaining = [b.name for b in t.list_branches()]
        print(f"  Remaining branches: {remaining}")


# =============================================================================
# PART 2 -- Automated: BranchTrigger detects content type tangents
# =============================================================================

def part2_automated():
    print("\n" + "=" * 60)
    print("PART 2 -- Automated: Tangent Detection via BranchTrigger")
    print("=" * 60)
    print()
    print("  BranchTrigger watches for rapid content type switching.")
    print("  When the conversation tangents (e.g., dialogue -> artifact ->")
    print("  dialogue), it proposes a branch to isolate the tangent.")
    print()

    # Low threshold so our short demo triggers it
    trigger = BranchTrigger(content_type_window=5, switch_threshold=2)

    with Tract.open() as t:
        t.configure_triggers([trigger])

        # Hook to intercept the trigger proposal
        proposals = []

        def on_trigger(pending):
            proposals.append(pending)
            print(f"  [trigger] {pending.trigger_name}: {pending.reason}")
            print(f"  [trigger] proposed branch: {pending.action_params.get('name', '?')}")
            pending.approve()

        t.on("trigger", on_trigger, name="tangent-detector")

        # Build a conversation with mixed content types
        t.system("You are a helpful assistant.")
        t.user("What is Python?")
        t.assistant("Python is a programming language.")
        t.tool_result("def hello(): pass", tool_call_id="t1", name="code_gen")
        t.user("Now explain decorators.")

        print(f"\n  Trigger fired {len(proposals)} time(s)")
        print(f"  Branches: {[b.name for b in t.list_branches()]}")

        # Manual evaluate to show the API
        print("\n  --- Manual evaluate() ---")
        action = trigger.evaluate(t)
        if action:
            print(f"  action_type={action.action_type}")
            print(f"  reason: {action.reason}")
            print(f"  autonomy: {action.autonomy}")
        else:
            print(f"  No tangent detected (already handled by trigger)")


# --- Tier notes ---
# Commits and compile are primitives; they don't have review=True variants.
# For HITL patterns, see: hooks/ (t.on(), review=True)
# For agent automation, see: agentic/sidecar/ (triggers, orchestrator)


def main():
    part1_manual()
    part2_automated()


if __name__ == "__main__":
    main()
