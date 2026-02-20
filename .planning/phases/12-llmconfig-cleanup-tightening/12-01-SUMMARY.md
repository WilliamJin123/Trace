---
phase: 12-llmconfig-cleanup-tightening
plan: 01
subsystem: config
tags: [dataclass, frozen, LLMConfig, OperationConfigs, aliases, from_dict, from_obj]

# Dependency graph
requires:
  - phase: 11-llmconfig-query
    provides: LLMConfig frozen dataclass, from_dict/to_dict, query_by_config
provides:
  - OperationConfigs frozen dataclass with typed chat/merge/compress/orchestrate fields
  - LLMConfig.from_dict() alias handling (stop->stop_sequences, max_completion_tokens->max_tokens)
  - LLMConfig.from_dict() API plumbing key ignoring (messages, tools, stream, etc.)
  - LLMConfig.from_obj() for extracting config from arbitrary objects
  - Consolidated _default_config (LLMConfig | None) replacing _default_model (str | None)
  - Tract.open(default_config=, operations=) new parameters
  - configure_operations() dual-path (OperationConfigs or **kwargs)
affects: [12-02-PLAN, future phases using operation config]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen dataclass for typed config with IDE autocomplete and typo detection"
    - "Dual-path API: new typed path + kwargs backward compat"
    - "Alias/ignore preprocessing in from_dict() for cross-framework compatibility"

key-files:
  modified:
    - src/tract/models/config.py
    - src/tract/__init__.py
    - src/tract/tract.py
    - tests/test_operation_config.py
    - tests/test_conversation.py

key-decisions:
  - "12-01-D1: OperationConfigs uses frozen dataclass (not Pydantic) -- matches LLMConfig pattern, runtime-only"
  - "12-01-D2: Alias handling: canonical wins when both alias and canonical present in same dict"
  - "12-01-D3: from_obj() uses dataclass fields > model_dump > vars dispatch for maximum compatibility"
  - "12-01-D4: model= and default_config= are mutually exclusive on Tract.open() -- no ambiguity"
  - "12-01-D5: configure_operations() uses positional-only param for OperationConfigs to avoid name collision"

patterns-established:
  - "Typed config replaces dict: OperationConfigs replaces dict[str, LLMConfig]"
  - "getattr-based resolution on frozen dataclass vs dict.get()"

# Metrics
duration: 5min
completed: 2026-02-20
---

# Phase 12 Plan 01: Config Layer Foundation Summary

**OperationConfigs frozen dataclass with typed fields, LLMConfig.from_dict() alias/ignore handling, from_obj() extraction, and consolidated _default_config replacing _default_model**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-20T03:31:18Z
- **Completed:** 2026-02-20T03:36:42Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- OperationConfigs frozen dataclass with chat/merge/compress/orchestrate fields catches typos at construction time
- LLMConfig.from_dict() handles cross-framework aliases (stop, max_completion_tokens) and drops API plumbing keys
- LLMConfig.from_obj() extracts config from dataclasses, Pydantic models, and plain objects
- _default_model completely eliminated from tract.py, replaced by _default_config: LLMConfig | None
- configure_operations() dual-path: accepts typed OperationConfigs or backward-compatible **kwargs
- 1031 tests passing (20 new, 0 regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: OperationConfigs dataclass + from_dict aliases + from_obj** - `282c748` (feat)
2. **Task 2: Consolidated _default_config and updated Tract init/open/configure/property** - `7724533` (feat)
3. **Task 3: Update tests for new config layer** - `4b81765` (test)

## Files Created/Modified
- `src/tract/models/config.py` - Added _ALIASES, _IGNORED, updated from_dict(), added from_obj(), added OperationConfigs dataclass
- `src/tract/__init__.py` - Added OperationConfigs to imports and __all__
- `src/tract/tract.py` - Replaced _default_model with _default_config, replaced dict with OperationConfigs, updated open/configure/property/resolve
- `tests/test_operation_config.py` - Updated existing tests for attribute access, added 20 new tests
- `tests/test_conversation.py` - Fixed _default_model -> _default_config references

## Decisions Made
- **12-01-D1:** OperationConfigs is a frozen dataclass (matching LLMConfig pattern) -- runtime-only, no persistence needed
- **12-01-D2:** When both alias and canonical key exist in from_dict() input, canonical wins silently -- no error, no ambiguity
- **12-01-D3:** from_obj() dispatch: dataclass fields > model_dump() > vars() -- covers all common Python config patterns
- **12-01-D4:** model= and default_config= are mutually exclusive on Tract.open() with clear ValueError message
- **12-01-D5:** configure_operations() uses positional-only `_configs` param to avoid name collision with operation kwargs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed _default_model reference in test_conversation.py**
- **Found during:** Task 3 (test execution revealed AttributeError)
- **Issue:** test_conversation.py::TestOpenLLMConfig::test_open_with_api_key_and_model asserted `t._default_model` which no longer exists
- **Fix:** Changed assertion to check `t._default_config.model` and updated docstring reference
- **Files modified:** tests/test_conversation.py
- **Verification:** Full test suite passes (1031 tests)
- **Committed in:** 4b81765 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary fix for test that referenced eliminated attribute. No scope creep.

## Issues Encountered
None -- plan executed cleanly.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Config layer foundation complete, ready for Plan 02 (wiring)
- OperationConfigs dataclass ready for 4-level _resolve_llm_config rewrite
- _default_config ready for full-field resolution (not just model)
- from_dict() aliases ready for _build_generation_config capture

---
*Phase: 12-llmconfig-cleanup-tightening*
*Completed: 2026-02-20*
