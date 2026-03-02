"""Selective Compression

compress_tool_calls(name=) compresses only specific tool types,
leaving others untouched. Useful when grep results are verbose but
bash output is already concise.

Requires an LLM for compression.

Demonstrates: compress_tool_calls(name=) for selective compression,
              find_tool_results(name=), get_content(), token accounting,
              pprint(style="compact"), before/after visualization
"""

import os

from dotenv import load_dotenv

from tract import Tract

load_dotenv()

TRACT_OPENAI_API_KEY = os.environ.get("TRACT_OPENAI_API_KEY", "")
TRACT_OPENAI_BASE_URL = os.environ.get("TRACT_OPENAI_BASE_URL", "")
MODEL_ID = "gpt-oss-120b"


def _build_agent_session(t):
    """Build a realistic multi-tool agent session for auditing.

    Simulates a coding agent that uses grep, read_file, and bash tools
    to investigate a bug. Returns commit hashes for key tool results.
    """
    t.system("You are a code debugging agent.")
    t.user("Find and fix the authentication bug in the login module.")

    # Turn 1: grep for auth-related files (verbose)
    t.assistant(
        "Let me search for authentication code.",
        metadata={"tool_calls": [
            {"id": "c1", "name": "grep", "arguments": {"pattern": "authenticate"}},
        ]},
    )
    grep1_ci = t.tool_result("c1", "grep", (
        "src/auth/login.py:15: def authenticate(username, password):\n"
        "src/auth/login.py:22:     if not authenticate_ldap(username, password):\n"
        "src/auth/login.py:31:     logger.info(f'authenticate() called for {username}')\n"
        "src/auth/session.py:8: from auth.login import authenticate\n"
        "src/auth/session.py:45: result = authenticate(user, pw)\n"
        "src/auth/middleware.py:12: from auth.login import authenticate\n"
        "src/auth/middleware.py:33: auth_result = authenticate(req.user, req.pass)\n"
        "tests/test_auth.py:10: from auth.login import authenticate\n"
        "tests/test_auth.py:25: assert authenticate('admin', 'pass123')\n"
        "tests/test_auth.py:30: assert not authenticate('admin', 'wrong')\n"
        "docs/api.md:88: The `authenticate()` function validates credentials.\n"
        "docs/api.md:92: See `authenticate()` for LDAP integration details."
    ))

    # Turn 2: read the main auth file (verbose)
    t.assistant(
        "Let me read the login module.",
        metadata={"tool_calls": [
            {"id": "c2", "name": "read_file", "arguments": {"path": "src/auth/login.py"}},
        ]},
    )
    read1_ci = t.tool_result("c2", "read_file", (
        "import hashlib\n"
        "import logging\n"
        "from datetime import datetime, timedelta\n"
        "\n"
        "from ldap3 import Connection, Server\n"
        "\n"
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "MAX_ATTEMPTS = 5\n"
        "LOCKOUT_DURATION = timedelta(minutes=15)\n"
        "_failed_attempts = {}  # BUG: not thread-safe\n"
        "\n"
        "\n"
        "def authenticate(username, password):\n"
        "    if _is_locked_out(username):\n"
        "        logger.warning(f'{username} is locked out')\n"
        "        return False\n"
        "    \n"
        "    if not authenticate_ldap(username, password):\n"
        "        _record_failure(username)\n"
        "        return False\n"
        "    \n"
        "    _failed_attempts.pop(username, None)  # Clear on success\n"
        "    logger.info(f'authenticate() called for {username}')\n"
        "    return True\n"
        "\n"
        "\n"
        "def _is_locked_out(username):\n"
        "    if username not in _failed_attempts:\n"
        "        return False\n"
        "    count, last_time = _failed_attempts[username]\n"
        "    if datetime.now() - last_time > LOCKOUT_DURATION:\n"
        "        del _failed_attempts[username]\n"
        "        return False\n"
        "    return count >= MAX_ATTEMPTS\n"
        "\n"
        "\n"
        "def _record_failure(username):\n"
        "    count, _ = _failed_attempts.get(username, (0, None))\n"
        "    _failed_attempts[username] = (count + 1, datetime.now())\n"
    ))

    # Turn 3: another grep (verbose)
    t.assistant(
        "Let me check the test file for the failing test.",
        metadata={"tool_calls": [
            {"id": "c3", "name": "grep", "arguments": {"pattern": "thread"}},
        ]},
    )
    grep2_ci = t.tool_result("c3", "grep", (
        "src/auth/login.py:11: _failed_attempts = {}  # BUG: not thread-safe\n"
        "src/server.py:5: import threading\n"
        "src/server.py:18: thread_pool = ThreadPoolExecutor(max_workers=10)\n"
        "tests/test_concurrent.py:8: import threading\n"
        "tests/test_concurrent.py:22: threads = [threading.Thread(target=auth_worker)]\n"
        "tests/test_concurrent.py:35: # This test intermittently fails due to race"
    ))

    # Turn 4: read the test file
    t.assistant(
        "Found it. Let me read the concurrent test.",
        metadata={"tool_calls": [
            {"id": "c4", "name": "read_file",
             "arguments": {"path": "tests/test_concurrent.py"}},
        ]},
    )
    read2_ci = t.tool_result("c4", "read_file", (
        "import threading\n"
        "import pytest\n"
        "from auth.login import authenticate\n"
        "\n"
        "def auth_worker(results, idx):\n"
        "    results[idx] = authenticate('admin', 'wrong_pass')\n"
        "\n"
        "def test_concurrent_auth():\n"
        "    results = [None] * 10\n"
        "    threads = [threading.Thread(target=auth_worker, args=(results, i))\n"
        "              for i in range(10)]\n"
        "    for t in threads: t.start()\n"
        "    for t in threads: t.join()\n"
        "    # This test intermittently fails due to race\n"
        "    assert all(r is False for r in results)\n"
    ))

    # Turn 5: bash to run the failing test
    t.assistant(
        "Let me run the test to confirm the race condition.",
        metadata={"tool_calls": [
            {"id": "c5", "name": "bash",
             "arguments": {"command": "python -m pytest tests/test_concurrent.py -v"}},
        ]},
    )
    bash_ci = t.tool_result("c5", "bash", (
        "===== test session starts =====\n"
        "collected 1 item\n"
        "tests/test_concurrent.py::test_concurrent_auth FAILED\n"
        "FAILED tests/test_concurrent.py::test_concurrent_auth\n"
        "AssertionError: assert all(r is False for r in results)\n"
        "1 failed in 0.12s"
    ))

    # Agent's conclusion
    t.assistant(
        "The bug is a race condition in `_failed_attempts` — it's a plain dict "
        "shared across threads without synchronization. The fix is to use "
        "`threading.Lock` to guard access to `_failed_attempts`."
    )

    return {
        "grep1": grep1_ci,
        "read1": read1_ci,
        "grep2": grep2_ci,
        "read2": read2_ci,
        "bash": bash_ci,
    }


