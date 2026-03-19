"""Real Callable Tools: Agent with actual Python functions

An agent equipped with real Python tool functions -- not simulated
tool_result() calls. The agent has live access to the filesystem
(read-only) and an in-memory notepad. Tract manages the context
around every tool invocation automatically.

Sections:
  1. Custom tool registration + agent loop with real filesystem tools
  2. Post-loop tool compaction: compress verbose results to save tokens

Demonstrates: @t.toolkit.tool, t.runtime.run(), compress_tool_calls(),
              real os/pathlib operations inside tool handlers

Requires: LLM API key (uses Claude Code provider)
"""

import io
import os
import sys
from pathlib import Path

# Windows console encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from tract import Tract

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _providers import claude_code as llm
from _logging import StepLogger

MODEL_ID = llm.small

# ---------------------------------------------------------------------------
# Safety: all file reads are restricted to the cookbook directory
# ---------------------------------------------------------------------------
COOKBOOK_ROOT = Path(__file__).resolve().parents[1]  # cookbook/

# In-memory notepad for write_note (no real filesystem writes)
_notes: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Tool functions -- plain Python with type hints and docstrings
# ---------------------------------------------------------------------------

def list_files(directory: str) -> str:
    """List files in a directory under the cookbook root. Returns one filename per line."""
    target = (COOKBOOK_ROOT / directory).resolve()
    # Safety: only allow reads within the cookbook tree
    if not str(target).startswith(str(COOKBOOK_ROOT)):
        return "Error: access denied -- path is outside the cookbook directory"
    try:
        entries = sorted(os.listdir(target))
        if not entries:
            return "(empty directory)"
        return "\n".join(entries[:30])  # cap at 30 entries
    except OSError as e:
        return f"Error: {e}"


def read_file(path: str) -> str:
    """Read a file under the cookbook root. Only .py and .txt files, max 500 chars."""
    target = (COOKBOOK_ROOT / path).resolve()
    if not str(target).startswith(str(COOKBOOK_ROOT)):
        return "Error: access denied -- path is outside the cookbook directory"
    if target.suffix not in (".py", ".txt", ".cfg", ".toml", ".md"):
        return f"Error: cannot read {target.suffix} files (allowed: .py, .txt, .cfg, .toml, .md)"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > 500:
            return text[:500] + f"\n... (truncated, {len(text)} chars total)"
        return text
    except OSError as e:
        return f"Error: {e}"


def word_count(text: str) -> str:
    """Count words, lines, and characters in the given text."""
    words = len(text.split())
    lines = text.count("\n") + (1 if text else 0)
    chars = len(text)
    return f"{words} words, {lines} lines, {chars} characters"


def write_note(title: str, content: str) -> str:
    """Save a note to the in-memory notepad. Returns confirmation."""
    _notes[title] = content
    return f"Note '{title}' saved ({len(content)} chars). Total notes: {len(_notes)}"


# ===================================================================
# Section 1: Custom Tool Registration + Agent Loop
# ===================================================================

def section_1_real_tools() -> None:
    print("=" * 60)
    print("  Section 1: Real Tools in an Agent Loop")
    print("=" * 60)
    print()
    print("  The agent has 4 real Python tools:")
    print("    list_files  -- os.listdir() on the cookbook directory")
    print("    read_file   -- reads real .py files (max 500 chars)")
    print("    word_count  -- counts words/lines/chars in text")
    print("    write_note  -- writes to an in-memory notepad")
    print()

    _notes.clear()

    with Tract.open(
        **llm.tract_kwargs(MODEL_ID),
        auto_message=llm.small,
    ) as t:

        # Register tools via the decorator -- schema is inferred from type hints
        t.toolkit.tool(list_files)
        t.toolkit.tool(read_file)
        t.toolkit.tool(word_count)
        t.toolkit.tool(write_note)

        # Verify registration
        print("  Registered tools:")
        for name, td in t.toolkit.custom_tools.items():
            print(f"    {name:15s}  {td.description[:55]}")
        print()

        t.system(
            "You are a code analysis assistant with access to filesystem tools. "
            "You can list directories, read files, count words, and write notes."
        )

        # Run agent with a real task
        log = StepLogger()
        result = t.runtime.run(
            "List the Python files in the 'agentic' directory, read the "
            "conftest.py file if it exists (or any small .py file you find), "
            "count the words in what you read, then write a summary note "
            "with the key findings.",
            max_steps=12,
            max_tokens=1024,
            tool_names=["list_files", "read_file", "word_count", "write_note",
                        "commit", "status"],
            on_step=log.on_step,
            on_tool_result=log.on_tool_result,
        )

        # Results
        print(f"\n  Loop result: {result.status} ({result.steps} steps, "
              f"{result.tool_calls} tool calls)")

        if result.final_response:
            text = result.final_response[:200]
            print(f"  Final response: {text}{'...' if len(result.final_response) > 200 else ''}")

        # Show notes written
        if _notes:
            print(f"\n  Notes written ({len(_notes)}):")
            for title, content in _notes.items():
                preview = content[:80].replace("\n", " ")
                print(f"    [{title}]: {preview}{'...' if len(content) > 80 else ''}")

        # Show compiled context with real tool results embedded
        print(f"\n  Compiled context ({t.compile().token_count} tokens):")
        t.compile().pprint(style="chat")


