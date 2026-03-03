"""Edit History

Chat with an LLM, then iteratively refine a response via edits.
Use edit_history() to see every version of a commit, and restore()
to roll back when the edits go too far.

Demonstrates: t.revise(), t.assistant(edit=), edit_history(),
              restore(), get_content(), pprint(style="chat"),
              response.pprint()
"""

import sys
from pathlib import Path

from tract import Tract

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import cerebras as llm  

MODEL_ID = llm.small


def edit_history():
    print(f"\n{'=' * 60}")
    print("EDIT HISTORY")
    print("=" * 60)
    print()

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        t.system("You are a concise writing assistant. Keep answers under 2 sentences.")

        # --- Initial conversation ---

        print("=== Initial question ===\n")
        r1 = t.chat("Explain what a black hole is.")
        r1.pprint()
        original_hash = r1.commit_info.commit_hash

        # --- Ask a follow-up so we have surrounding context ---

        print("=== Follow-up ===\n")
        r2 = t.chat("How are they detected?")
        r2.pprint()

        # --- Edit the first response to add more detail ---
        # t.revise() asks the LLM to rewrite a commit, then applies the
        # result as an EDIT. Under the hood it: (1) calls chat() with your
        # prompt, (2) creates an EDIT commit targeting the original, and
        # (3) SKIPs the intermediate user/assistant commits so only the
        # edit survives in compiled context.

        print("=== Edit 1: ask LLM to improve the first answer ===\n")
        e1 = t.revise(
            original_hash,
            "Please rewrite your first answer about black holes to also "
            "mention the event horizon. Keep it to 2 sentences.",
            message="Add event horizon detail",
        )
        print(f"  Edit commit: {e1.commit_info.commit_hash[:8]}")
        print(f"  Content: {t.get_content(e1.commit_info)}\n")

        # --- Edit again: further refinement ---

        print("=== Edit 2: manual refinement ===\n")
        e2 = t.assistant(
            "A black hole is a region of spacetime where gravity is so "
            "extreme that nothing, not even light, can escape past its "
            "event horizon. They form when massive stars collapse at the "
            "end of their life cycle.",
            edit=original_hash,
            message="Manual rewrite for clarity",
        )
        print(f"  Edit commit: {e2.commit_hash[:8]}")

        # --- View the full edit history ---
        # edit_history() returns [original, edit1, edit2, ...] in order.
        # This is a lightweight query -- no full context compilation needed.

        print("\n=== Edit history for the first answer ===\n")
        history = t.edit_history(original_hash)
        for i, version in enumerate(history):
            label = "ORIGINAL" if i == 0 else f"EDIT {i}"
            content = t.get_content(version)
            print(f"  v{i} ({label}) [{version.commit_hash[:8]}]")
            print(f"     {content}")
            print()

        print(f"  Total versions: {len(history)}")

        # --- The compiled context uses the latest edit automatically ---

        print("\n=== Compiled context (latest edit wins) ===\n")
        t.compile().pprint(style="chat")

        # --- Restore: the manual edit was too verbose, go back to v1 ---
        # restore() creates a NEW edit pointing to the original, with the
        # content from the specified version. The full history is preserved.

        print("\n=== Restore to v1 (LLM-improved version) ===\n")
        restored = t.restore(original_hash, version=1)
        print(f"  Restore commit: {restored.commit_hash[:8]}")
        print(f"  edit_target: {restored.edit_target[:8]} (points to original)")
        print(f"  Content: {t.get_content(restored)}\n")

        # --- Verify the restore is tracked in history ---

        print("=== Updated edit history (restore is itself an edit) ===\n")
        updated_history = t.edit_history(original_hash)
        for i, version in enumerate(updated_history):
            msg = version.message or "(no message)"
            if len(msg) > 60:
                msg = msg[:57] + "..."
            print(f"  v{i} [{version.commit_hash[:8]}] {msg}")
        print(f"\n  Total versions: {len(updated_history)} "
              f"(was {len(history)}, +1 from restore)")

        # --- Surrounding context is unaffected ---

        print("\n=== Full compiled context after restore ===\n")
        ctx = t.compile()
        ctx.pprint(style="chat")
        print(f"\n  The follow-up answer about detection is still intact.")
        print(f"  Only the black hole definition was rolled back to v1.")


def main():
    edit_history()


if __name__ == "__main__":
    main()