def part3_selective_compression():
    if not TRACT_OPENAI_API_KEY:
        print(f"\n{'=' * 60}")
        print("PART 3 -- Manual: SKIPPED (no TRACT_OPENAI_API_KEY)")
        print("=" * 60)
        return

    print(f"\n{'=' * 60}")
    print("PART 3 -- Manual: SELECTIVE COMPRESSION (compress_tool_calls(name=))")
    print("=" * 60)
    print()

    with Tract.open(
        api_key=TRACT_OPENAI_API_KEY,
        base_url=TRACT_OPENAI_BASE_URL,
        model=MODEL_ID,
    ) as t:
        refs = _build_agent_session(t)

        ctx_before = t.compile()
        print(f"  BEFORE: {ctx_before.token_count} tokens\n")

        # --- Compress only grep results ---
        # bash and read_file results stay untouched

        print("  compress_tool_calls(name='grep') — only grep turns:\n")
        grep_result = t.compress_tool_calls(
            name="grep",
            instructions="One line per file: 'filename: relevant finding'",
        )
        print(f"    original_tokens:  {grep_result.original_tokens}")
        print(f"    compacted_tokens: {grep_result.compacted_tokens}")
        print(f"    turn_count:       {grep_result.turn_count}")
        print(f"    tool_names:       {grep_result.tool_names}")

        ctx_after_grep = t.compile()
        print(f"\n  After grep compression: {ctx_after_grep.token_count} tokens")

        # --- Compress read_file results too ---

        print(f"\n  compress_tool_calls(name='read_file'):\n")
        read_result = t.compress_tool_calls(
            name="read_file",
            instructions="Summarize the file's purpose and key findings in 1-2 lines.",
        )
        print(f"    original_tokens:  {read_result.original_tokens}")
        print(f"    compacted_tokens: {read_result.compacted_tokens}")
        print(f"    turn_count:       {read_result.turn_count}")

        ctx_after_both = t.compile()
        total_saved = ctx_before.token_count - ctx_after_both.token_count
        print(f"\n  AFTER all selective compressions: {ctx_after_both.token_count} tokens")
        print(f"  Total saved: {total_saved} tokens\n")

        # --- bash results were untouched ---

        print("  bash results were never compressed (already concise):")
        bash_results = t.find_tool_results(name="bash")
        for r in bash_results:
            content = t.get_content(r.commit_hash)
            preview = content[:60] if isinstance(content, str) else str(content)[:60]
            print(f"    {r.token_count} tokens: {preview}...")

        # --- Final context ---

        print(f"\n  Final context:\n")
        ctx_after_both.pprint(style="compact")


