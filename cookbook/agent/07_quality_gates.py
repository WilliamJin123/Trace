"""Agent Quality Gates

An LLM agent encounters middleware-based gates when transitioning between
stages. When the agent tries to transition but doesn't meet requirements,
it adapts by doing more work.

This demonstrates middleware as agent guardrails -- the agent cannot skip
stages or bypass quality checks, and must genuinely complete work before
advancing.

Tools exercised: configure, transition, commit, get_config, status,
                 log, compile, annotate, branch

Demonstrates: Middleware gates, agent adapting to gate failures,
              quality enforcement via BlockedError
"""

import io
import sys
from pathlib import Path

# Windows console encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from tract import Tract, BlockedError
from tract.toolkit import ToolConfig, ToolProfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import groq as llm

MODEL_ID = llm.large


# Tool profile: quality gate tools
GATE_PROFILE = ToolProfile(
    name="gate-navigator",
    tool_configs={
        "configure": ToolConfig(
            enabled=True,
            description=(
                "Set config key-value pairs on the DAG. Use for stage "
                "tracking, model settings, and custom keys."
            ),
        ),
        "transition": ToolConfig(
            enabled=True,
            description=(
                "Transition to a target branch/stage. Middleware gates may "
                "block the transition via BlockedError. If blocked, the "
                "agent must do more work and try again."
            ),
        ),
        "commit": ToolConfig(
            enabled=True,
            description=(
                "Record content into the tract. Use content_type='dialogue' for "
                "messages, 'artifact' for deliverables, 'reasoning' for analysis. "
                "Each commit counts toward gate thresholds."
            ),
        ),
        "get_config": ToolConfig(
            enabled=True,
            description=(
                "Resolve a config value from the DAG. Check 'stage' to "
                "see which stage you're in, or any other config key."
            ),
        ),
        "status": ToolConfig(
            enabled=True,
            description=(
                "Check current branch, HEAD, commit count, and token count. "
                "Use this to verify your position and assess gate readiness."
            ),
        ),
        "log": ToolConfig(
            enabled=True,
            description="View recent commits to understand what work has been done.",
        ),
        "compile": ToolConfig(
            enabled=True,
            description="View current compiled context.",
        ),
        "annotate": ToolConfig(
            enabled=True,
            description=(
                "Mark a commit as 'pinned' to protect it, or 'skip' to exclude."
            ),
        ),
        "branch": ToolConfig(
            enabled=True,
            description="Create a new branch for a workflow stage.",
        ),
    },
)


def _log_step(step_num, response):
    """on_step callback -- print step number."""
    print(f"    [step {step_num}]")


def main():
    if not llm.api_key:
        print("SKIPPED (no API key)")
        return

    print("=" * 70)
    print("Agent Quality Gates: middleware as agent guardrails")
    print("=" * 70)
    print()
    print("  The agent encounters transition gates that enforce quality.")
    print("  When blocked, it must do more work to meet the requirements.")
    print()

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        # Register tools from the profile
        tools = t.as_tools(profile=GATE_PROFILE)
        t.set_tools(tools)

        t.system(
            "You are a software engineer working through a gated workflow.\n\n"
            "GATE PROTOCOL:\n"
            "- Each stage has middleware gates that may block transitions if "
            "you haven't done enough work.\n"
            "- When a transition raises BlockedError, read the message to "
            "understand what's missing, do the required work, then try again.\n"
            "- Use commit to record work (artifacts, analysis, deliverables).\n"
            "- Use transition to advance when ready.\n"
            "- Do NOT skip stages or bypass gates."
        )

        # --- Phase 1: Set up gated workflow ---
        print("=== Phase 1: Set up gated stages ===\n")

        # Create the research stage with a middleware gate
        t.branch("research", switch=True)
        t.configure(stage="research")

        # Gate: require at least 3 commits before transitioning to impl
        def research_gate(ctx):
            if ctx.target == "implementation":
                status = ctx.tract.status()
                if status.commit_count < 5:
                    raise BlockedError(
                        "pre_transition",
                        f"Need at least 3 research commits before implementation "
                        f"(currently {status.commit_count - 2} research commits)",
                    )

        t.use("pre_transition", research_gate)
        print("  Created 'research' branch with transition gate")

        # Create the implementation stage
        t.switch("main")
        t.branch("implementation", switch=True)
        t.configure(stage="implementation")
        print("  Created 'implementation' branch")
        t.switch("research")

        print(f"  Starting on: {t.current_branch}")
        print(f"  Branches: {[b.name for b in t.list_branches()]}")

        # --- Phase 2: Agent tries to transition too early ---
        print("\n\n=== Phase 2: Agent attempts premature transition ===\n")
        result = t.run(
            "You are on the 'research' stage. There is a gate requiring at "
            "least 3 commits before you can transition to 'implementation'.\n\n"
            "First, try to transition to 'implementation' immediately to see "
            "the gate block you. Then, do the required research work:\n"
            "1. Commit a research artifact about API authentication options\n"
            "2. Commit a research artifact about database schema design\n"
            "3. Commit a research artifact about error handling patterns\n\n"
            "After completing the research, try the transition again.",
            max_steps=15, on_step=_log_step,
        )
        result.pprint()

        # --- Phase 3: Show final state ---
        print("\n\n=== Final State ===\n")
        print(f"  Current branch: {t.current_branch}")
        branches = [b.name for b in t.list_branches()]
        print(f"  All branches: {branches}")

        status = t.status()
        print(f"  Commits: {status.commit_count}")
        print(f"  Tokens: {status.token_count}")

        print("\n  Current context:")
        t.compile().pprint(style="compact")


if __name__ == "__main__":
    main()
