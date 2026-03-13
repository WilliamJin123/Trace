"""Research Pipeline: ingest -> organize -> synthesize

An agent-driven research workflow. The agent ingests information, organizes
it with tags and metadata, and synthesizes findings -- all governed by config
for compile strategies and middleware gates for transitions.

Stages:
  ingest    -- full compile strategy, gather raw information
  organize  -- tag taxonomy, metadata classification
  synthesize -- adaptive compile, produce final synthesis

Demonstrates: tagging tools, metadata tools, transition gates with commit
              thresholds, agent-driven stage navigation, compile strategies

Requires: LLM API key (uses Cerebras provider)
"""

import sys
from pathlib import Path

from tract import Tract, BlockedError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import cerebras as llm
from _logging import StepLogger

MODEL_ID = llm.large


def main():
    if not llm.api_key:
        print("SKIPPED (no API key -- set CEREBRAS_API_KEY)")
        return

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        # =============================================================
        # Stage config and transition gates
        # =============================================================

        print("=== Setting Up Research Pipeline ===\n")

        # Initial stage config
        t.configure(
            stage="ingest",
            compile_strategy="full",
            temperature=0.7,
        )

        # Transition gates via middleware
        def organize_gate(ctx):
            if ctx.target != "organize":
                return
            count = len(ctx.tract.log())
            if count < 6:
                raise BlockedError(
                    "pre_transition",
                    [f"Need >= 6 commits for organize (have {count})"],
                )

        def synthesize_gate(ctx):
            if ctx.target != "synthesize":
                return
            count = len(ctx.tract.log())
            if count < 3:
                raise BlockedError(
                    "pre_transition",
                    [f"Need >= 3 commits for synthesize (have {count})"],
                )

        t.use("pre_transition", organize_gate)
        t.use("pre_transition", synthesize_gate)

        print(f"  Initial configs: {t.get_all_configs()}")

        # =============================================================
        # Register tags the agent can use
        # =============================================================

        for tag_name in ["source", "primary", "secondary", "comparison", "synthesis"]:
            t.register_tag(tag_name)

        print(f"  Registered 5 research tags")

        # =============================================================
        # System prompt: describe the research workflow
        # =============================================================

        t.system(
            "You are a research assistant working through a structured pipeline.\n\n"
            "PIPELINE STAGES:\n"
            "1. INGEST -- Commit research facts using the commit tool. "
            "Include tags=['source'] in your commit calls to tag them.\n"
            "2. ORGANIZE -- Use create_metadata to store structured taxonomies.\n"
            "3. SYNTHESIZE -- Produce a final comparative summary via commit.\n\n"
            "IMPORTANT: The primary tool is commit(). Use it to save each fact.\n"
            "Use transition to advance between stages.\n"
            "Complete all three stages."
        )

        # =============================================================
        # Seed some initial research content
        # =============================================================

        t.user("Topic: Compare database indexing strategies -- B-trees, "
               "hash indexes, and LSM trees.")

        # =============================================================
        # Run: agent drives through ingest -> organize -> synthesize
        # =============================================================

        print("\n=== Running Agent (ingest -> organize -> synthesize) ===\n")

        log = StepLogger()

        result = t.run(
            "Research database indexing strategies. Use commit() to save each fact:\n"
            "1. commit(content={content_type:'dialogue', role:'assistant', "
            "text:'B-trees: balanced, O(log n) lookups, good for range queries'}, "
            "tags=['source'])\n"
            "2. Same pattern for hash indexes: O(1) point lookups, no range support\n"
            "3. Same pattern for LSM trees: write-optimized, compaction-based\n\n"
            "After committing 3+ facts, call transition(target='organize').\n"
            "In organize, use create_metadata to classify strategies.\n"
            "Then transition(target='synthesize') and commit a comparative summary.",
            max_steps=20,
            profile="full",
            tool_names=["commit", "transition",
                        "create_metadata", "get_config", "status"],
            on_step=log.on_step,
            on_tool_result=log.on_tool_result,
        )

        result.pprint()

        # =============================================================
        # Show final state
        # =============================================================

        print(f"\n=== Final State ===\n")

        print(f"  Stage: {t.get_config('stage')}")
        print(f"  Branch: {t.current_branch}")

        print(f"\n  Branches:")
        for b in t.list_branches():
            marker = "*" if b.is_current else " "
            print(f"    {marker} {b.name}")

        print(f"\n  Registered tags:")
        for entry in t.list_tags():
            print(f"    {entry['name']:20s} count={entry['count']}")

        print(f"\n  Log (last 10 commits):")
        for ci in t.log()[-10:]:
            tags_str = f" [{', '.join(ci.tags)}]" if ci.tags else ""
            print(f"    {ci.commit_hash[:8]}  {ci.content_type:10s}{tags_str}  "
                  f"{(ci.message or '')[:40]}")


if __name__ == "__main__":
    main()


# --- See also ---
# Coding workflow:       workflows/01_coding_assistant.py
# Customer support:      workflows/03_customer_support.py
# Tagging patterns:      agent/04_knowledge_organization.py
