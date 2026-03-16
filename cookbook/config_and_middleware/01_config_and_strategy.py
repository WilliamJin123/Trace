"""Config and Compile Strategy

t.config.set() commits key-value settings to the DAG. Well-known keys are
type-checked; unknown keys pass through for custom use.

  - Each configure() call commits one or more key-value pairs
  - When multiple calls set the same key, closest to HEAD wins (DAG precedence)
  - Query with t.config.get() or t.config.get_all()

The most common use: selecting the compile strategy that controls how
tract builds the LLM context window.

Well-known config keys:
  model, temperature, max_tokens, max_commit_tokens,
  auto_compress_threshold, compact_tools, compile_strategy,
  compile_strategy_k, handoff_summary_k

Demonstrates: t.config.set(), t.config.get(), t.config.get_all(),
              DAG precedence, compile_strategy, strategy comparison

No LLM required.
"""

from tract import Tract


def main() -> None:
    with Tract.open() as t:

        # --- Config as key-value store ---

        print("=== Config ===\n")

        t.config.set(model="gpt-4o")
        t.config.set(temperature=0.7)
        t.config.set(max_tokens=4096)

        print(f"  model:       {t.config.get('model')}")
        print(f"  temperature: {t.config.get('temperature')}")
        print(f"  max_tokens:  {t.config.get('max_tokens')}")

        # --- DAG precedence: closer to HEAD wins ---

        print("\n=== DAG Precedence ===\n")

        t.user("Hello, world!")
        t.assistant("Hi there!")

        # Override model -- new configure() call is closer to HEAD
        t.config.set(model="claude-sonnet")

        print(f"  model (overridden): {t.config.get('model')}")
        print(f"  temperature (unchanged): {t.config.get('temperature')}")
        print(f"  missing key:  {t.config.get('nonexistent')}")
        print(f"  with default: {t.config.get('nonexistent', 'fallback')}")

        # Complex values work too
        t.config.set(stop=["END", "DONE", "---"])
        print(f"  stop (list): {t.config.get('stop')}")

        # --- Build conversation for strategy demos ---

        print("\n=== Building History ===\n")

        t.system("You are a helpful assistant.")
        for i in range(8):
            t.user(f"Question {i + 1}: Tell me about topic {i + 1}.")
            t.assistant(f"Answer {i + 1}: Here is information about topic {i + 1}.")

        print(f"  Total commits: {len(t.search.log())}")

        # --- Compile strategy: full ---

        print("\n=== Strategy: full ===\n")

        t.config.set(compile_strategy="full")

        strategy = t.config.get("compile_strategy")
        ctx_full = t.compile(strategy=strategy)
        print(f"  {strategy}: {len(ctx_full.messages)} messages")

        # --- Compile strategy: messages (lightweight summaries) ---

        print("\n=== Strategy: messages (lightweight) ===\n")

        t.config.set(compile_strategy="messages", compile_strategy_k=5)

        strategy = t.config.get("compile_strategy")
        ctx_messages = t.compile(strategy=strategy)
        print(f"  {strategy}: {len(ctx_messages.messages)} messages (commit-message text only)")

        # --- Compile strategy: adaptive ---

        print("\n=== Strategy: adaptive ===\n")

        t.config.set(compile_strategy="adaptive")

        strategy = t.config.get("compile_strategy")
        k = t.config.get("compile_strategy_k")
        ctx_adaptive = t.compile(strategy=strategy, strategy_k=k)
        print(f"  {strategy} (k={k}): {len(ctx_adaptive.messages)} messages")

        # --- Comparison ---

        print("\n=== Strategy Comparison ===\n")

        # All strategies produce the same number of messages -- they differ
        # in *content detail*, not in message count.
        print(f"  full:     {len(ctx_full.messages)} messages (full content)")
        print(f"  messages: {len(ctx_messages.messages)} messages (lightweight commit messages)")
        print(f"  adaptive: {len(ctx_adaptive.messages)} messages (last {k} full, rest lightweight)")

        # --- All active config ---

        print("\n=== All Active Configs ===\n")
        for key, val in sorted(t.config.get_all().items()):
            print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
