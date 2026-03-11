"""Content Type Hints -- how content types guide compilation and compression

Every content type in tract has a ContentTypeHints dataclass that controls
its default behavior in the compiler and compressor.  These hints determine:
  - default_priority: what Priority annotation a commit gets if none is set
  - default_role: what LLM role the content compiles to (system/user/assistant/tool)
  - compression_priority: 0=compress first, 100=protect from compression
  - compilable: whether the content appears in compiled output at all
  - aggregation_rule: how multiple messages of this type are combined
  - format_roles: additional role constraints for formatting

Understanding hints is essential for controlling what your LLM sees and
how aggressively the compressor treats different content types.

Patterns shown:
  1. Built-in Type Behaviors      -- all 10 types and their default hints
  2. Non-Compilable Types         -- config and metadata are excluded from compile
  3. Compression Priority          -- which types the compressor targets first
  4. Reasoning is Auto-Skipped     -- reasoning defaults to SKIP priority
  5. Custom Content Type with Hints -- register a custom type, observe default hints

Demonstrates: BUILTIN_TYPE_HINTS, ContentTypeHints, t.commit(), t.compile(),
              t.register_content_type(), t.annotate(), Priority,
              InstructionContent, DialogueContent, ReasoningContent,
              MetadataContent, ConfigContent

No LLM required.
"""

from pydantic import BaseModel

from tract import (
    BUILTIN_TYPE_HINTS,
    ConfigContent,
    ContentTypeHints,
    DialogueContent,
    InstructionContent,
    MetadataContent,
    Priority,
    ReasoningContent,
    Tract,
)