# =============================================================================
# Part 2 -- Interactive: Selective Compression
# =============================================================================
# Show tool turns grouped by name. Let the human choose which tool types
# to compress interactively.

def part2_interactive():
    import click

    if not TRACT_OPENAI_API_KEY:
        print(f"\n{'=' * 60}")
        print("PART 2 -- Interactive: SKIPPED (no TRACT_OPENAI_API_KEY)")
        print("=" * 60)
        return

    print(f"\n{'=' * 60}")
    print("PART 2 -- Interactive: SELECTIVE COMPRESSION")
    print("=" * 60)
    print()

    with Tract.open(
        api_key=TRACT_OPENAI_API_KEY,
        base_url=TRACT_OPENAI_BASE_URL,
        model=MODEL_ID,
    ) as t:
        _build_agent_session(t)

        # Show tool turns grouped by name
        all_turns = t.find_tool_turns()
        tool_names = set()
        for turn in all_turns:
            tool_names.update(turn.tool_names)

        print(f"  Tool types found: {sorted(tool_names)}\n")
        for name in sorted(tool_names):
            name_turns = t.find_tool_turns(name=name)
            total = sum(turn.total_tokens for turn in name_turns)
            print(f"    {name}: {len(name_turns)} turn(s), {total} tokens")

        # Let human choose which to compress
        for name in sorted(tool_names):
            if click.confirm(f"\n  Compress all '{name}' tool turns?", default=False):
                result = t.compress_tool_calls(
                    name=name,
                    instructions=f"Summarize {name} output in 1-2 lines.",
                )
                print(f"    Compressed: {result.original_tokens} -> "
                      f"{result.compacted_tokens} tokens")

        ctx = t.compile()
        print(f"\n  Final: {ctx.token_count} tokens")


# =============================================================================
# Part 3b -- Agent: Auto-Compresses via Toolkit
# =============================================================================
# An agent auto-compresses specific tool types via compress_tool_calls.

def part3b_agent():
    if not TRACT_OPENAI_API_KEY:
        print(f"\n{'=' * 60}")
        print("PART 3b -- Agent: SKIPPED (no TRACT_OPENAI_API_KEY)")
        print("=" * 60)
        return

    print(f"\n{'=' * 60}")
    print("PART 3b -- Agent: AUTO-COMPRESSES VIA TOOLKIT")
    print("=" * 60)
    print()

    from tract.toolkit import ToolExecutor

    with Tract.open(
        api_key=TRACT_OPENAI_API_KEY,
        base_url=TRACT_OPENAI_BASE_URL,
        model=MODEL_ID,
    ) as t:
        _build_agent_session(t)
        executor = ToolExecutor(t)

        ctx_before = t.compile()
        print(f"  BEFORE: {ctx_before.token_count} tokens")

        # Agent auto-compresses grep results
        result = t.compress_tool_calls(
            name="grep",
            instructions="One line per file: 'filename: relevant finding'",
        )
        print(f"  Compressed grep: {result.original_tokens} -> "
              f"{result.compacted_tokens} tokens")

        ctx_after = t.compile()
        print(f"  AFTER: {ctx_after.token_count} tokens")

    # Note: Agents identify verbose tool types via find_tool_turns() and
    # selectively compress them. This is a common pattern in long agent
    # sessions where grep/read_file outputs dominate the context.


def main():
    part2_interactive()
    part3_selective_compression()
    part3b_agent()


if __name__ == "__main__":
    main()