# ===================================================================
# Section 2: Tool Compaction After Heavy Use
# ===================================================================

def section_2_compaction() -> None:
    print()
    print("=" * 60)
    print("  Section 2: Post-Loop Tool Compaction")
    print("=" * 60)
    print()
    print("  After heavy tool use, compress_tool_calls() summarizes")
    print("  verbose results while keeping the tool turn structure.")
    print()

    _notes.clear()

    with Tract.open(
        **llm.tract_kwargs(MODEL_ID),
        auto_message=llm.small,
    ) as t:

        # Register the same tools
        t.toolkit.tool(list_files)
        t.toolkit.tool(read_file)
        t.toolkit.tool(word_count)
        t.toolkit.tool(write_note)

        t.system(
            "You are a thorough code analyst. Read multiple files and "
            "produce detailed notes about each one."
        )

        # Run agent with a task that generates verbose tool output
        log = StepLogger()
        result = t.runtime.run(
            "Explore the cookbook directory structure: list the top-level "
            "contents, then list the 'getting_started' subdirectory. "
            "Read at least 2 Python files from getting_started/. "
            "For each file, count its words. Write a note summarizing "
            "what you found.",
            max_steps=15,
            max_tokens=1024,
            tool_names=["list_files", "read_file", "word_count", "write_note",
                        "commit", "status"],
            on_step=log.on_step,
            on_tool_result=log.on_tool_result,
        )

        print(f"\n  Loop complete: {result.status} ({result.steps} steps, "
              f"{result.tool_calls} tool calls)")

        # Measure before compaction
        before = t.compile().token_count
        turns_before = len(t.tools.find_turns())
        print(f"\n  Before compaction: {turns_before} tool turns, {before} tokens")

        # Compress all tool results at once
        print("  Calling compress_tool_calls()...")
        compact_result = t.compress_tool_calls(
            instructions="Keep file names and key findings. Drop raw file "
                         "contents and verbose listings. Preserve structure."
        )

        after = t.compile().token_count
        saved = before - after
        ratio = compact_result.compression_ratio

        print(f"  After compaction:  {after} tokens "
              f"({ratio:.1%} ratio, {saved} tokens saved)")
        print(f"  EDIT commits created: {len(compact_result.edit_commits)}")

        # Show the compacted context
        print(f"\n  Compiled context after compaction:")
        t.compile().pprint(style="chat")

        # Show that notes are still intact (in-memory, not in DAG)
        if _notes:
            print(f"\n  In-memory notes ({len(_notes)} total) still available:")
            for title in _notes:
                print(f"    - {title}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not llm.available:
        print("SKIPPED (no LLM provider)")
        return

    print()
    print("  Real Callable Tools")
    print("  Agent with live Python functions + tract context management")
    print()

    section_1_real_tools()
    section_2_compaction()

    print("\n\n  Done. Both sections complete.")
    print("  Key takeaway: tract automatically commits tool results to the DAG,")
    print("  and compress_tool_calls() can shrink them after the loop finishes.")


if __name__ == "__main__":
    main()


# --- See also ---
# Custom tool basics:       getting_started/02_custom_tools.py
# Tool compaction patterns:  agentic/03_tool_compaction.py
# Implicit discovery:        agentic/01_implicit_discovery.py
