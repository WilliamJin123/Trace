"""Tool Decorator: register custom tools with @t.tool

The @t.tool decorator turns any typed Python function into an agent tool.
No JSON schema, no handler dicts, no manual merging -- just decorate and go.

Demonstrates three patterns:
  1. @t.tool             -- basic registration from type hints + docstring
  2. @t.tool(name=...)   -- override name or description
  3. Python REPL tool    -- agent can execute code and see the output

Compare with 03_custom_tools.py which shows the manual approach (tool defs
+ tool_handlers). This is the same thing with less boilerplate.

Requires: LLM API key (uses Cerebras provider)
"""

import contextlib
import io
import sys
from pathlib import Path

from tract import Tract

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import cerebras as llm

MODEL_ID = llm.large


# ---------------------------------------------------------------------------
# Custom tools as plain functions -- these become agent tools via @t.tool
# ---------------------------------------------------------------------------

def calculator(expression: str) -> str:
    """Evaluate a mathematical expression. Supports +, -, *, /, parentheses.

    Args:
        expression: The math expression to evaluate (e.g. "2 * (3 + 4)").
    """
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "Error: only numeric expressions allowed"
    try:
        return f"{expression} = {eval(expression)}"  # noqa: S307
    except Exception as e:
        return f"Error: {e}"


def python_repl(code: str) -> str:
    """Execute a Python code snippet and return its stdout output.

    Use this to run calculations, test logic, or verify assumptions.
    The code runs in an isolated namespace with standard builtins.

    Args:
        code: Python code to execute. Use print() to produce output.
    """
    buf = io.StringIO()
    namespace: dict = {}
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, {"__builtins__": __builtins__}, namespace)  # noqa: S102
        output = buf.getvalue()
        return output if output else "(executed, no output)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def note_pad(action: str, text: str = "") -> str:
    """A simple scratchpad for keeping notes during a task.

    Args:
        action: One of 'write', 'read', or 'clear'.
        text: Text to write (only used with 'write' action).
    """
    if not hasattr(note_pad, "_notes"):
        note_pad._notes = []  # type: ignore[attr-defined]

    if action == "write":
        note_pad._notes.append(text)  # type: ignore[attr-defined]
        return f"Noted ({len(note_pad._notes)} entries)"  # type: ignore[attr-defined]
    elif action == "read":
        if not note_pad._notes:  # type: ignore[attr-defined]
            return "(empty)"
        return "\n".join(f"- {n}" for n in note_pad._notes)  # type: ignore[attr-defined]
    elif action == "clear":
        note_pad._notes = []  # type: ignore[attr-defined]
        return "Cleared."
    return f"Unknown action: {action}"


def main() -> None:
    if not llm.api_key:
        print("SKIPPED (no API key -- set CEREBRAS_API_KEY)")
        return

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:

        # =============================================================
        # Pattern 1: @t.tool -- basic decorator
        # =============================================================

        print("=== Registering tools with @t.tool ===\n")

        # Decorate existing functions
        t.tool(calculator)
        t.tool(python_repl)

        # Or use the decorator syntax inline
        @t.tool(name="notes", description="Scratchpad for keeping notes")
        def _notepad(action: str, text: str = "") -> str:
            return note_pad(action, text)

        # See what's registered
        for name, td in t.custom_tools.items():
            print(f"  {name:15s}  {td.description[:60]}")

        # Verify they show up in as_tools()
        all_tools = t.as_tools(profile="full", format="openai")
        custom_names = {name for name in t.custom_tools}
        in_tools = {
            td["function"]["name"]
            for td in all_tools
            if td["function"]["name"] in custom_names
        }
        print(f"\n  Custom tools in as_tools(): {sorted(in_tools)}")

        # =============================================================
        # Run: agent uses custom tools alongside tract built-ins
        # =============================================================

        print("\n=== Running agent with custom tools ===\n")

        t.system(
            "You are a helpful assistant with access to a calculator, a "
            "Python REPL, and a notes scratchpad. Use the tools to work "
            "through problems step by step. Show your work."
        )

        result = t.run(
            "I need to figure out compound interest.\n\n"
            "Use the Python REPL to calculate how much $10,000 grows to "
            "after 5 years at 7% annual interest, compounded monthly.\n\n"
            "Then use the calculator to verify the final amount rounded "
            "to the nearest dollar.\n\n"
            "Save the formula and result to the notepad.",
            max_steps=10,
            profile="full",
            tool_names=["commit", "status", "calculator", "python_repl", "notes"],
        )

        # =============================================================
        # Show what happened
        # =============================================================

        result.pprint(style="chat")

        print(f"\n=== Full conversation ===\n")
        t.compile().pprint(style="chat")

        print(f"\n=== Notepad contents ===\n")
        print(f"  {note_pad('read')}")

        print(f"\n=== Summary ===")
        print(f"  Status: {result.status}")
        print(f"  Steps:  {result.steps}")
        print(f"  Tools:  {result.tool_calls} calls")
        print(f"  Custom tools registered: {sorted(t.custom_tools.keys())}")


if __name__ == "__main__":
    main()


# --- See also ---
# Manual tool setup:     getting_started/03_custom_tools.py
# Agent loop basics:     getting_started/06_agent_loop.py
# Adversarial review:    workflows/08_adversarial_review.py
