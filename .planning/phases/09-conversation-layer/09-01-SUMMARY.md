---
phase: 09-conversation-layer
plan: 01
subsystem: conversation-layer
tags: [chat, generate, ChatResponse, LLM, convenience-api]
dependency_graph:
  requires: [08-format-commit-shorthand]
  provides: [chat-method, generate-method, ChatResponse-dataclass, open-llm-config]
  affects: [09-02-streaming, 10-cookbook-examples]
tech_stack:
  added: []
  patterns: [delegate-compose, response-wrapping, ownership-tracking]
key_files:
  created:
    - tests/test_conversation.py
  modified:
    - src/tract/protocols.py
    - src/tract/tract.py
    - src/tract/__init__.py
decisions:
  - id: 09-01-D1
    decision: "Response model is authoritative for generation_config"
    rationale: "Actual model used may differ from requested due to aliases/routing"
  - id: 09-01-D2
    decision: "Tract.open() auto-configures LLM only when api_key explicitly provided"
    rationale: "No env var auto-detection; explicit is better than implicit"
  - id: 09-01-D3
    decision: "Tract owns (and closes) internally-created LLM clients, not external ones"
    rationale: "Follows resource ownership principle; external callers manage their own lifecycle"
  - id: 09-01-D4
    decision: "chat()/generate() raise TraceError inside batch()"
    rationale: "LLM calls are side-effects that cannot be rolled back atomically"
metrics:
  duration: 5m
  completed: 2026-02-20
---

# Phase 9 Plan 1: Conversation Layer - chat/generate Methods Summary

**One-liner:** ChatResponse dataclass + Tract.open() LLM config + chat()/generate() composing user/compile/LLM/assistant/usage into one-call operations.

## What Was Built

### ChatResponse (protocols.py)
- Frozen dataclass with `.text`, `.usage` (TokenUsage|None), `.commit_info` (CommitInfo), `.generation_config` (dict)
- Exported from `tract.__init__`

### Tract.open() LLM Config
- New params: `api_key`, `model`, `base_url`
- When `api_key` provided, auto-creates OpenAIClient and calls configure_llm()
- Tracks `_owns_llm_client` and `_default_model` for lifecycle management

### close() Lifecycle
- Internally-created LLM clients (via open() api_key) are closed on Tract.close()
- Externally-provided clients (via configure_llm()) are NOT closed

### generate() Method
- Compile context -> call LLM -> extract content/usage -> build generation_config -> commit assistant response -> record usage
- Returns ChatResponse with all fields populated
- Supports model/temperature/max_tokens overrides per call
- Guards: LLMConfigError without client, TraceError inside batch()

### chat() Method
- Commits user message -> delegates to generate()
- One-call convenience: `resp = t.chat("question")` does everything
- Supports name parameter for user message speaker

### _build_generation_config()
- Response model field is authoritative (actual resolved model)
- Falls back to request model, then _default_model
- Captures temperature and max_tokens from request params

## Test Coverage

31 new tests in `tests/test_conversation.py`:
- 3 ChatResponse dataclass tests (fields, None usage, frozen immutability)
- 5 Tract.open() LLM config tests (api_key, model, base_url, no-key, defaults)
- 3 close() lifecycle tests (internal client closed, external not, no-client)
- 7 generate() tests (happy path, commits, usage, params, message/metadata, errors)
- 6 chat() tests (happy path, context, multi-turn, name, errors)
- 5 _build_generation_config tests (response authoritative, fallbacks, params)
- 2 LLM message forwarding tests (single turn, multi-turn accumulation)

**Total: 952 tests (921 existing + 31 new), all passing.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed CommitInfo construction in unit tests**
- **Found during:** Task 2
- **Issue:** Plan's test template used incorrect CommitInfo constructor (missing required fields, wrong operation enum value)
- **Fix:** Created `_make_commit_info()` helper with valid defaults
- **Files modified:** tests/test_conversation.py

## Requirements Coverage

| Requirement | Status | How |
|-------------|--------|-----|
| LLM-01 (open config) | Complete | api_key/model/base_url on Tract.open() |
| LLM-02 (auto gen_config) | Complete | _build_generation_config() from response + request |
| LLM-03 (auto usage) | Complete | record_usage() auto-called in generate() |
| CONV-01 (chat) | Complete | chat() one-call convenience |
| CONV-02 (generate) | Complete | generate() two-step control |
| CONV-03 (ChatResponse) | Complete | Frozen dataclass with .text/.usage/.commit_info/.generation_config |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 8d33226 | feat | ChatResponse dataclass, LLM config on Tract.open(), close() lifecycle |
| ad45ef9 | feat | chat(), generate(), _build_generation_config() methods and tests |

## Next Phase Readiness

No blockers. Ready for:
- Phase 09-02: Streaming support (if planned)
- Phase 10: Cookbook examples (chat loop is now 1 line per turn)
