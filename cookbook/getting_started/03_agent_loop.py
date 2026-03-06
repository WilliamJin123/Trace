"""Agent Loop: compile -> LLM -> tools -> repeat

run_loop() is tract's built-in agent loop. It compiles context, sends it to
the LLM with tool definitions, executes any tool calls the LLM makes, and
repeats until the LLM finishes or a rule blocks execution.

Rules configure the loop's behavior -- compile strategy, model selection,
and safety gates -- all as data in the conversation history.

Demonstrates: run_loop(), LoopConfig, rules + loop integration, as_tools()

Requires: LLM API key (uses Groq provider)
"""

import sys
from pathlib import Path

from tract import Tract, LoopConfig, run_loop

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import groq as llm

MODEL_ID = llm.small


def main():
    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        # --- Configure behavior via rules ---

        print("=== Setting up rules ===\n")

        t.rule(
            "compile-strategy",
            trigger="active",
            action={"type": "set_config", "key": "compile_strategy", "value": "adaptive"},
        )
        t.rule(
            "strategy-k",
            trigger="active",
            action={"type": "set_config", "key": "compile_strategy_k", "value": 5},
        )

        print(f"  compile_strategy:   {t.get_config('compile_strategy')}")
        print(f"  compile_strategy_k: {t.get_config('compile_strategy_k')}")

        t.system(
            "You are a helpful assistant. Answer questions concisely. "
            "You have access to tools for managing your own context history."
        )

        # --- Run the loop ---

        print("\n=== Running agent loop ===\n")

        config = LoopConfig(
            max_steps=5,
            stop_on_no_tool_call=True,
        )

        result = run_loop(
            t,
            task="What is the capital of France? Answer in one sentence.",
            config=config,
            on_step=lambda step, _resp: print(f"  step {step}..."),
        )

        print(f"\n=== Loop result ===\n")
        print(f"  status:     {result.status}")
        print(f"  reason:     {result.reason}")
        print(f"  steps:      {result.steps}")
        print(f"  tool_calls: {result.tool_calls}")

        if result.final_response:
            print(f"\n  Response: {result.final_response[:200]}")

        # --- Show the conversation history ---

        print(f"\n=== Conversation log ({len(t.log())} commits) ===\n")
        for ci in t.log()[-6:]:
            print(f"  {ci.commit_hash[:8]}  {ci.content_type:10s}  {ci.message[:50]}")


if __name__ == "__main__":
    main()
