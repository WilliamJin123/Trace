"""PendingTrigger -- LLM agent controlling trigger actions.

An LLM agent autonomously intercepts trigger-fired actions via the hook
system and exercises ALL PendingTrigger actions: approve, reject, and
modify_params.  The agent uses pending.consult(instruction) to let an LLM
decide what to do -- consult() handles to_dict(), to_tools(), the LLM
call, and apply_decision() internally.

Flow overview:

    trigger fires -> PendingTrigger created -> t.on("trigger", handler)
    -> handler calls pending.consult() -> LLM decides via tools

Scenario A: Agent modifies target_tokens then approves a compress trigger.
Scenario B: Agent decides the context is too important to compress and rejects.

Tools exercised: modify_params, approve, reject
Demonstrates: PendingTrigger lifecycle, consult() for LLM-driven decisions,
              multi-turn flows via max_turns, rejection with reasoning
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import groq as llm

from tract import CompressTrigger, Tract, TractConfig, TokenBudgetConfig
from tract.hooks.trigger import PendingTrigger

MODEL_ID = llm.large


# =====================================================================
# SCENARIO A: Agent modifies params then approves
# =====================================================================

def scenario_a_approve():
    """Agent intercepts a compress trigger, adjusts target_tokens, and approves."""
    print("=" * 60)
    print("SCENARIO A -- Agent Modifies Params and Approves")
    print("=" * 60)

    if not llm.api_key:
        print("\n  SKIPPED (no API key)")
        print("=" * 60)
        return

    config = TractConfig(token_budget=TokenBudgetConfig(max_tokens=200))

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
        config=config,
    ) as t:
        # Track what the agent decided
        decisions: list[dict] = []

        def agent_handler(pending: PendingTrigger) -> None:
            """Hook handler: use consult() to let an LLM decide."""
            print(f"\n  [hook] Trigger fired: {pending.trigger_name}")
            print(f"  [hook] Action type:   {pending.action_type}")
            print(f"  [hook] Reason:        {pending.reason}")
            print(f"  [hook] Params:        {pending.action_params}")

            # consult() with max_turns=2 allows modify_params then approve
            decision = pending.consult(
                "A compression trigger has fired. Inspect the action_params "
                "and reason. Set target_tokens to roughly 60% of the current "
                "threshold to leave headroom, then approve.",
                system_prompt=(
                    "You are a context management agent. A compression "
                    "trigger has fired. Use modify_params to adjust "
                    "target_tokens, then approve."
                ),
                max_turns=2,
            )
            decisions.append(decision)
            print(f"  [agent] Decision: {json.dumps(decision)}")
            print(f"  [agent] Params after consult: {pending.action_params}")
            print(f"  [agent] Status: {pending.status}")

        # Register the hook and trigger
        t.on("trigger", agent_handler, name="agent-approve")
        trigger = CompressTrigger(threshold=0.3, summary_content="Condensed context.")
        t.configure_triggers([trigger])

        # Seed enough messages to fire the trigger
        t.system("You are a research assistant tracking experiment results.")
        for i in range(8):
            t.user(f"Experiment {i}: measured value = {i * 3.14:.2f} units.")

        print(f"\n  Commits before compile: {len(t.log(limit=100))}")
        status = t.status()
        print(f"  Tokens before compile: {status.token_count}/{status.token_budget_max}")

        # compile() triggers evaluation -> fires hook -> agent decides
        ctx = t.compile()
        print(f"\n  After compile: {ctx.token_count} tokens, {len(ctx.messages)} messages")

        if decisions:
            print(f"\n  Agent reasoning: {decisions[0].get('reasoning', 'N/A')}")
        else:
            print("\n  (trigger did not fire -- threshold not reached)")

    print()


# =====================================================================
# SCENARIO B: Agent rejects the trigger
# =====================================================================

def scenario_b_reject():
    """Agent intercepts a compress trigger and rejects it to protect data."""
    print("=" * 60)
    print("SCENARIO B -- Agent Rejects the Trigger")
    print("=" * 60)

    if not llm.api_key:
        print("\n  SKIPPED (no API key)")
        print("=" * 60)
        return

    config = TractConfig(token_budget=TokenBudgetConfig(max_tokens=200))

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
        config=config,
    ) as t:
        rejections: list[dict] = []

        def agent_handler(pending: PendingTrigger) -> None:
            """Hook handler: agent rejects compression to protect data."""
            print(f"\n  [hook] Trigger fired: {pending.trigger_name}")
            print(f"  [hook] Action type:   {pending.action_type}")
            print(f"  [hook] Reason:        {pending.reason}")

            # consult() asks the LLM to reject via the reject tool
            decision = pending.consult(
                "A compression trigger wants to fire, but the user is "
                "actively analyzing critical experiment data. The data is "
                "too important to compress right now. Reject the trigger "
                "with a clear reason.",
                system_prompt=(
                    "You are a context management agent. A compression "
                    "trigger has fired but the context contains critical "
                    "experiment data that should NOT be compressed yet. "
                    "Always reject. Use the reject tool."
                ),
            )
            rejections.append(decision)
            print(f"  [agent] Decision: {json.dumps(decision)}")
            print(f"  [agent] Status: {pending.status}")
            print(f"  [agent] Rejection reason: {pending.rejection_reason}")

        # Register hook and trigger
        t.on("trigger", agent_handler, name="agent-reject")
        trigger = CompressTrigger(threshold=0.3, summary_content="Should not appear.")
        t.configure_triggers([trigger])

        # Seed critical experiment data
        t.system("You are tracking a live particle physics experiment.")
        for i in range(8):
            t.user(f"Detector reading {i}: {(i + 1) * 42} GeV, significance {i + 1} sigma.")

        status_before = t.status()
        print(f"\n  Tokens before compile: {status_before.token_count}/{status_before.token_budget_max}")

        # compile() triggers evaluation -> agent rejects -> no compression
        ctx = t.compile()
        status_after = t.status()

        print(f"\n  After compile: {ctx.token_count} tokens, {len(ctx.messages)} messages")
        print(f"  Tokens unchanged: {status_before.token_count == status_after.token_count}")

        if rejections:
            print(f"\n  Agent reasoning: {rejections[0].get('reason', 'N/A')}")
            print("  Result: compression was BLOCKED -- all data preserved.")
        else:
            print("\n  (trigger did not fire)")

    print()


# =====================================================================
# SCENARIO C: Manual walkthrough (no LLM required)
# =====================================================================

def scenario_c_manual():
    """Manual demonstration of all three PendingTrigger actions without LLM."""
    print("=" * 60)
    print("SCENARIO C -- Manual: All Three Actions (no LLM)")
    print("=" * 60)

    config = TractConfig(token_budget=TokenBudgetConfig(max_tokens=200))

    # -- 1. modify_params + approve ------------------------------------
    print("\n  1. modify_params + approve:")
    with Tract.open(config=config) as t:
        captured: list[PendingTrigger] = []

        def modify_and_approve(pending: PendingTrigger) -> None:
            captured.append(pending)
            print(f"     trigger_name:  {pending.trigger_name}")
            print(f"     action_type:   {pending.action_type}")
            print(f"     reason:        {pending.reason}")
            print(f"     action_params: {pending.action_params}")

            # Modify target_tokens before approving
            pending.modify_params({"target_tokens": 80})
            print(f"     after modify:  {pending.action_params}")
            pending.approve()
            print(f"     status:        {pending.status}")

        t.on("trigger", modify_and_approve, name="modify-approve")
        t.configure_triggers([CompressTrigger(threshold=0.3, summary_content="Summary.")])
        t.system("Instructions for the assistant.")
        for i in range(8):
            t.user(f"Message {i} with enough text to grow token count.")
        t.compile()

        if captured:
            print(f"     result:        approved with target_tokens={captured[0].action_params.get('target_tokens')}")

    # -- 2. reject -----------------------------------------------------
    print("\n  2. reject:")
    with Tract.open(config=config) as t:
        rejected_pending: list[PendingTrigger] = []

        def reject_handler(pending: PendingTrigger) -> None:
            rejected_pending.append(pending)
            pending.reject("Data is critical, do not compress.")
            print(f"     status:           {pending.status}")
            print(f"     rejection_reason: {pending.rejection_reason}")

        t.on("trigger", reject_handler, name="reject")
        t.configure_triggers([CompressTrigger(threshold=0.3, summary_content="Nope.")])
        t.system("Critical data tracking.")
        for i in range(8):
            t.user(f"Critical reading {i}.")
        ctx = t.compile()
        print(f"     messages after:   {len(ctx.messages)} (all preserved)")

    # -- 3. to_dict() inspection ---------------------------------------
    print("\n  3. to_dict() inspection:")
    with Tract.open(config=config) as t:
        def inspect_handler(pending: PendingTrigger) -> None:
            info = pending.to_dict()
            print(f"     keys: {sorted(info.keys())}")
            print(f"     operation:     {info['operation']}")
            print(f"     status:        {info['status']}")

            # Fields contain the trigger-specific data
            fields = info.get("fields", {})
            print(f"     trigger_name:  {fields.get('trigger_name')}")
            print(f"     action_type:   {fields.get('action_type')}")
            print(f"     action_params: {fields.get('action_params')}")
            print(f"     reason:        {fields.get('reason')}")

            # Available actions show what the agent can do
            print(f"     actions:       {info.get('available_actions')}")
            pending.approve()

        t.on("trigger", inspect_handler, name="inspect")
        t.configure_triggers([CompressTrigger(threshold=0.3, summary_content="Inspected.")])
        t.system("System setup.")
        for i in range(8):
            t.user(f"Filler message {i}.")
        t.compile()

    print()


def main():
    scenario_c_manual()
    scenario_a_approve()
    scenario_b_reject()


if __name__ == "__main__":
    main()


# --- See also ---
# cookbook/agentic/sidecar/01_triggers.py         -- All trigger types and autonomy spectrum
# cookbook/hooks/01_routing/01_three_tier.py       -- Three-tier hook routing
# cookbook/hooks/02_pending/01_compress_lifecycle.py -- PendingCompress lifecycle
