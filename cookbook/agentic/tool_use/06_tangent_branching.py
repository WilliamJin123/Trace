"""Tangent Branching -- Agent isolates off-topic questions on branches

An LLM agent working on a design task autonomously branches when the user
asks conceptual clarification questions that don't advance the project.
After answering on the branch, the tangent is compressed into a one-line
summary and merged back, keeping the main context focused.

Key technique: custom tool descriptions via ToolProfile steer the LLM on
*when* to branch, without any hardcoded trigger logic.

Tools exercised: branch, switch, status, log
Demonstrates: description overrides for behavioral steering, agent-managed
              branch lifecycle, compress-then-merge pattern
"""

import io
import json
import sys
from pathlib import Path

# Windows console encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from tract import Tract
from tract.toolkit import ToolConfig, ToolExecutor, ToolProfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import cerebras as llm

MODEL_ID = llm.large


# =====================================================================
# Tool profile: branching tools with steering descriptions
# =====================================================================

TANGENT_PROFILE = ToolProfile(
    name="tangent-manager",
    tool_configs={
        "branch": ToolConfig(
            enabled=True,
            description=(
                "Create a new branch. You MUST use this when the user asks a "
                "conceptual or clarification question that does not directly "
                "advance the current design or implementation discussion. "
                "Name the branch 'tangent/<topic>'. Set switch=true to work on it."
            ),
        ),
        "switch": ToolConfig(
            enabled=True,
            description=(
                "Switch to a different branch. Use this to return to 'main' "
                "after answering a tangent question on a branch."
            ),
        ),
        "status": ToolConfig(
            enabled=True,
            description="Check current branch, HEAD, and token count.",
        ),
        "log": ToolConfig(
            enabled=True,
            description="View recent commits on the current branch.",
        ),
    },
)


def run_agent_loop(t, executor, task, *, max_turns=10):
    """Agentic loop: user task -> tool calls -> final response."""
    t.user(task)

    for turn in range(max_turns):
        response = t.generate()

        if not response.tool_calls:
            text = response.text or "(empty)"
            print(f"\n  Agent: {text[:400]}")
            if len(text) > 400:
                print(f"         ...({len(text)} chars total)")
            return response

        for tc in response.tool_calls:
            result = executor.execute(tc.name, tc.arguments)
            t.tool_result(tc.id, tc.name, str(result))
            args_short = json.dumps(tc.arguments)[:80]
            ok = "OK" if result.success else "FAIL"
            output = str(result.output if result.success else result.error)[:100]
            print(f"    [{ok}] {tc.name}({args_short})")
            print(f"           {output}")

    print("  (max turns reached)")
    return None


def compress_and_merge_tangent(t, tangent_branch, summary):
    """Compress a tangent branch to a one-line summary and merge to main.

    This is the programmatic cleanup after the LLM answers on a tangent.
    In production, this could also be LLM-driven with a capable model.
    """
    print(f"\n  --- Cleanup: compress & merge '{tangent_branch}' ---")

    # Compress everything on the tangent (except shared ancestry) into a summary
    t.compress(content=summary)
    print(f"    Compressed tangent to: \"{summary}\"")

    # Switch to main and merge the compressed tangent
    t.switch("main")
    result = t.merge(tangent_branch, message=f"Merge tangent: {summary}")
    print(f"    Merged to main ({result.merge_type})")

    # Clean up the branch
    t.delete_branch(tangent_branch, force=True)
    print(f"    Deleted branch '{tangent_branch}'")


def main():
    if not llm.api_key:
        print("SKIPPED (no API key)")
        return

    print("=" * 70)
    print("Tangent Branching: Agent isolates off-topic questions on branches")
    print("=" * 70)
    print()
    print("  The agent is helping design an API. When the user asks a")
    print("  conceptual question ('what is REST?'), the agent should")
    print("  autonomously branch to isolate the tangent.")
    print()
    print("  Steering is done purely through tool description overrides --")
    print("  no triggers or hardcoded logic. The LLM reads the branch tool's")
    print("  description and decides when branching is appropriate.")
    print()

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        executor = ToolExecutor(t)
        tools = t.as_tools(profile=TANGENT_PROFILE)
        t.set_tools(tools)

        t.system(
            "You are a senior API architect helping design a REST API for a "
            "task management app. Stay focused on the design. When the user "
            "asks conceptual questions that don't advance the design (e.g. "
            "'what is REST?', 'explain HTTP methods'), use the branch tool "
            "to isolate the tangent before answering. Keep the main branch "
            "focused on design decisions only."
        )

        # --- Phase 1: Design question (should NOT branch) ---
        print("=== Phase 1: Design question (on main, no branching) ===\n")
        run_agent_loop(
            t, executor,
            "Let's design the API for a task management app. I need endpoints "
            "for creating, listing, updating, and deleting tasks. Each task has "
            "a title, description, status (todo/in_progress/done), and assignee. "
            "What's your recommended URL structure?",
        )
        print(f"\n  Branch: {t.current_branch}")

        # --- Phase 2: Conceptual tangent (should branch) ---
        print("\n\n=== Phase 2: Conceptual tangent (agent should branch) ===\n")
        run_agent_loop(
            t, executor,
            "Wait, quick question -- what actually is REST? I keep hearing "
            "the term but I don't fully understand the principles behind it.",
        )

        # Check if the agent branched
        current = t.current_branch
        print(f"\n  Branch after tangent: {current}")

        if current and current != "main":
            # Agent successfully branched! Now compress and merge back.
            # This is done programmatically for reliability. In production
            # with a capable model (GPT-4, Claude), the LLM could do this
            # via compress/switch/merge tool calls in a single loop.
            compress_and_merge_tangent(
                t, current,
                "REST is an architectural style: stateless HTTP, resource URIs, "
                "standard verbs (GET/POST/PUT/DELETE), and uniform interface.",
            )
        else:
            print("  (Agent answered inline -- model didn't branch)")

        # --- Phase 3: Resume design (back on main) ---
        print(f"\n\n=== Phase 3: Resume design (on {t.current_branch}) ===\n")
        run_agent_loop(
            t, executor,
            "OK, back to the API design. What status codes should each "
            "endpoint return? And should we version the API?",
        )

        # --- Final state ---
        print("\n\n=== Final context on main ===\n")
        t.compile().pprint(style="compact")

        branches = [b.name for b in t.list_branches()]
        msgs = t.compile().to_dicts()
        print(f"\n  Branch: {t.current_branch}  |  Messages: {len(msgs)}  |  "
              f"All branches: {branches}")
        print()
        print("  The tangent was answered on a branch, compressed to one line,")
        print("  and merged back. Main stayed focused on API design decisions.")


if __name__ == "__main__":
    main()
