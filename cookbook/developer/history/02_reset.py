"""Reset and Undo Reset

Manual reset -- permanently rolls back, then undo via ORIG_HEAD.

Demonstrates: reset(), ORIG_HEAD undo, compile(), pprint(style="chat")
"""

import sys
from pathlib import Path

from tract import Tract

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import groq as llm  

MODEL_ID = llm.small


# =============================================================================
# Manual: reset() permanently rolls back
# =============================================================================

def manual_rollback():
    print("=" * 60)
    print("Manual: Permanent Rollback with reset()")
    print("=" * 60)
    print()
    print("  Build a conversation, then reset() to an earlier commit.")
    print("  Later turns become orphaned -- invisible to compile().")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        t.system("You are a concise geography tutor. One sentence answers.")

        r1 = t.chat("What are the 3 largest countries by area?")
        early_hash = r1.commit_info.commit_hash

        t.chat("Which of those has the highest population density?")
        t.chat("What's the capital of that country?")

        print("\n  Full conversation (7 messages):")
        t.compile().pprint(style="chat")

        # Permanently roll back to turn 1
        print(f"\n  Resetting to turn 1 ({early_hash[:8]})...\n")
        t.reset(early_hash)

        print("  After reset:")
        ctx = t.compile()
        ctx.pprint(style="chat")
        print(f"\n  {len(ctx.messages)} messages -- turns 2-3 are orphaned.")

        # --- Undo the reset via ORIG_HEAD ---

        print("\n  Undoing reset via ORIG_HEAD...\n")
        t.reset("ORIG_HEAD")

        print("  After undo:")
        ctx = t.compile()
        ctx.pprint(style="chat")
        print(f"\n  {len(ctx.messages)} messages -- all turns restored.")

        # --- Continue the conversation from the restored state ---

        print("\n  Continuing with one more question...\n")
        t.chat("What language is most widely spoken there?")

        ctx = t.compile()
        ctx.pprint(style="chat")


if __name__ == "__main__":
    manual_rollback()
