"""
05 — Auto-Summarize Commit Messages
====================================

When you commit without a ``message=`` parameter, Tract can use an LLM to
generate a concise one-sentence commit message instead of truncating content.

Pass ``auto_summarize=`` to ``Tract.open()`` to enable it:
- ``True``: use the tract-level default model
- ``"model-name"``: use a specific (cheap) model
- ``LLMConfig(...)``: full control over the summarization config

This example shows all four modes.
"""

import sys
from pathlib import Path

import click

from tract import LLMConfig, Tract

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import cerebras as llm  

MODEL_ID = llm.large
MESSAGE_MODEL_ID = llm.small


# =============================================================================
# Parts 1-2 -- Manual: Auto-Summarize Modes
# =============================================================================

# --- 1. Cheapest: point auto_summarize at a small model ---
# One parameter does it all.  Uses the small model for commit messages
# while the main tract model stays large.

with Tract.open(
    api_key=llm.api_key,
    base_url=llm.base_url,
    model=MODEL_ID,
    auto_summarize=MESSAGE_MODEL_ID,
) as t:
    t.system("You are a helpful coding assistant specializing in Python.")
    t.user("How do I read a CSV file with pandas?")

    # Log shows clean messages like:
    #   "Set up Python coding assistant"
    #   "Ask how to read CSV with pandas"
    for entry in t.log():
        print(f"  {entry.commit_hash[:8]} {entry.message}")


# --- 2. Reuse the tract model ---
# If your tract model is already cheap, just pass True.

with Tract.open(
    api_key=llm.api_key,
    base_url=llm.base_url,
    model=MESSAGE_MODEL_ID,
    auto_summarize=True,
) as t:
    t.system("You are a helpful assistant.")
    t.chat("Tell me a joke.")

    print(t.log())

# --- 3. Full control with LLMConfig ---

with Tract.open(
    api_key=llm.api_key,
    base_url=llm.base_url,
    model=MODEL_ID,
    auto_summarize=LLMConfig(model=MESSAGE_MODEL_ID, temperature=0.0, max_tokens=60),
) as t:
    t.system("You are a helpful assistant.")
    t.chat("Tell me a joke.")
    print(t.log())

# --- 4. Off by default ---
# Without auto_summarize=, commit messages are truncated content previews.

with Tract.open(
    api_key=llm.api_key,
    base_url=llm.base_url,
    model=MODEL_ID,
) as t:
    t.system("You are a helpful assistant.")
    t.chat("Write a haiku.")
    print(t.log())
    # Message will be: "You are a helpful assistant."  (raw text, up to 500 chars)


# --- 5. Per-operation client (advanced) ---
# Use a completely different LLM provider for summarization.

# from openai import OpenAI
# summarize_client = OpenAI(api_key="sk-other-key")
# with Tract.open(api_key="sk-...", auto_summarize=True) as t:
#     t.configure_clients(summarize=summarize_client)
#     t.system("You are helpful.")


# =============================================================================
# Part 2 -- Interactive: Pick summarize mode interactively
# =============================================================================
# Let the user choose between cheap (small model), full (main model), or off
# (no auto-summarize) before opening the tract.

def part2_interactive():
    """Part 2: Interactive -- pick auto_summarize mode via click prompt."""
    print("=" * 60)
    print("PART 2 -- Interactive: Pick Summarize Mode")
    print("=" * 60)

    mode = click.prompt(
        "\n  Summarize mode",
        type=click.Choice(["cheap", "full", "off"]),
        default="cheap",
    )

    if mode == "cheap":
        auto_summarize = MESSAGE_MODEL_ID
        print(f"  -> Using cheap model ({MESSAGE_MODEL_ID}) for summaries")
    elif mode == "full":
        auto_summarize = True
        print(f"  -> Using main model ({MODEL_ID}) for summaries")
    else:
        auto_summarize = False
        print(f"  -> Auto-summarize disabled (raw text previews)")

    open_kwargs = dict(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    )
    if auto_summarize is not False:
        open_kwargs["auto_summarize"] = auto_summarize

    with Tract.open(**open_kwargs) as t:
        t.system("You are a helpful coding assistant.")
        t.user("How do I sort a list in Python?")

        print(f"\n  Log after commits:")
        for entry in t.log():
            print(f"    {entry.commit_hash[:8]} {entry.message}")

        if click.confirm("\n  Send a chat call to see an assistant commit?", default=True):
            t.chat("Show me an example with sorted().")
            print(f"\n  Updated log:")
            for entry in t.log():
                print(f"    {entry.commit_hash[:8]} {entry.message}")


def main():
    part2_interactive()


if __name__ == "__main__":
    main()
