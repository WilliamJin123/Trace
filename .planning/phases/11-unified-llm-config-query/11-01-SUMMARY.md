---
phase: 11-unified-llm-config-query
plan: 01
subsystem: api
tags: [llm-config, dataclass, frozen, pydantic, migration]

# Dependency graph
requires:
  - phase: 10-llm-operation-config
    provides: LLMOperationConfig, configure_operations(), _resolve_llm_config()
provides:
  - LLMConfig frozen dataclass with 9 typed fields + extra dict
  - from_dict/to_dict/non_none_fields conversion methods
  - CommitInfo auto-coercion of dict -> LLMConfig via Pydantic validator
  - ChatResponse.generation_config as LLMConfig
  - CompiledContext.generation_configs as list[LLMConfig | None]
  - Full removal of LLMOperationConfig from codebase
affects: [11-02-query-overhaul, cookbook-examples]

# Tech tracking
tech-stack:
  added: [types.MappingProxyType]
  patterns:
    - "Boundary conversion: LLMConfig at SDK/API, dict at storage/cache"
    - "Pydantic field_validator for auto-coercion at deserialization boundary"
    - "Frozen dataclass with escape-hatch extra dict for provider-specific params"

key-files:
  created: []
  modified:
    - src/tract/models/config.py
    - src/tract/models/commit.py
    - src/tract/protocols.py
    - src/tract/__init__.py
    - src/tract/models/__init__.py
    - src/tract/engine/commit.py
    - src/tract/engine/cache.py
    - src/tract/engine/compiler.py
    - src/tract/tract.py
    - src/tract/operations/diff.py
    - src/tract/toolkit/definitions.py
    - tests/test_operation_config.py
    - tests/test_conversation.py
    - tests/test_tract.py
    - tests/test_merge.py
    - tests/test_rebase.py
    - tests/test_format_shorthand.py
    - tests/test_engine/test_commit.py
    - tests/test_engine/test_compiler.py

key-decisions:
  - "11-01-D1: LLMConfig replaces both LLMOperationConfig (runtime) and dict generation_config (persisted) with one unified type"
  - "11-01-D2: CompileSnapshot internal cache stays tuple[dict,...] -- LLMConfig conversion at boundaries only"
  - "11-01-D3: Pydantic field_validator auto-coerces dict->LLMConfig on CommitInfo construction"
  - "11-01-D4: extra field uses MappingProxyType for immutability, unknown dict keys route to extra"
  - "11-01-D5: Commits without generation_config produce None (not empty LLMConfig) in CompiledContext"

patterns-established:
  - "Boundary pattern: typed LLMConfig at API surface, plain dict at storage/cache layer"
  - "Escape hatch: extra dict for provider-specific params not in the typed schema"

# Metrics
duration: 10min
completed: 2026-02-20
---

# Phase 11 Plan 01: Unified LLM Config Summary

**LLMConfig frozen dataclass with 9 typed fields + extra replaces LLMOperationConfig across all ~20 files, unifying runtime config and persisted generation_config into one type**

## Performance

- **Duration:** 10 min
- **Started:** 2026-02-20T01:56:04Z
- **Completed:** 2026-02-20T02:06:56Z
- **Tasks:** 2
- **Files modified:** 19

## Accomplishments
- Defined LLMConfig with model, temperature, top_p, max_tokens, stop_sequences, frequency_penalty, presence_penalty, top_k, seed, extra -- covers all major LLM provider params
- Complete removal of LLMOperationConfig from entire codebase (zero grep matches)
- Auto-coercion at all boundaries: CommitInfo Pydantic validator, cache to_compiled/build_snapshot, compiler compile()
- All 990 tests passing (7 new LLMConfig-specific tests added)

## Task Commits

Each task was committed atomically:

1. **Task 1: Define LLMConfig and migrate models/protocols layer** - `699650f` (feat)
2. **Task 2: Migrate facade, operations, and all tests** - `8d9e155` (feat)

## Files Created/Modified
- `src/tract/models/config.py` - LLMConfig frozen dataclass replacing LLMOperationConfig
- `src/tract/models/commit.py` - CommitInfo.generation_config: Optional[LLMConfig] with auto-coercion
- `src/tract/protocols.py` - ChatResponse.generation_config: LLMConfig, CompiledContext.generation_configs: list[LLMConfig | None]
- `src/tract/__init__.py` - Export LLMConfig, remove LLMOperationConfig
- `src/tract/models/__init__.py` - Export LLMConfig
- `src/tract/engine/cache.py` - Boundary conversion: from_dict at to_compiled, to_dict at build_snapshot
- `src/tract/engine/compiler.py` - Compiler produces LLMConfig objects directly
- `src/tract/tract.py` - All references migrated, _resolve_llm_config handles new typed fields
- `src/tract/operations/diff.py` - _compute_generation_config_changes handles LLMConfig inputs
- `src/tract/toolkit/definitions.py` - Serialize LLMConfig via to_dict() for display
- `tests/test_operation_config.py` - All tests migrated to LLMConfig with new tests added

## Decisions Made
- **11-01-D1:** Single LLMConfig type replaces both runtime (LLMOperationConfig) and persisted (dict generation_config) -- eliminates the type gap
- **11-01-D2:** CompileSnapshot internal cache format stays as tuple[dict, ...] -- conversion only at API boundaries for performance
- **11-01-D3:** Pydantic field_validator on CommitInfo auto-coerces dict -> LLMConfig -- backward compatible with all existing code paths
- **11-01-D4:** extra field wrapped in MappingProxyType for immutability; unknown dict keys automatically route to extra in from_dict()
- **11-01-D5:** Commits without generation_config produce None (not empty LLMConfig()) in CompiledContext.generation_configs

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LLMConfig type ready for Plan 02 (query overhaul)
- All commit/compile/cache/facade paths produce LLMConfig objects
- from_dict/to_dict methods enable seamless SQL query integration in Plan 02

---
*Phase: 11-unified-llm-config-query*
*Completed: 2026-02-20*
