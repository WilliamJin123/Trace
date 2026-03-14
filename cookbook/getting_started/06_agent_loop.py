"""Five-Minute Agent Loop -- minimal runnable agent with tract.

Shows how to set up an LLM loop with tools in under 50 lines.
Everything runs locally -- no API keys needed.

Patterns shown:
  1. Mock LLM client       -- protocol-conformant, returns tool calls then text
  2. Custom tool handlers   -- calculator and note-taking tools
  3. run() with callbacks   -- on_step monitoring
  4. LoopResult inspection  -- status, steps, tool_calls, token usage

Demonstrates: Tract.open(llm_client=), t.run(), LoopResult, on_step

No LLM required.
"""

import json
from typing import Any

from tract import Tract
from tract.loop import LoopConfig, run_loop


# ---------------------------------------------------------------------------
# Mock LLM client -- returns a tool call first, then a text response
# ---------------------------------------------------------------------------

class MockLLM:
    """Minimal mock: call a tool on step 1, give a final answer on step 2."""

    def __init__(self):
        self._step = 0
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], **kwargs: Any) -> dict:
        self.calls.append({"messages": messages, **kwargs})
        self._step += 1

        if self._step == 1:
            # Step 1: LLM decides to call the calculator tool
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "function": {
                                "name": "calculator",
                                "arguments": json.dumps({"expression": "6 * 7"}),
                            },
                        }],
                    },
                }],
                "usage": {"prompt_tokens": 25, "completion_tokens": 12, "total_tokens": 37},
            }

        # Step 2+: LLM gives a final text answer (no tool calls -> loop stops)
        return {
            "choices": [{"message": {"role": "assistant", "content": "The answer is 42."}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
        }

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tool handlers -- plain functions, no decorators needed
# ---------------------------------------------------------------------------

notes: list[str] = []


def calculator(expression: str) -> str:
    """Evaluate a math expression (mock: always returns 42)."""
    return "42"


def take_note(text: str) -> str:
    """Save a note for later reference."""
    notes.append(text)
    return f"Noted ({len(notes)} total)."


# Tool definitions in OpenAI format
TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a math expression",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_note",
            "description": "Save a note for later reference",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Five-Minute Agent Loop")
    print("=" * 60)
    print()

    mock = MockLLM()
    step_log: list[int] = []

    def on_step(step_num: int, response: Any) -> None:
        """Simple callback that records each step."""
        step_log.append(step_num)
        content = None
        if isinstance(response, dict):
            try:
                content = response["choices"][0]["message"].get("content")
            except (KeyError, IndexError):
                pass
        tag = f"text='{content[:40]}...'" if content else "tool call"
        print(f"  [on_step] step {step_num}: {tag}")

    with Tract.open(llm_client=mock) as t:
        t.system("You are a helpful calculator assistant.")

        # One call does everything: compile -> LLM -> tools -> repeat
        result = t.run(
            "What is 6 times 7?",
            tools=TOOL_DEFS,
            tool_handlers={"calculator": calculator, "take_note": take_note},
            max_steps=5,
            on_step=on_step,
        )

    # ---------------------------------------------------------------------------
    # Inspect LoopResult
    # ---------------------------------------------------------------------------

    print()
    print("  --- LoopResult ---")
    result.pprint()
    print()

    # ---------------------------------------------------------------------------
    # Assertions
    # ---------------------------------------------------------------------------

    assert result.status == "completed", f"Expected completed, got {result.status}"
    assert result.steps == 2, f"Expected 2 steps, got {result.steps}"
    assert result.tool_calls == 1, f"Expected 1 tool call, got {result.tool_calls}"
    assert result.final_response == "The answer is 42."
    assert len(step_log) == 2, f"on_step should have fired twice, got {len(step_log)}"
    assert result.total_tokens > 0, "Should have token usage"
    assert len(mock.calls) == 2, "Mock should have been called twice"

    print("  All assertions passed.")
    print()
    print("PASSED")


# Alias for pytest discovery
test_agent_loop = main


if __name__ == "__main__":
    main()


# --- See also ---
# Mock patterns:     testing/01_mocking_patterns.py
# Staged workflows:  agent/05_staged_workflow.py
# Tool tracking:     reference/07_tool_tracking.py
