"""Agentic PendingMerge: consult() sends the pending state to an LLM which
autonomously controls a merge conflict.

Demonstrated actions:
    approve          -- execute the merge with current resolutions
    reject           -- abandon the merge, leave branches unchanged
    edit_resolution  -- patch a single conflict resolution by key
    set_resolution   -- overwrite/create a resolution from scratch
    edit_guidance    -- change the guidance text for the next retry
    retry            -- re-resolve ALL conflicts via LLM with new guidance
    validate         -- check that every conflict has a non-empty resolution

Skipped (TUI-only):
    edit_interactive -- opens an interactive CLI menu; not suitable for agents

Three scenarios:
    A) Validate -> edit_resolution -> re-validate -> approve
    B) set_resolution from scratch -> edit_guidance + retry -> approve
    C) Validate -> reject
"""

import sys
from pathlib import Path

from tract import Tract
from tract.hooks.merge import PendingMerge
from tract.models.commit import CommitInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import groq as llm  # noqa: E402

MODEL_ID = llm.large


SYSTEM_PROMPT = (
    "You are a merge conflict resolution agent. "
    "You will receive the state of a pending merge operation "
    "and a set of tools. Use EXACTLY ONE tool call to carry out "
    "the user's instruction. Respond ONLY with a tool call."
)


# ---------------------------------------------------------------------------
# Helper: build a tract with a merge conflict on the assistant message
# ---------------------------------------------------------------------------

def build_conflict_tract() -> Tract:
    """Create a Tract with a BOTH_EDIT conflict ready to merge.

    main edits the assistant message one way, feature edits it another.
    Returns an open Tract positioned on main with feature ready to merge.
    """
    t = Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    )

    # Shared history
    t.system("You are a knowledgeable science tutor.")
    t.user("Explain how photosynthesis works.")
    asst_ci: CommitInfo = t.assistant(
        "Photosynthesis converts sunlight into chemical energy."
    )
    asst_hash: str = asst_ci.commit_hash

    # Feature branch: more detailed version
    t.branch("feature")
    t.assistant(
        edit=asst_hash,
        text=(
            "Photosynthesis is the process by which plants, algae, and "
            "cyanobacteria convert sunlight, water, and CO2 into glucose "
            "and oxygen through light-dependent and light-independent reactions."
        ),
    )

    # Back to main: different edit on the same message
    t.switch("main")
    t.assistant(
        edit=asst_hash,
        text=(
            "Photosynthesis uses chlorophyll to capture light energy, "
            "splitting water molecules and fixing carbon dioxide into "
            "sugars via the Calvin cycle."
        ),
    )

    return t


# ===================================================================
# SCENARIO A: validate -> edit_resolution -> re-validate -> approve
# ===================================================================

def scenario_a() -> None:
    print("=" * 70)
    print("SCENARIO A: validate -> edit_resolution -> re-validate -> approve")
    print("=" * 70)

    t = build_conflict_tract()

    try:
        pending: PendingMerge = t.merge("feature", review=True)
        print("\n  Initial PendingMerge:")
        pending.pprint()

        # Step 1: Agent validates -- should pass (LLM already resolved)
        print("\n  Step 1: Agent validates the current resolutions")
        pending.consult(
            "Validate the current merge resolutions to check if they are "
            "complete and non-empty.",
            system_prompt=SYSTEM_PROMPT,
        )

        # Step 2: Agent edits the resolution to improve it
        print("\n  Step 2: Agent edits the resolution")
        first_key: str = list(pending.resolutions.keys())[0]
        current_res = pending.resolutions[first_key]
        print(f"    Current resolution ({first_key[:8]}): {current_res[:80]}")

        pending.consult(
            f"The resolution for conflict key '{first_key}' should be improved. "
            f"Use edit_resolution to replace it with: "
            f"'Photosynthesis is the biological process where chlorophyll-containing "
            f"organisms convert sunlight, water, and CO2 into glucose and oxygen "
            f"through light-dependent reactions (in thylakoids) and the Calvin cycle "
            f"(in the stroma).'",
            system_prompt=SYSTEM_PROMPT,
        )

        print(f"    Updated resolution: {pending.resolutions[first_key][:80]}...")

        # Step 3: Agent re-validates after the edit
        print("\n  Step 3: Agent re-validates after edit")
        pending.consult(
            "Validate the resolutions again to confirm the edit is acceptable.",
            system_prompt=SYSTEM_PROMPT,
        )

        # Step 4: Agent approves the merge
        print("\n  Step 4: Agent approves the merge")
        pending.consult(
            "All resolutions look good. Approve the merge.",
            system_prompt=SYSTEM_PROMPT,
        )

        print(f"\n  Final status: {pending.status}")
        pending.pprint()

        print("\n  Compiled context after merge:")
        t.compile().pprint(style="chat")

    finally:
        t.close()


