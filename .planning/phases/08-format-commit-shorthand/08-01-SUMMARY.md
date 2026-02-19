---
phase: 08-format-commit-shorthand
plan: 01
subsystem: dx-layer
tags: [format, shorthand, auto-message, compiled-context, dx]
depends_on:
  requires: []
  provides: [to_dicts, to_openai, to_anthropic, system-shorthand, user-shorthand, assistant-shorthand, auto-message]
  affects: [08-02, 08-03, 09, 10]
tech-stack:
  added: []
  patterns: [format-methods-on-dataclass, shorthand-delegation, auto-message-generation]
key-files:
  created:
    - tests/test_format_shorthand.py
  modified:
    - src/tract/protocols.py
    - src/tract/tract.py
    - tests/test_tract.py
decisions:
  - id: "08-01-D1"
    decision: "to_openai() delegates to to_dicts() (identical format)"
    rationale: "OpenAI uses inline system messages, same as generic format"
  - id: "08-01-D2"
    decision: "to_anthropic() returns {system: str|None, messages: list}"
    rationale: "Anthropic API requires system messages as separate top-level key"
  - id: "08-01-D3"
    decision: "Auto-message uses content_type prefix (e.g. 'instruction: Be helpful')"
    rationale: "Content type provides context, text preview gives specificity"
  - id: "08-01-D4"
    decision: "Auto-message max 72 chars with '...' truncation"
    rationale: "Matches git convention for commit message line length"
  - id: "08-01-D5"
    decision: "message=None triggers auto-gen, message='' stores empty string"
    rationale: "Natural Python convention, no sentinel values needed"
metrics:
  duration: 7m
  completed: 2026-02-19
---

# Phase 8 Plan 01: Format Methods & Commit Shorthand Summary

**One-liner:** CompiledContext.to_dicts/to_openai/to_anthropic for zero-transformation LLM output, plus Tract.system/user/assistant shorthand and auto-generated commit messages.

## What Was Done

### Task 1: Format Methods on CompiledContext
Added three methods to `CompiledContext` frozen dataclass in `src/tract/protocols.py`:
- `to_dicts()` -- returns `list[dict]` with role/content keys (plus name when present)
- `to_openai()` -- delegates to `to_dicts()` (OpenAI uses inline system messages)
- `to_anthropic()` -- returns `{system: str|None, messages: list[dict]}` with system messages extracted to separate key, concatenated with `\n\n`

### Task 2: Shorthand Commit Methods on Tract
Added three methods to `Tract` class in `src/tract/tract.py`:
- `system(text, *, message=, metadata=)` -- commits `InstructionContent`
- `user(text, *, message=, name=, metadata=)` -- commits `DialogueContent(role="user")`
- `assistant(text, *, message=, name=, metadata=, generation_config=)` -- commits `DialogueContent(role="assistant")`

All delegate to `self.commit()` so cache updates, policy evaluation, orchestrator triggers, and budget enforcement all fire correctly.

### Task 3: Auto-Generated Commit Messages
Added `_auto_message()` helper and modified `Tract.commit()`:
- When `message=None`, auto-generates from content type and text preview
- Format: `"{content_type}: {text_preview}"` (max 72 chars)
- Multi-line text flattened to single line
- `message=""` stores empty string (explicit), `message=None` triggers auto-gen
- Logic lives only in Tract facade; CommitEngine unchanged

## Test Results

- **26 new tests** in `tests/test_format_shorthand.py`
- **1 existing test updated** in `tests/test_tract.py` (auto-message expectation)
- **921 total tests passing** (895 baseline + 26 new)
- Zero regressions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated existing test expectation for auto-message**
- **Found during:** Task 3
- **Issue:** `test_get_commit_by_hash` in `test_tract.py` asserted `message is None` when no message provided. With auto-message generation, message is now auto-generated.
- **Fix:** Updated assertion to `message == "instruction: findme"` (auto-generated)
- **Files modified:** `tests/test_tract.py`
- **Commit:** e09f3fd

## Success Criteria Verification

1. compiled.to_dicts() returns list[dict] with "role" and "content" keys -- VERIFIED
2. compiled.to_openai() returns same format as to_dicts() -- VERIFIED
3. compiled.to_anthropic() returns {"system": str|None, "messages": list[dict]} -- VERIFIED
4. t.system(), t.user(), t.assistant() work without importing content models -- VERIFIED
5. commit() auto-generates messages when message=None -- VERIFIED
6. Zero-transformation path: compile() -> to_dicts() requires no manual work -- VERIFIED
7. All existing tests pass (no regressions) -- VERIFIED (921 passed)
