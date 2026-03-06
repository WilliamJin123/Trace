"""Self-Regulating Agent

An LLM agent that controls its own behavior using the three primitives:

  1. configure   -- sets its own parameters (temperature, strategy)
  2. directive   -- writes standing instructions for itself (deduplicated)
  3. create_middleware -- generates Python validation code at runtime

The developer sets up the tract and gives the agent the tools. The agent
decides what rules it needs, writes them as config/directives/middleware,
and enforces them on itself.

Key pattern: the agent creates a regex middleware to validate its own
commit messages, then updates its own directives as the task evolves.

Tools exercised: configure, directive, create_middleware, remove_middleware,
                 commit, get_config, status, transition

Demonstrates: Agent self-configuration, agent-generated middleware,
              directive override-by-name, full self-regulation loop

Requires: LLM API key (uses Groq provider)
"""

import io
import sys
from pathlib import Path

# Windows console encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from tract import Tract, BlockedError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import groq as llm

MODEL_ID = llm.large


def main():
    if not llm.api_key:
        print("SKIPPED (no API key -- set GROQ_API_KEY)")
        return

    print("=" * 70)
    print("Self-Regulating Agent")
    print("=" * 70)
    print()
    print("  The agent configures its own behavior, writes its own directives,")
    print("  and creates its own middleware guards -- all via tools.")
    print()

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        # Give the agent self-regulation tools + basic context tools
        tools = t.as_tools(
            tool_names=[
                "configure", "directive", "create_middleware",
                "remove_middleware", "get_config", "commit",
                "status", "log", "transition",
            ],
            format="openai",
        )
        t.set_tools(tools)

        t.system(
            "You are an autonomous agent that regulates its own behavior.\n\n"
            "You have three self-regulation tools:\n"
            "1. configure -- set key-value settings (temperature, strategy, custom keys)\n"
            "2. directive -- set named standing instructions for yourself (deduplicated by name)\n"
            "3. create_middleware -- write Python code that validates your own operations\n\n"
            "Use these tools proactively:\n"
            "- When you start a new phase of work, configure appropriate settings\n"
            "- When you need behavioral rules, create directives\n"
            "- When you need enforcement, create middleware\n\n"
            "Middleware code must define handler(ctx). Available: BlockedError, re, json.\n"
            "Example: def handler(ctx):\\n    if 'bad' in (ctx.commit.message or ''):\\n"
            "        raise BlockedError('pre_commit', 'rejected')"
        )

        # --- Phase 1: Agent sets up its own rules ---
        print("=== Phase 1: Agent self-configures ===\n")
        result = t.run(
            "You're starting a documentation writing task. Set yourself up:\n\n"
            "1. Use configure to set: stage='drafting', temperature=0.8\n"
            "2. Use directive to create a 'format' directive: "
            "'All documentation must use markdown with headers, bullet points, "
            "and code examples.'\n"
            "3. Use directive to create a 'tone' directive: "
            "'Write in a clear, technical tone. Avoid jargon unless defining it.'\n"
            "4. Use get_config to verify your stage is 'drafting'\n"
            "5. Use status to check your current state",
            max_steps=10,
            on_step=lambda step, _: print(f"    [step {step}]"),
        )
        result.pprint()

        # --- Phase 2: Agent creates its own middleware ---
        print("\n\n=== Phase 2: Agent creates middleware guard ===\n")
        result = t.run(
            "Now create a middleware guard for your own commits. Use create_middleware "
            "to write a post_commit handler that tracks how many commits you've made. "
            "The handler should print a message when commit count exceeds 5.\n\n"
            "The code should be:\n"
            "def handler(ctx):\n"
            "    if ctx.commit:\n"
            "        print(f'[guard] commit {ctx.commit.commit_hash[:8]}')\n\n"
            "After creating the middleware, make 2-3 commits with documentation "
            "content (use commit with content_type='artifact', artifact_type='document').",
            max_steps=10,
            on_step=lambda step, _: print(f"    [step {step}]"),
        )
        result.pprint()

        # --- Phase 3: Agent overrides its own directive ---
        print("\n\n=== Phase 3: Agent updates its own directives ===\n")
        result = t.run(
            "The task has shifted from drafting to review. Update yourself:\n\n"
            "1. Use configure to set: stage='review', temperature=0.3\n"
            "2. Use directive to OVERRIDE 'tone' (same name, new text): "
            "'Be critical and precise. Flag any ambiguity or missing details.'\n"
            "3. Use get_config to verify stage='review'\n"
            "4. Use status to see your final state\n\n"
            "Note: because 'tone' is the same name as before, the old directive "
            "is automatically replaced -- only the new one appears in context.",
            max_steps=10,
            on_step=lambda step, _: print(f"    [step {step}]"),
        )
        result.pprint()

        # --- Final state ---
        print("\n\n=== Final State ===\n")
        print(f"  Branch: {t.current_branch}")
        print(f"  Configs: {t.get_all_configs()}")
        print(f"  Commits: {len(t.log())}")

        ctx = t.compile()
        print(f"\n  Compiled context: {len(ctx.messages)} messages, {ctx.token_count} tokens")
        print("\n  Messages with 'directive' or 'config':")
        for m in ctx.messages:
            if any(kw in m.content.lower() for kw in ["directive", "format", "tone", "critical"]):
                preview = m.content[:80].replace("\n", " ")
                print(f"    [{m.role}] {preview}...")


if __name__ == "__main__":
    main()


# --- See also ---
# Config & directives (no LLM):  getting_started/02_config_and_directives.py
# Middleware patterns (no LLM):   config_and_middleware/02_event_automation.py
# Quality gates (LLM):            agent/07_quality_gates.py
# Coding workflow (LLM):          workflows/01_coding_assistant.py
