"""LLM Configuration Hierarchy

Demonstrates the 4-level config resolution chain introduced in Phase 12:

  1. Sugar params (model=, temperature=, max_tokens=) — highest priority
  2. llm_config= (LLMConfig instance per call)
  3. Operation-level config (via configure_operations)
  4. Tract-level default (via default_config= on open)

Each level overrides the one below it, per-field. Different fields can come
from different levels in the same call.

Also demonstrates:
- LLMConfig: typed, frozen dataclass for LLM settings
- OperationConfigs: typed per-operation defaults
- LLMConfig.from_dict(): cross-framework alias handling
- Full generation_config capture on every commit

Demonstrates: LLMConfig, OperationConfigs, configure_operations(),
              default_config=, llm_config=, LLMConfig.from_dict(), 4-level resolution
"""

import os

from dotenv import load_dotenv

from tract import LLMConfig, OperationConfigs, Tract

load_dotenv()

CEREBRAS_API_KEY = os.environ["TRACT_OPENAI_API_KEY"]
CEREBRAS_BASE_URL = os.environ["TRACT_OPENAI_BASE_URL"]


def main():
    # --- Level 4: Tract-level default via default_config= ---
    # Instead of model="gpt-oss-120b", use a full LLMConfig for typed defaults.
    # All operations inherit these unless overridden at a lower level.
    tract_default = LLMConfig(
        model="gpt-oss-120b",
        temperature=0.5,
        top_p=0.95,
    )

    with Tract.open(
        api_key=CEREBRAS_API_KEY,
        base_url=CEREBRAS_BASE_URL,
        default_config=tract_default,
    ) as t:
        t.system("You are a helpful assistant. Be concise.")

        # --- Level 3: Operation-level defaults via configure_operations() ---
        # Chat calls should be creative (higher temp), but compression
        # should be deterministic (low temp, fixed seed).
        t.configure_operations(
            chat=LLMConfig(temperature=0.8),
            compress=LLMConfig(temperature=0.1, seed=42),
        )

        # Equivalent typed style using OperationConfigs:
        #   t.configure_operations(OperationConfigs(
        #       chat=LLMConfig(temperature=0.8),
        #       compress=LLMConfig(temperature=0.1, seed=42),
        #   ))

        # --- Demonstrate resolution chain ---
        print("=== Call 1: Default resolution ===")
        print("  Level 4 (tract default): model=gpt-oss-120b, temp=0.5, top_p=0.95")
        print("  Level 3 (chat operation): temp=0.8 (overrides default)")
        print("  Effective: model=gpt-oss-120b, temp=0.8, top_p=0.95\n")

        response = t.chat("What is Python's GIL?")
        gc = response.generation_config
        print(f"  Captured: model={gc.model}, temp={gc.temperature}, top_p={gc.top_p}")
        print(f"  Response: {response.text[:120]}...\n")

        # --- Level 2: Call-level LLMConfig override ---
        print("=== Call 2: llm_config= override ===")
        precise_config = LLMConfig(temperature=0.2, seed=123)
        print("  Level 4 (tract default): model=gpt-oss-120b, top_p=0.95")
        print("  Level 3 (chat operation): temp=0.8")
        print("  Level 2 (llm_config=): temp=0.2, seed=123 (overrides operation)")
        print("  Effective: model=gpt-oss-120b, temp=0.2, top_p=0.95, seed=123\n")

        response = t.chat("Explain it in one sentence.", llm_config=precise_config)
        gc = response.generation_config
        print(f"  Captured: model={gc.model}, temp={gc.temperature}, top_p={gc.top_p}, seed={gc.seed}")
        print(f"  Response: {response.text[:120]}...\n")

        # --- Level 1: Sugar params (highest priority) ---
        print("=== Call 3: Sugar param override ===")
        print("  Level 2 (llm_config=): temp=0.2, seed=123")
        print("  Level 1 (sugar): temperature=0.9 (beats llm_config)")
        print("  Effective: model=gpt-oss-120b, temp=0.9, top_p=0.95, seed=123\n")

        response = t.chat(
            "Give a creative analogy for the GIL.",
            llm_config=precise_config,
            temperature=0.9,  # sugar beats llm_config for this field
        )
        gc = response.generation_config
        print(f"  Captured: model={gc.model}, temp={gc.temperature}, seed={gc.seed}")
        print(f"  Response: {response.text[:120]}...\n")

        # --- LLMConfig.from_dict(): Cross-framework portability ---
        print("=== LLMConfig.from_dict(): Cross-framework aliases ===\n")

        # Config from an OpenAI-style dict (uses "stop" and "max_completion_tokens")
        openai_params = {
            "model": "gpt-oss-120b",
            "temperature": 0.3,
            "max_completion_tokens": 200,  # alias -> max_tokens
            "stop": ["\n\n"],             # alias -> stop_sequences
            "messages": [...],            # API plumbing — auto-ignored
        }

        config = LLMConfig.from_dict(openai_params)
        print(f"  Input: max_completion_tokens=200, stop=['\\n\\n'], messages=[...]")
        print(f"  Parsed: max_tokens={config.max_tokens}, "
              f"stop_sequences={config.stop_sequences}, "
              f"extra={config.extra}")
        print(f"  (messages was auto-ignored as API plumbing)\n")

        # Use the parsed config directly
        response = t.chat("Summarize the GIL in 2 sentences.", llm_config=config)
        gc = response.generation_config
        print(f"  Captured: model={gc.model}, temp={gc.temperature}, max_tokens={gc.max_tokens}")
        print(f"  Response: {response.text[:120]}...\n")

        # --- Summary: what was captured ---
        print("=== Generation configs across all calls ===\n")
        history = t.log(limit=20)
        for entry in reversed(history):
            if entry.generation_config:
                print(f"  {entry.commit_hash[:8]} | {entry.generation_config.to_dict()}")


if __name__ == "__main__":
    main()
