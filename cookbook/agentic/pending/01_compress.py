"""Agent-controlled compression: consult() sends the pending state to an LLM
which autonomously decides how to handle it.

Demonstrates every PendingCompress action through consult():
  - validate: check summary quality
  - edit_summary: replace a summary at a given index
  - edit_guidance: steer future retries
  - retry: re-generate a summary with guidance
  - approve / reject: finalize the decision
"""

import sys
from pathlib import Path

from tract import Priority, Tract
from tract.hooks.compress import PendingCompress

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import groq as llm

MODEL_ID = llm.large


# =====================================================================
# Helper
# =====================================================================

def _seed_conversation(t: Tract) -> None:
    """Build a multi-turn support conversation to give compress something to work with."""
    sys_ci = t.system(
        "You are a customer support agent for TechFlow, a project management "
        "SaaS platform. You help users troubleshoot issues with exports, "
        "integrations, and team workflows."
    )
    t.annotate(sys_ci.commit_hash, Priority.PINNED)

    t.chat(
        "Hi, I can't export my project reports to PDF. The button just spins "
        "and nothing happens. I've tried waiting 5 minutes.",
        max_tokens=500,
    )
    t.chat(
        "I'm on Chrome, macOS Sonoma. The project has about 200 tasks with "
        "file attachments totaling around 2GB.",
        max_tokens=500,
    )
    t.chat(
        "Tried Firefox too -- same issue. Is there a file size limit for "
        "exports? Our team really needs this report.",
        max_tokens=500,
    )
    t.chat(
        "Can you just email me the report directly? My deadline is tomorrow "
        "and I need the burndown charts for the stakeholder meeting.",
        max_tokens=500,
    )


SYSTEM_PROMPT = (
    "You are a context management agent responsible for reviewing "
    "compression operations on LLM conversation histories. You "
    "evaluate summaries for quality, completeness, and accuracy. "
    "Use the provided tools to take action. Always call exactly "
    "one tool -- never respond with plain text."
)


# =====================================================================
# SCENARIO A -- Validate, find issue, edit summary, re-validate, approve
# =====================================================================

def scenario_a() -> None:
    """Agent validates summaries, fixes a problem, then approves."""
    print("=" * 60)
    print("SCENARIO A -- Validate -> Edit Summary -> Re-validate -> Approve")
    print("=" * 60)
    print()
    print("  The agent validates the compression summaries. When it finds")
    print("  an issue (we inject a bad summary), it edits the summary,")
    print("  re-validates, and then approves.")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        _seed_conversation(t)

        print(f"\n  Conversation BEFORE compression:")
        ctx_before = t.compile()
        print(f"    {len(ctx_before.messages)} messages, {ctx_before.token_count} tokens")

        pending: PendingCompress = t.compress(target_tokens=150, review=True)

        print(f"\n  PendingCompress created:")
        pending.pprint()

        # --- Step 1: Sabotage a summary to give the agent something to find ---
        original_summary = pending.summaries[0]
        pending.edit_summary(0, "Stuff happened.")
        print(f"\n  [Injected bad summary at index 0: 'Stuff happened.']")

        # --- Step 2: Ask agent to validate ---
        print(f"\n  Step 1 -- Agent validates:")
        result = pending.consult(
            "Validate the compression summaries to check for quality issues. "
            "Call the validate action.",
            system_prompt=SYSTEM_PROMPT,
        )
        if result is not None:
            print(f"    Result: {result}")

        # --- Step 3: Ask agent to fix the bad summary ---
        print(f"\n  Step 2 -- Agent edits the bad summary:")
        pending.consult(
            "The summary at index 0 is too vague ('Stuff happened.'). "
            "Replace it with a proper summary that captures the key details: "
            "the user has a PDF export issue on Chrome/macOS with a large "
            "project (200 tasks, 2GB attachments). Use the edit_summary tool.",
            system_prompt=SYSTEM_PROMPT,
        )
        print(f"    Summary after edit: {pending.summaries[0][:80]}...")

        # --- Step 4: Agent re-validates ---
        print(f"\n  Step 3 -- Agent re-validates:")
        result = pending.consult(
            "Validate the summaries again to confirm the fix resolved the issue.",
            system_prompt=SYSTEM_PROMPT,
        )
        if result is not None:
            print(f"    Result: {result}")

        # --- Step 5: Agent approves ---
        print(f"\n  Step 4 -- Agent approves:")
        result = pending.consult(
            "The summaries look good now. Approve the compression to finalize.",
            system_prompt=SYSTEM_PROMPT,
        )
        print(f"    Status: {pending.status}")

        print(f"\n  Conversation AFTER compression:")
        ctx_after = t.compile()
        print(f"    {len(ctx_after.messages)} messages, {ctx_after.token_count} tokens")
        ctx_after.pprint(style="compact")


# =====================================================================
# SCENARIO B -- Edit guidance + retry to steer compression
# =====================================================================