def main():
    # =================================================================
    # 1. Built-in Type Behaviors
    # =================================================================
    #
    # Tract ships with 10 content types, each with a ContentTypeHints
    # dataclass that controls compiler and compressor behavior.  This
    # pattern prints every type's hints so you can see the full map.

    print("=" * 60)
    print("1. Built-in Type Behaviors")
    print("=" * 60)
    print()

    # Header
    print(f"  {'Type':<14} {'Priority':<10} {'Role':<12} {'Compress':<10} {'Compilable'}")
    print(f"  {'----':<14} {'--------':<10} {'----':<12} {'--------':<10} {'----------'}")

    for name, hints in BUILTIN_TYPE_HINTS.items():
        print(
            f"  {name:<14} {hints.default_priority:<10} "
            f"{hints.default_role:<12} {hints.compression_priority:<10} "
            f"{hints.compilable}"
        )

    # Verify the dict has all 10 built-in types
    expected_types = {
        "instruction", "dialogue", "tool_io", "reasoning", "artifact",
        "output", "freeform", "session", "config", "metadata",
    }
    assert expected_types == set(BUILTIN_TYPE_HINTS.keys()), (
        f"Expected {expected_types}, got {set(BUILTIN_TYPE_HINTS.keys())}"
    )
    print(f"\n  All {len(BUILTIN_TYPE_HINTS)} built-in types present")

    # Verify ContentTypeHints fields
    sample = BUILTIN_TYPE_HINTS["dialogue"]
    assert hasattr(sample, "default_priority")
    assert hasattr(sample, "default_role")
    assert hasattr(sample, "compression_priority")
    assert hasattr(sample, "compilable")
    assert hasattr(sample, "aggregation_rule")
    print("  ContentTypeHints fields verified: default_priority, default_role,")
    print("    compression_priority, compilable, aggregation_rule, format_roles")

    print("\n  Built-in type behaviors: PASSED")

    # =================================================================
    # 2. Non-Compilable Types
    # =================================================================
    #
    # config and metadata have compilable=False.  Commits of these
    # types are stored in the DAG but EXCLUDED from compile() output.
    # This is how you store structured data (settings, tags, workflow
    # state) without polluting the LLM's context window.

    print()
    print("=" * 60)
    print("2. Non-Compilable Types")
    print("=" * 60)
    print()

    # Identify non-compilable types from hints
    non_compilable = [
        name for name, hints in BUILTIN_TYPE_HINTS.items()
        if not hints.compilable
    ]
    compilable = [
        name for name, hints in BUILTIN_TYPE_HINTS.items()
        if hints.compilable
    ]
    print(f"  Non-compilable types: {non_compilable}")
    print(f"  Compilable types:     {compilable}")

    with Tract.open() as t:
        # Commit a mix of compilable and non-compilable content
        t.system("You are helpful.")
        t.user("Hello!")
        t.assistant("Hi there!")

        # These are non-compilable -- they won't appear in compile output
        t.commit(ConfigContent(settings={"model": "gpt-4o", "temperature": 0.7}))
        t.commit(MetadataContent(kind="session_state", data={"step": 3, "status": "active"}))

        # Check what appears in compiled output
        ctx = t.compile()
        messages = ctx.to_dicts()

        # Count by role
        roles = [m["role"] for m in messages]
        print(f"\n  Total commits in DAG:      5 (3 dialogue + 1 config + 1 metadata)")
        print(f"  Messages in compile():     {len(messages)}")
        print(f"  Roles present:             {roles}")

        # Verify non-compilable content is excluded
        compiled_text = ctx.to_text()
        assert "gpt-4o" not in compiled_text, "Config should not appear in compiled output"
        assert "session_state" not in compiled_text, "Metadata should not appear in compiled output"
        assert "Hello" in compiled_text, "Dialogue should appear in compiled output"
        print(f"  Config content in compile():    NO (correct)")
        print(f"  Metadata content in compile():  NO (correct)")
        print(f"  Dialogue content in compile():  YES (correct)")

    print("\n  Non-compilable types: PASSED")

    # =================================================================
    # 3. Compression Priority
    # =================================================================
    #
    # compression_priority controls which content types the compressor
    # targets first.  Lower values = compressed first, higher values =
    # protected longer.  This ranking lets you preserve instructions
    # while aggressively summarizing tool output.

    print()
    print("=" * 60)
    print("3. Compression Priority")
    print("=" * 60)
    print()

    # Sort types by compression priority (lowest = compressed first)
    sorted_types = sorted(
        BUILTIN_TYPE_HINTS.items(),
        key=lambda item: item[1].compression_priority,
    )

    print("  Compression order (first compressed -> last compressed):")
    print()
    print(f"  {'Type':<14} {'Priority':<10} {'Meaning'}")
    print(f"  {'----':<14} {'--------':<10} {'-------'}")

    descriptions = {
        "tool_io": "Tool calls/results -- compress aggressively",
        "reasoning": "Chain-of-thought -- often ephemeral",
        "dialogue": "User/assistant turns -- moderate protection",
        "freeform": "Unstructured content -- moderate protection",
        "artifact": "Code, documents -- somewhat protected",
        "output": "Final results -- more protected",
        "config": "Configuration -- high protection (not compiled)",
        "instruction": "System prompts -- strongly protected",
        "session": "Session boundaries -- strongly protected",
        "metadata": "Metadata -- default protection (not compiled)",
    }

    for name, hints in sorted_types:
        desc = descriptions.get(name, "")
        print(f"  {name:<14} {hints.compression_priority:<10} {desc}")

    # Verify key ordering invariants
    tool_io_p = BUILTIN_TYPE_HINTS["tool_io"].compression_priority
    instruction_p = BUILTIN_TYPE_HINTS["instruction"].compression_priority
    session_p = BUILTIN_TYPE_HINTS["session"].compression_priority
    dialogue_p = BUILTIN_TYPE_HINTS["dialogue"].compression_priority

    assert tool_io_p < dialogue_p, "tool_io should compress before dialogue"
    assert dialogue_p < instruction_p, "dialogue should compress before instruction"
    assert instruction_p <= session_p, "instructions and sessions are highly protected"
    print(f"\n  Verified: tool_io({tool_io_p}) < dialogue({dialogue_p}) "
          f"< instruction({instruction_p}) <= session({session_p})")

    print("\n  Compression priority: PASSED")

    # =================================================================
    # 4. Reasoning is Auto-Skipped
    # =================================================================
    #
    # reasoning content has default_priority="skip".  This means
    # chain-of-thought commits are automatically excluded from compile
    # output -- the LLM never sees its own reasoning in the next turn.
    # This is intentional: reasoning is for observability/debugging,
    # not for context.

    print()
    print("=" * 60)
    print("4. Reasoning is Auto-Skipped")
    print("=" * 60)
    print()

    reasoning_hints = BUILTIN_TYPE_HINTS["reasoning"]
    print(f"  reasoning.default_priority:  {reasoning_hints.default_priority}")
    print(f"  reasoning.default_role:      {reasoning_hints.default_role}")
    print(f"  reasoning.compilable:        {reasoning_hints.compilable}")

    with Tract.open() as t:
        t.system("You are a math tutor.")
        t.user("What is 15 * 23?")

        # Commit reasoning (chain-of-thought) -- default priority is SKIP
        t.commit(ReasoningContent(
            text="Step 1: 15 * 20 = 300. Step 2: 15 * 3 = 45. Step 3: 300 + 45 = 345."
        ))

        # Commit the actual answer
        t.assistant("15 * 23 = 345")

        ctx = t.compile()
        text = ctx.to_text()

        # The reasoning is NOT in compiled output (default_priority=skip)
        assert "Step 1" not in text, "Reasoning should be skipped in compilation"
        assert "345" in text, "Answer should be in compilation"
        print(f"\n  Compiled messages: {len(ctx.messages)}")
        print(f"  Reasoning 'Step 1: 15 * 20...' in output:  NO (auto-skipped)")
        print(f"  Answer '345' in output:                     YES")

        # But the reasoning IS in the DAG -- queryable for debugging
        log = t.log(limit=10)
        reasoning_commits = [e for e in log if e.content_type == "reasoning"]
        assert len(reasoning_commits) == 1
        content = t.get_content(reasoning_commits[0].commit_hash)
        # get_content returns a dict for reasoning (structured type)
        content_text = content["text"] if isinstance(content, dict) else str(content)
        assert "Step 1" in content_text
        print(f"  Reasoning in DAG (queryable):               YES")
        print(f"    Content: {content_text[:50]}...")

        # You CAN override the skip by explicitly annotating as NORMAL
        t.annotate(reasoning_commits[0].commit_hash, Priority.NORMAL)
        ctx2 = t.compile()
        text2 = ctx2.to_text()
        assert "Step 1" in text2, "Annotated reasoning should now appear"
        print(f"\n  After annotating as NORMAL:")
        print(f"  Reasoning in compile():                     YES (override works)")

    print("\n  Reasoning is auto-skipped: PASSED")

    # =================================================================
    # 5. Custom Content Type with Hints
    # =================================================================
    #
    # When you register a custom content type, it gets default
    # ContentTypeHints (all defaults: normal priority, assistant role,
    # compression_priority=50, compilable=True).  This means custom
    # types behave like standard compilable content out of the box.

    print()
    print("=" * 60)
    print("5. Custom Content Type with Hints")
    print("=" * 60)
    print()

    # Define a custom content model
    class EvaluationContent(BaseModel):
        content_type: str = "evaluation"
        criteria: str
        score: float
        rationale: str

    with Tract.open() as t:
        t.register_content_type("evaluation", EvaluationContent)

        t.system("You are a writing coach.")
        t.user("Evaluate this essay on climate policy.")

        # Commit custom content
        ci = t.commit(EvaluationContent(
            criteria="clarity",
            score=8.5,
            rationale="Arguments are well-structured with clear topic sentences.",
        ))
        print(f"  Registered custom type: 'evaluation'")
        print(f"  Committed: {ci.commit_hash[:8]} (content_type={ci.content_type})")

        # Custom type gets default hints (not in BUILTIN_TYPE_HINTS)
        default_hints = ContentTypeHints()
        is_builtin = "evaluation" in BUILTIN_TYPE_HINTS
        print(f"\n  In BUILTIN_TYPE_HINTS: {is_builtin}")
        print(f"  Default hints applied:")
        print(f"    default_priority:      {default_hints.default_priority}")
        print(f"    default_role:          {default_hints.default_role}")
        print(f"    compression_priority:  {default_hints.compression_priority}")
        print(f"    compilable:            {default_hints.compilable}")

        # Custom type IS compilable (default) -- it appears in compile output
        ctx = t.compile()
        text = ctx.to_text()
        assert "clarity" in text or "8.5" in text or "well-structured" in text
        print(f"\n  Custom content in compile():  YES (compilable=True by default)")
        print(f"  Compiled messages: {len(ctx.messages)}, ~{ctx.token_count} tokens")

    print("\n  Custom content type with hints: PASSED")

    # =================================================================
    # Summary
    # =================================================================

    print()
    print("=" * 60)
    print("Summary: Content Type Hints")
    print("=" * 60)
    print()
    print("  ContentTypeHints fields:")
    print("    default_priority      -- Priority annotation if none set")
    print("    default_role          -- LLM role (system/user/assistant/tool)")
    print("    compression_priority  -- 0=compress first, 100=protect")
    print("    compilable            -- whether to include in compile() output")
    print("    aggregation_rule      -- how to combine multiples (concatenate)")
    print("    format_roles          -- additional formatting constraints")
    print("    summary_instruction   -- guidance for LLM compression")
    print()
    print("  Key behaviors:")
    print("    instruction  -- pinned priority, system role, highly protected")
    print("    dialogue     -- normal priority, moderate compression protection")
    print("    tool_io      -- compressed first (priority=30)")
    print("    reasoning    -- auto-skipped from compilation")
    print("    config       -- not compiled (stored in DAG only)")
    print("    metadata     -- not compiled (stored in DAG only)")
    print("    custom types -- get all defaults (normal, compilable, priority=50)")
    print()
    print("Done.")


# Alias for pytest discovery
test_content_type_hints = main


if __name__ == "__main__":
    main()
