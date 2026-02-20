---
phase: 10
plan: 01
subsystem: llm-config
tags: [per-operation, llm, configuration, dx]
depends_on:
  requires: [phase-9]
  provides: [per-operation-llm-config, LLMOperationConfig, configure_operations, _resolve_llm_config]
  affects: []
tech-stack:
  added: []
  patterns: [frozen-dataclass-config, three-level-resolution-chain, dataclasses-replace-mutation-safety]
key-files:
  created:
    - tests/test_operation_config.py
  modified:
    - src/tract/models/config.py
    - src/tract/tract.py
    - src/tract/operations/compression.py
    - src/tract/__init__.py
decisions:
  - id: 10-01-D1
    decision: "LLMOperationConfig is a frozen dataclass (not Pydantic)"
    rationale: "Runtime-only config, not persisted; avoids Pydantic overhead"
  - id: 10-01-D2
    decision: "Three-level resolution: call > operation > tract default"
    rationale: "Most specific wins; matches CSS specificity mental model"
  - id: 10-01-D3
    decision: "dataclasses.replace() for mutation-safe OrchestratorConfig updates"
    rationale: "Avoids mutating caller-supplied objects; functional immutability pattern"
  - id: 10-01-D4
    decision: "auto_message excluded from per-operation config"
    rationale: "_auto_message() is a pure-string function with no LLM call"
  - id: 10-01-D5
    decision: "Orchestrate resolution happens BEFORE three-way branch"
    rationale: "Ensures all code paths (new, reuse, default) benefit from operation config"
metrics:
  duration: 8m
  completed: 2026-02-20
  tests-added: 31
  tests-total: 983
---

# Phase 10 Plan 01: Per-Operation LLM Config Summary

**One-liner:** Frozen LLMOperationConfig dataclass with three-level resolution chain (call > operation > tract) wired through all 4 LLM-powered operations.

## What Was Built

### LLMOperationConfig (src/tract/models/config.py)
- Frozen dataclass with `model`, `temperature`, `max_tokens`, `extra_kwargs` fields
- All fields default to None (inherit from higher level)
- Exported from `tract` package

### Resolution Chain (src/tract/tract.py)
- `_resolve_llm_config(operation, *, model, temperature, max_tokens, **kwargs)` private helper
- Three-level precedence: call-level params > operation-level config > tract-level default
- `extra_kwargs` from operation config merged with call kwargs overriding
- `configure_operations(**configs)` public method with type validation
- `operation_configs` read-only property returning a copy
- `Tract.open(operation_configs=...)` parameter for upfront configuration

### Operations Wired
1. **chat/generate** -- `_resolve_llm_config("chat")` before `llm_client.chat()`; resolved model flows into `generation_config` for accurate tracking
2. **merge** -- `_resolve_llm_config("merge")` creates tailored `OpenAIResolver` with resolved model/temperature/max_tokens; new `temperature` and `max_tokens` params on `merge()`
3. **compress** -- `_resolve_llm_config("compress")` passed as `llm_kwargs` through `compress_range()` to `_summarize_group()` to `llm_client.chat()`; new `model`, `temperature`, `max_tokens` params on `compress()`
4. **orchestrate** -- `_resolve_llm_config("orchestrate")` resolved BEFORE three-way branch; `dataclasses.replace()` for mutation-safe `OrchestratorConfig` updates

### Tests (tests/test_operation_config.py)
- 31 tests across 9 test classes (597 lines)
- Coverage: dataclass creation/frozen, configure_operations validation, resolution chain, Tract.open() integration, chat/generate/merge/compress/orchestrate integration, backward compatibility

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 10-01-D1 | LLMOperationConfig is a frozen dataclass | Runtime-only, not persisted; clean and simple |
| 10-01-D2 | Three-level resolution chain | Most specific wins; natural mental model |
| 10-01-D3 | dataclasses.replace() for OrchestratorConfig | Avoid mutating caller-supplied objects |
| 10-01-D4 | auto_message excluded | Pure-string function, no LLM call |
| 10-01-D5 | Orchestrate resolution before three-way branch | All code paths benefit from operation config |

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

```
983 passed in 39.41s
```
- 952 existing tests: all pass (no regressions)
- 31 new tests: all pass

## Success Criteria Verification

1. **Different models per operation** -- Verified: configure chat with one model, compress with another, each operation receives its configured model (tests: test_chat_uses_operation_config_model, test_compress_uses_operation_config)
2. **Per-operation defaults persist** -- Verified: configure once, multiple calls use the config (tests: test_configure_overwrites_existing, integration tests)
3. **Call-level overrides work** -- Verified: model= on chat/compress/merge overrides operation config (tests: test_chat_call_override_beats_operation, test_compress_call_level_model_override)
4. **Backward compatible** -- Verified: 952 existing tests pass without modification (tests: test_no_operation_config_chat_unchanged, test_no_operation_config_compress_unchanged)
5. **LLM-04 requirement** -- Complete: per-operation LLM config fully implemented
