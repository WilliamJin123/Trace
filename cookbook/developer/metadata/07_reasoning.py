"""Reasoning commits, compile control, formatting, and LLM integration.

Four aspects of reasoning:

  Part 1 -- Manual Commits:     t.reasoning(), log(), compile(), get_content()
  Part 2 -- Compile Control:    compile(include_reasoning=True), annotate() overrides
  Part 3 -- Formatting:         pprint() styles for reasoning, to_dicts()/to_openai()
  Part 4 -- LLM Integration:    generate() with reasoning, ChatResponse.reasoning,
                                reasoning=False, Tract.open(commit_reasoning=False)

Demonstrates: t.reasoning(), ReasoningContent, format=, metadata=,
              compile(include_reasoning=True), annotate(), Priority.PINNED,
              Priority.SKIP, get_content(), get_metadata(),
              pprint() reasoning style (table, chat, compact),
              to_dicts(), to_openai(),
              generate() with reasoning, ChatResponse.reasoning,
              ChatResponse.reasoning_commit, reasoning=False,
              Tract.open(commit_reasoning=False)
"""

import sys
from pathlib import Path

from tract import Priority, Tract

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _providers import cerebras as llm

MODEL_ID = llm.large


# =====================================================================
# Part 1 -- Manual Reasoning Commits
# =====================================================================

def part1_manual_reasoning():
    """Commit reasoning manually -- no LLM needed."""
    print("=" * 60)
    print("Part 1: MANUAL REASONING COMMITS")
    print("=" * 60)
    print()
    print("  t.reasoning() commits chain-of-thought text.")
    print("  Default priority is SKIP -- excluded from compile().")
    print()

    t = Tract.open()

    # Build a conversation with reasoning between user and assistant
    t.system("You are a math tutor. Show your work.")
    t.user("What is 17 * 23?")

    # Reasoning: the model's internal thinking (committed manually here)
    r_info = t.reasoning(
        "17 * 23 = 17 * 20 + 17 * 3 = 340 + 51 = 391",
        format="parsed",
    )

    t.assistant("17 x 23 = 391")

    # --- Reasoning is in log() ---

    print("  log() shows reasoning commits:\n")
    for entry in reversed(t.log()):
        print(f"    {entry}")

    print(f"\n  Reasoning commit: {r_info.commit_hash[:8]}")
    print(f"  Content type:     {r_info.content_type}")

    # --- But excluded from compile() ---

    ctx = t.compile()
    print(f"\n  compile() -> {ctx.commit_count} messages (reasoning excluded):")
    for msg in ctx.messages:
        print(f"    [{msg.role}] {msg.content[:60]}")

    # --- Format and metadata ---

    print(f"\n  t.reasoning() also accepts format= and metadata=:")
    t2 = Tract.open()
    info = t2.reasoning(
        "Let me think step by step...",
        format="think_tags",
        metadata={"source": "deepseek-r1"},
    )
    content = t2.get_content(info.commit_hash)
    print(f"    format:   {content['format']}")
    meta = t2.get_metadata(info.commit_hash)
    print(f"    metadata: {meta}")
    t2.close()

    t.close()


# =====================================================================
# Part 2 -- Compile Control
# =====================================================================

def part2_compile_control():
    """Manual flag toggling for reasoning visibility."""
    print(f"\n{'=' * 60}")
    print("Part 2: COMPILE CONTROL")
    print("=" * 60)
    print()

    t = Tract.open()
    t.system("You are a helpful assistant.")
    t.user("Explain photosynthesis.")
    t.reasoning(
        "Photosynthesis converts CO2 + H2O into glucose + O2 using "
        "sunlight. The light reactions happen in thylakoids, the Calvin "
        "cycle in the stroma. I should keep this concise."
    )
    t.assistant(
        "Photosynthesis converts CO2 and water into glucose and oxygen "
        "using sunlight energy, primarily in chloroplasts."
    )

    # --- Default: reasoning excluded ---

    ctx_default = t.compile()
    print(f"  compile() default:")
    print(f"    {ctx_default.commit_count} messages, {ctx_default.token_count} tokens")
    roles = [m.role for m in ctx_default.messages]
    print(f"    roles: {roles}")

    # --- include_reasoning=True: reasoning included ---

    ctx_with = t.compile(include_reasoning=True)
    print(f"\n  compile(include_reasoning=True):")
    print(f"    {ctx_with.commit_count} messages, {ctx_with.token_count} tokens")
    roles = [m.role for m in ctx_with.messages]
    print(f"    roles: {roles}")
    extra = ctx_with.token_count - ctx_default.token_count
    print(f"    +{extra} tokens from reasoning content")

    # --- Explicit annotation overrides ---

    print(f"\n  Explicit annotations always win:")

    t2 = Tract.open()
    t2.user("Hello")
    info = t2.reasoning("Important chain of thought")
    t2.annotate(info.commit_hash, Priority.PINNED, reason="keep this")
    t2.assistant("Hi!")

    # PINNED reasoning appears even without include_reasoning
    ctx = t2.compile()
    texts = [m.content for m in ctx.messages]
    has_reasoning = "Important chain of thought" in texts
    print(f"    PINNED reasoning in compile(): {has_reasoning}")

    # Explicit SKIP is respected even with include_reasoning=True
    t3 = Tract.open()
    t3.user("Hello")
    info2 = t3.reasoning("Thinking...")
    t3.annotate(info2.commit_hash, Priority.SKIP, reason="exclude this")
    t3.assistant("Hi!")

    ctx2 = t3.compile(include_reasoning=True)
    texts2 = [m.content for m in ctx2.messages]
    has_reasoning2 = "Thinking..." in texts2
    print(f"    Explicit SKIP with include_reasoning=True: hidden={not has_reasoning2}")

    t.close()
    t2.close()
    t3.close()


