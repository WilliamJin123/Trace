"""Pin, Skip, and Reset Annotations

Control what the LLM sees without deleting history. Pin a system prompt so
it survives compression. Skip noisy tool output to slim down context. Reset
an annotation when you change your mind. All three are non-destructive —
the commits stay in history.

Demonstrates: annotate(hash, PINNED), annotate(hash, SKIP),
              annotate(hash, NORMAL), compile() reflects annotations,
              Priority enum values
"""

from tract import Priority, Tract


def main():
    t = Tract.open()

    # --- Build a conversation with a tool output in the middle ---

    sys_ci = t.system("You are a research assistant.")
    t.user("Find recent papers on transformer efficiency.")

    # Simulate a tool output — useful once, noisy after
    tool_ci = t.assistant(
        "[search_results]\n"
        "1. FlashAttention-2: Faster Attention with Better Parallelism (2023)\n"
        "2. Efficient Transformers: A Survey (2022)\n"
        "3. Mamba: Linear-Time Sequence Modeling (2023)\n"
        "... 47 more results ...",
    )

    t.user("Great, summarize the top 3.")
    t.assistant(
        "Here are the key papers:\n"
        "1. FlashAttention-2 reduces memory usage via tiling.\n"
        "2. The Efficient Transformers survey covers sparse/low-rank methods.\n"
        "3. Mamba replaces attention with selective state spaces."
    )

    # --- Pin the system prompt — it must survive compression ---

    t.annotate(sys_ci.commit_hash, Priority.PINNED, reason="system prompt")
    print(f"Pinned:  {sys_ci.commit_hash[:8]}  (system prompt)")

    # --- Skip the tool output — it's been summarized already ---

    t.annotate(tool_ci.commit_hash, Priority.SKIP, reason="already summarized")
    print(f"Skipped: {tool_ci.commit_hash[:8]}  (tool output)")

    # --- Compile: tool output is gone, everything else is visible ---

    ctx = t.compile()
    print(f"\n=== After SKIP: {len(ctx.messages)} messages (tool output hidden) ===\n")
    ctx.pprint()

    # --- Change your mind: un-skip the tool output ---

    t.annotate(tool_ci.commit_hash, Priority.NORMAL)
    print("Reset tool output back to NORMAL\n")

    ctx = t.compile()
    print(f"=== After reset: {len(ctx.messages)} messages (tool output restored) ===\n")
    ctx.pprint()

    t.close()


if __name__ == "__main__":
    main()
