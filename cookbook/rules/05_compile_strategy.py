"""Compile Strategies via Rules

The compile strategy controls how tract builds the LLM context window:
  - "full"     -- all messages, ordered chronologically
  - "messages" -- last K messages (set via compile_strategy_k)
  - "adaptive" -- smart selection balancing recency and relevance

Instead of passing strategy= to every compile() call, set it once
as an active config rule. The run_loop() and compile() methods
consult get_config("compile_strategy") automatically.

Demonstrates: compile_strategy, compile_strategy_k, active config rules,
              strategy comparison
"""

from tract import Tract, resolve_all_configs


def main():
    with Tract.open() as t:

        # --- Build some conversation history ---

        print("=== Building History ===\n")

        t.system("You are a helpful assistant.")
        for i in range(8):
            t.user(f"Question {i + 1}: Tell me about topic {i + 1}.")
            t.assistant(f"Answer {i + 1}: Here is information about topic {i + 1}.")

        total = len(t.log())
        print(f"  Total commits: {total}")

        # --- Strategy: full ---

        print("\n=== Strategy: full ===\n")

        t.rule("strategy", trigger="active",
               action={"type": "set_config", "key": "compile_strategy", "value": "full"})

        strategy = t.get_config("compile_strategy")
        ctx_full = t.compile(strategy=strategy)
        print(f"  Strategy: {strategy}")
        print(f"  Messages: {len(ctx_full.messages)}")

        # --- Strategy: messages (last K) ---

        print("\n=== Strategy: messages (last 5) ===\n")

        # Override strategy
        t.rule("strategy", trigger="active",
               action={"type": "set_config", "key": "compile_strategy", "value": "messages"})
        t.rule("strategy-k", trigger="active",
               action={"type": "set_config", "key": "compile_strategy_k", "value": 5})

        strategy = t.get_config("compile_strategy")
        k = t.get_config("compile_strategy_k")
        ctx_messages = t.compile(strategy=strategy, strategy_k=k)
        print(f"  Strategy: {strategy}, k={k}")
        print(f"  Messages: {len(ctx_messages.messages)}")

        # --- Strategy: adaptive ---

        print("\n=== Strategy: adaptive ===\n")

        t.rule("strategy", trigger="active",
               action={"type": "set_config", "key": "compile_strategy", "value": "adaptive"})
        t.rule("strategy-k", trigger="active",
               action={"type": "set_config", "key": "compile_strategy_k", "value": 5})

        strategy = t.get_config("compile_strategy")
        k = t.get_config("compile_strategy_k")
        ctx_adaptive = t.compile(strategy=strategy, strategy_k=k)
        print(f"  Strategy: {strategy}, k={k}")
        print(f"  Messages: {len(ctx_adaptive.messages)}")

        # --- Comparison ---

        print("\n=== Strategy Comparison ===\n")

        print(f"  full:     {len(ctx_full.messages)} messages")
        print(f"  messages: {len(ctx_messages.messages)} messages (last {k})")
        print(f"  adaptive: {len(ctx_adaptive.messages)} messages")

        # --- Show active configs ---

        print("\n=== Active Configs ===\n")
        for key, val in sorted(resolve_all_configs(t.rule_index).items()):
            print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