# =====================================================================
# Part 3 -- Formatting
# =====================================================================

def part3_formatting():
    """pprint styles and format output for reasoning content."""
    print(f"\n{'=' * 60}")
    print("Part 3: FORMATTING")
    print("=" * 60)
    print()
    print("  Reasoning commits render in dim cyan, visually")
    print("  distinct from regular dialogue.\n")

    t = Tract.open()
    t.system("You are a helpful assistant.")
    t.user("What is the capital of France?")
    t.reasoning(
        "The user is asking about France's capital. This is a "
        "straightforward geography question. The answer is Paris."
    )
    t.assistant("The capital of France is Paris.")

    # Include reasoning so pprint() can show it
    ctx = t.compile(include_reasoning=True)

    print("  --- table style ---\n")
    ctx.pprint(style="table")

    print("\n  --- chat style ---\n")
    ctx.pprint(style="chat")

    print("\n  --- compact style ---\n")
    ctx.pprint(style="compact")

    t.close()


def part3b_format_output():
    """to_dicts() and to_openai() with reasoning content."""
    print("=" * 60)
    print("Part 3b: FORMAT OUTPUT FOR APIS")
    print("=" * 60)
    print()
    print("  to_dicts() and to_openai() include reasoning when compiled")
    print("  with include_reasoning=True. This is what agents consume.\n")

    t = Tract.open()
    t.system("You are a helpful assistant.")
    t.user("What is 2 + 2?")
    t.reasoning("Simple arithmetic: 2 + 2 = 4.")
    t.assistant("2 + 2 = 4.")

    # Without reasoning
    ctx_no = t.compile()
    dicts_no = ctx_no.to_dicts()
    print(f"  to_dicts() without reasoning: {len(dicts_no)} messages")
    for d in dicts_no:
        print(f"    [{d['role']}] {d['content'][:50]}")

    # With reasoning
    ctx_yes = t.compile(include_reasoning=True)
    dicts_yes = ctx_yes.to_dicts()
    print(f"\n  to_dicts() with reasoning: {len(dicts_yes)} messages")
    for d in dicts_yes:
        print(f"    [{d['role']}] {d['content'][:50]}")

    print()
    t.close()


# =====================================================================
# Part 4 -- LLM Integration
# =====================================================================

def part4_llm_integration():
    """generate() with reasoning extraction and commit control."""
    if not llm.api_key:
        print(f"\n{'=' * 60}")
        print("Part 4: SKIPPED (no llm.api_key)")
        print("=" * 60)
        return

    print(f"\n{'=' * 60}")
    print("Part 4: LLM REASONING VIA GENERATE()")
    print("=" * 60)
    print()

    # --- 4a: generate() with reasoning ---

    print("  4a: generate() auto-commits reasoning traces\n")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        t.system("Think step by step before answering. Make sure your reasoning is thorough and clear, but your answers are concise")
        t.user("I want to wash my car and the car wash is 50 meters close. Should I drive there or walk?")

        resp = t.generate(reasoning_effort="high")

        if resp.reasoning_commit:
            print(f"  reasoning_commit hash: {resp.reasoning_commit.commit_hash[:8]}")
            print(f"  reasoning_commit type: {resp.reasoning_commit.content_type}")
        else:
            print("  (Model did not produce reasoning tokens)")

        # Compile with include_reasoning=True to see reasoning in pprint
        print(f"\n  compile(include_reasoning=True):\n")
        ctx = t.compile(include_reasoning=True)
        ctx.pprint(style="chat")

    # --- 4b: Per-call opt-out ---

    print(f"\n  4b: reasoning=False skips the commit\n")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
    ) as t:
        t.system("Think step by step.")
        t.user("What is 7 * 8?")

        resp = t.generate(reasoning=False, reasoning_effort="high")

        # Reasoning text is still extracted (if available)...
        print(f"  reasoning extracted: {resp.reasoning is not None}")
        # ...but NOT committed
        print(f"  reasoning committed: {resp.reasoning_commit is not None}")

        log_types = [e.content_type for e in t.log()]
        print(f"  content types in log: {log_types}")
        print(f"  'reasoning' in log: {'reasoning' in log_types}")

    # --- 4c: Global opt-out ---

    print(f"\n  4c: Tract.open(commit_reasoning=False) disables globally\n")

    with Tract.open(
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=MODEL_ID,
        commit_reasoning=False,
    ) as t:
        t.system("Think carefully.")
        t.user("What is 12 + 13?")

        resp = t.generate(reasoning_effort="high")

        print(f"  reasoning extracted: {resp.reasoning is not None}")
        print(f"  reasoning committed: {resp.reasoning_commit is not None}")
        print(f"  (t.reasoning() shorthand still works even with global opt-out)")

        # Manual reasoning is always allowed
        manual = t.reasoning("This was added manually.")
        print(f"  manual commit type:  {manual.content_type}")


# =====================================================================
# Main
# =====================================================================

def main():
    part1_manual_reasoning()
    part2_compile_control()
    part3_formatting()
    part3b_format_output()
    part4_llm_integration()
    print("=" * 60)
    print("Done -- reasoning demonstrated.")
    print("=" * 60)


if __name__ == "__main__":
    main()