def scenario_b() -> None:
    """Agent uses edit_guidance and retry to steer summary generation."""
    print(f"\n{'=' * 60}")
    print("SCENARIO B -- Edit Guidance -> Retry -> Approve")
    print("=" * 60)
    print()
    print("  The agent reviews the summaries and decides they lack focus.")
    print("  It sets guidance via edit_guidance, then retries the summary")
    print("  generation with the new guidance, and approves.")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        _seed_conversation(t)

        pending: PendingCompress = t.compress(target_tokens=150, review=True)

        print(f"\n  Initial summaries:")
        for i, s in enumerate(pending.summaries):
            print(f"    [{i}] {s[:100]}{'...' if len(s) > 100 else ''}")

        # --- Step 1: Agent sets guidance ---
        print(f"\n  Step 1 -- Agent sets guidance to focus the retry:")
        pending.consult(
            "The summaries should focus on technical details: the specific "
            "bug (PDF export failure), environment (Chrome, macOS, 200 tasks, "
            "2GB), and the user's deadline. Set guidance using edit_guidance "
            "with text: 'Focus on technical issue details: PDF export bug, "
            "browser/OS environment, project size, and the user deadline. "
            "Omit pleasantries and conversational filler.'",
            system_prompt=SYSTEM_PROMPT,
        )
        print(f"    Guidance set: {pending.guidance}")
        print(f"    Guidance source: {pending.guidance_source}")

        # --- Step 2: Agent retries summary 0 with guidance ---
        print(f"\n  Step 2 -- Agent retries summary generation with guidance:")
        pending.consult(
            "Now retry the summary at index 0 so it regenerates using the "
            "new guidance. The guidance will automatically be included in "
            "the retry prompt.",
            system_prompt=SYSTEM_PROMPT,
        )
        print(f"\n  Summary after retry:")
        for i, s in enumerate(pending.summaries):
            print(f"    [{i}] {s[:100]}{'...' if len(s) > 100 else ''}")
        print(f"    Tokens: {pending.original_tokens} -> {pending.estimated_tokens}")

        # --- Step 3: Agent approves ---
        print(f"\n  Step 3 -- Agent approves the guided compression:")
        result = pending.consult(
            "The retried summary now focuses on technical details. "
            "Approve the compression.",
            system_prompt=SYSTEM_PROMPT,
        )
        print(f"    Status: {pending.status}")

        print(f"\n  Conversation AFTER guided compression:")
        ctx_after = t.compile()
        print(f"    {len(ctx_after.messages)} messages, {ctx_after.token_count} tokens")
        ctx_after.pprint(style="compact")


# =====================================================================
# SCENARIO C -- Agent rejects (too much information lost)
# =====================================================================

def scenario_c() -> None:
    """Agent decides the compression loses too much and rejects it."""
    print(f"\n{'=' * 60}")
    print("SCENARIO C -- Validate -> Reject (Information Loss)")
    print("=" * 60)
    print()
    print("  The agent reviews the compression and decides that critical")
    print("  details would be lost. It rejects with a reason, leaving the")
    print("  original conversation intact.")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        _seed_conversation(t)

        print(f"\n  Conversation BEFORE compression attempt:")
        ctx_before = t.compile()
        print(f"    {len(ctx_before.messages)} messages, {ctx_before.token_count} tokens")

        pending: PendingCompress = t.compress(target_tokens=150, review=True)

        # Show what the agent sees
        state = pending.to_dict()
        print(f"\n  Agent sees {len(state['available_actions'])} available actions:")
        print(f"    {state['available_actions']}")
        print(f"\n  Token reduction: {pending.original_tokens} -> {pending.estimated_tokens}")
        if pending.original_tokens > 0:
            pct = int((1 - pending.estimated_tokens / pending.original_tokens) * 100)
            print(f"    ({pct}% reduction)")

        # --- Agent validates first ---
        print(f"\n  Step 1 -- Agent validates:")
        result = pending.consult(
            "Validate the compression summaries for quality.",
            system_prompt=SYSTEM_PROMPT,
        )
        if result is not None:
            print(f"    Result: {result}")

        # --- Agent decides to reject ---
        print(f"\n  Step 2 -- Agent rejects the compression:")
        pending.consult(
            "After reviewing the summaries, I believe this compression loses "
            "too much critical detail about the user's specific environment "
            "(Chrome, macOS Sonoma, 2GB attachments) and their urgent deadline "
            "(stakeholder meeting tomorrow). These details are essential for "
            "the support agent to provide accurate help. Reject this compression "
            "with a clear reason explaining what information would be lost.",
            system_prompt=SYSTEM_PROMPT,
        )
        print(f"    Status: {pending.status}")
        print(f"    Reason: {pending.rejection_reason}")

        # Show context is unchanged
        print(f"\n  Conversation AFTER rejection (unchanged):")
        ctx_after = t.compile()
        print(f"    {len(ctx_after.messages)} messages, {ctx_after.token_count} tokens")
        assert ctx_before.token_count == ctx_after.token_count, "Context should be unchanged"
        print(f"    (token count unchanged -- rejection preserved the full context)")


# =====================================================================
# Main
# =====================================================================

def main() -> None:
    if not llm.api_key:
        print("ERROR: No API key configured. Set GROQ_API_KEY in .env")
        print("See cookbook/_providers.py for provider configuration.")
        return

    print()
    print("Agent-Controlled Compression")
    print("consult() sends PendingCompress state to an LLM which")
    print("autonomously decides: validate, edit, retry, approve, or reject.")
    print()

    scenario_a()
    scenario_b()
    scenario_c()

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print()
    print("  Scenario A: validate -> edit_summary -> validate -> approve")
    print("    Agent found a bad summary, fixed it, confirmed the fix, approved.")
    print()
    print("  Scenario B: edit_guidance -> retry -> approve")
    print("    Agent steered compression by setting guidance, re-generated, approved.")
    print()
    print("  Scenario C: validate -> reject")
    print("    Agent decided compression would lose critical details, rejected.")
    print()
    print("  Key pattern: consult() sends to_dict() + to_tools() to an LLM,")
    print("  parses the tool call, and dispatches via apply_decision().")
    print()


if __name__ == "__main__":
    main()
