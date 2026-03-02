"""Toolkit: expose tract operations as LLM-callable tools.

  PART 1 -- Manual:      as_tools(profile="self"), 3 profiles, ToolExecutor.execute()
  PART 2 -- Interactive:  Human-gated tool execution with click.confirm per call
  PART 3 -- LLM / Agent:  Full LLM-driven tool loop: compile + tools -> LLM -> execute
"""

import os

import click
from dotenv import load_dotenv

from tract import Tract, TractConfig, TokenBudgetConfig
from tract.toolkit import ToolExecutor

load_dotenv()

TRACT_OPENAI_API_KEY = os.environ.get("TRACT_OPENAI_API_KEY", "")
TRACT_OPENAI_BASE_URL = os.environ.get("TRACT_OPENAI_BASE_URL", "")
MODEL_ID = "gpt-oss-120b"


# =====================================================================
# PART 1 -- Manual: profiles, tool listing, direct execution
# =====================================================================

def part1_manual():
    print("=" * 60)
    print("PART 1 -- Manual: Profiles and ToolExecutor")
    print("=" * 60)

    with Tract.open() as t:
        t.system("You are an astronomy research assistant.")
        t.user("What causes a solar eclipse?")
        t.assistant("A solar eclipse occurs when the Moon passes between "
                    "Earth and the Sun, casting a shadow on Earth.")

        # Three built-in profiles control which tools are exposed
        for profile in ["self", "supervisor", "full"]:
            tools = t.as_tools(profile=profile, format="openai")
            names = [tool["function"]["name"] for tool in tools]
            print(f"\n  Profile '{profile}': {len(tools)} tools")
            print(f"    {', '.join(names[:6])}{'...' if len(names) > 6 else ''}")

        # ToolExecutor dispatches tool calls against a tract
        executor = ToolExecutor(t)
        result = executor.execute("status", {})
        print(f"\n  executor.execute('status', {{}}):")
        print(f"    success={result.success}")
        print(f"    output={result.output[:100]}...")

        # Profile filtering on the executor
        executor.set_profile("supervisor")
        print(f"\n  Supervisor tools: {executor.available_tools()}")


# =====================================================================
# PART 2 -- Interactive: human-gated tool execution
# =====================================================================

def part2_interactive():
    print("\n" + "=" * 60)
    print("PART 2 -- Interactive: Human-Gated Tool Execution")
    print("=" * 60)

    with Tract.open() as t:
        t.system("You are a research assistant.")
        t.user("Summarize the Drake equation.")
        t.assistant("The Drake equation estimates the number of active "
                    "civilizations in the Milky Way.")

        executor = ToolExecutor(t)

        # Simulate a list of tool calls an LLM might request
        planned_calls = [
            ("status", {}),
            ("log", {"limit": 5}),
            ("compile", {}),
        ]

        print("\n  Simulated LLM tool calls (human gates each one):\n")
        for name, args in planned_calls:
            if click.confirm(f"  Execute {name}({args})?", default=True):
                result = executor.execute(name, args)
                status = "OK" if result.success else "FAIL"
                output = (result.output or result.error or "")[:80]
                print(f"    [{status}] {output}...\n")
            else:
                print(f"    [SKIPPED] {name}\n")


# =====================================================================
# PART 3 -- LLM / Agent: full LLM-driven tool loop
# =====================================================================

def part3_agent():
    print("\n" + "=" * 60)
    print("PART 3 -- LLM / Agent: LLM-Driven Tool Loop")
    print("=" * 60)

    config = TractConfig(token_budget=TokenBudgetConfig(max_tokens=2000))
    with Tract.open(
        config=config,
        api_key=TRACT_OPENAI_API_KEY,
        base_url=TRACT_OPENAI_BASE_URL,
        model=MODEL_ID,
    ) as t:
        t.system("You are a context management agent. Use the provided tools "
                 "to inspect and manage the conversation history.")
        for i in range(5):
            t.user(f"Research note {i}: stellar nucleosynthesis produces "
                   f"elements heavier than hydrogen in star cores.")

        tools = t.as_tools(profile="self", format="openai")
        executor = ToolExecutor(t)
        print(f"\n  {len(tools)} tools available for LLM")

        # Build messages for the LLM
        messages = [
            {"role": "system", "content": "You are a context management agent. "
             "Check the tract status and log, then decide if any action is needed."},
            {"role": "user", "content": "Please check the current context status "
             "and report what you find."},
        ]

        # Single-round tool loop (production would repeat until no tool_calls)
        response = t._llm_client.chat(messages, tools=tools)
        tool_calls = response.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])

        if tool_calls:
            print(f"\n  LLM requested {len(tool_calls)} tool call(s):")
            for tc in tool_calls:
                import json
                name = tc["function"]["name"]
                args = json.loads(tc["function"].get("arguments", "{}"))
                result = executor.execute(name, args)
                status = "OK" if result.success else "FAIL"
                print(f"    {name}({args}) -> [{status}]")
                print(f"      {(result.output or result.error or '')[:100]}")
        else:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"\n  LLM responded without tools: {content[:120]}...")


def main():
    part1_manual()
    part2_interactive()
    part3_agent()


if __name__ == "__main__":
    main()