# ===================================================================
# SCENARIO B: set_resolution + edit_guidance + retry -> approve
# ===================================================================

def scenario_b() -> None:
    print("\n" + "=" * 70)
    print("SCENARIO B: set_resolution -> edit_guidance + retry -> approve")
    print("=" * 70)

    t = build_conflict_tract()

    try:
        pending: PendingMerge = t.merge("feature", review=True)
        print("\n  Initial PendingMerge:")
        pending.pprint()

        # Step 1: Agent wipes resolutions and provides its own via set_resolution
        print("\n  Step 1: Agent uses set_resolution to provide a fresh resolution")
        first_key: str = list(pending.resolutions.keys())[0]

        # Clear existing resolutions to simulate starting from scratch
        pending.resolutions.clear()
        print(f"    Cleared all resolutions (simulating review=True without resolver)")

        pending.consult(
            f"There are no resolutions yet. Use set_resolution with key "
            f"'{first_key}' and content 'PLACEHOLDER -- needs LLM re-resolution' "
            f"to create a temporary placeholder.",
            system_prompt=SYSTEM_PROMPT,
        )

        print(f"    Placeholder resolution: {pending.resolutions.get(first_key, 'MISSING')}")

        # Step 2: Agent edits guidance and retries LLM resolution
        print("\n  Step 2: Agent updates guidance, then retries LLM resolution")
        pending.consult(
            "Use edit_guidance to set the guidance to: "
            "'Combine both versions into a comprehensive explanation that covers "
            "chlorophyll, light-dependent reactions, Calvin cycle, and the "
            "products (glucose + oxygen). Keep it under 3 sentences.'",
            system_prompt=SYSTEM_PROMPT,
        )

        print(f"    Guidance: {pending.guidance}")
        print(f"    Guidance source: {pending.guidance_source}")

        # Now retry with the updated guidance
        print("\n  Step 3: Agent retries to re-resolve conflicts via LLM")
        pending.consult(
            "Now retry the conflict resolution so the LLM re-resolves all "
            "conflicts using the updated guidance.",
            system_prompt=SYSTEM_PROMPT,
        )

        for key, res in pending.resolutions.items():
            print(f"    Resolution ({key[:8]}): {res[:80]}...")

        # Step 4: Agent approves
        print("\n  Step 4: Agent approves the merge")
        pending.consult(
            "The LLM re-resolved the conflicts. Approve the merge.",
            system_prompt=SYSTEM_PROMPT,
        )

        print(f"\n  Final status: {pending.status}")
        pending.pprint()

        print("\n  Compiled context after merge:")
        t.compile().pprint(style="chat")

    finally:
        t.close()


# ===================================================================
# SCENARIO C: validate -> reject
# ===================================================================

def scenario_c() -> None:
    print("\n" + "=" * 70)
    print("SCENARIO C: validate -> reject")
    print("=" * 70)

    t = build_conflict_tract()

    try:
        pending: PendingMerge = t.merge("feature", review=True)
        print("\n  Initial PendingMerge:")
        pending.pprint()

        # Step 1: Agent validates
        print("\n  Step 1: Agent validates")
        pending.consult(
            "Validate the current merge resolutions.",
            system_prompt=SYSTEM_PROMPT,
        )

        # Step 2: Agent decides the merge is unwanted and rejects it
        print("\n  Step 2: Agent rejects the merge")
        pending.consult(
            "After reviewing the conflict, this merge should not proceed. "
            "The feature branch content diverges too much from main. "
            "Reject the merge with reason: "
            "'Feature branch explanation diverges from main branch style; "
            "needs alignment before merging.'",
            system_prompt=SYSTEM_PROMPT,
        )

        print(f"\n  Final status: {pending.status}")
        print(f"  Rejection reason: {pending.rejection_reason}")
        pending.pprint()

        # Verify branches are unchanged
        print("\n  Main branch is unchanged after rejection:")
        t.compile().pprint(style="chat")

    finally:
        t.close()


# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    scenario_a()
    scenario_b()
    scenario_c()
