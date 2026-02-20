---
phase: 13-unified-operation-events-compile-records
plan: 02
subsystem: operations
tags: [event-repo, compression, gc, rebase, import-commit, provenance]

# Dependency graph
requires:
  - phase: 13-01
    provides: "OperationEventRepository ABC + SQLite impl, OperationEventRow/OperationCommitRow schema"
provides:
  - "compress_range/gc wired to event_repo (save_event/add_commit API)"
  - "rebase creates reorganize events with source/result commit mappings"
  - "import_commit replaces cherry_pick with import event recording"
  - "Tract._event_repo replaces _compression_repo throughout facade"
  - "GCResult.source_commits_removed replaces archives_removed"
  - "ImportResult/ImportIssue/ImportCommitError replace CherryPick equivalents"
affects:
  - "13-03 (compile record persistence)"
  - "CLI commands referencing cherry_pick (if any)"
  - "Cookbook examples using cherry_pick"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "event_repo parameter threading through operation functions"
    - "Optional event_repo for backward-compat (None skips event recording)"
    - "Unified event types: compress, reorganize, import"

key-files:
  modified:
    - "src/tract/operations/compression.py"
    - "src/tract/operations/rebase.py"
    - "src/tract/tract.py"
    - "src/tract/session.py"
    - "src/tract/operations/spawn.py"
    - "src/tract/models/merge.py"
    - "src/tract/models/compression.py"
    - "src/tract/exceptions.py"
    - "src/tract/__init__.py"
    - "tests/test_compression.py"
    - "tests/test_gc.py"
    - "tests/test_rebase.py"

key-decisions:
  - "13-02-D1: GCResult.archives_removed renamed to source_commits_removed for clarity with unified model"
  - "13-02-D2: import_commit event_repo is optional (None skips recording) for backward compat"
  - "13-02-D3: CherryPickError/Result/Issue renamed to ImportCommitError/ImportResult/ImportIssue (clean break)"
  - "13-02-D4: Compression params (target_tokens, instructions) stored in params_json dict"

patterns-established:
  - "event_repo optional parameter pattern: operations work without event recording when None"
  - "event type taxonomy: compress, reorganize, import"

# Metrics
duration: 10min
completed: 2026-02-20
---

# Phase 13 Plan 02: Operation Rewiring Summary

**Wired all operations (compress, GC, rebase, import) to unified OperationEventRepository, dissolved cherry-pick into import_commit, renamed all CherryPick types to Import equivalents**

## Performance

- **Duration:** 10 min
- **Started:** 2026-02-20T22:15:57Z
- **Completed:** 2026-02-20T22:26:01Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- compress_range() and gc() fully rewired from CompressionRepository to OperationEventRepository API
- rebase() now creates "reorganize" events with source/result commit mappings
- cherry_pick() dissolved into import_commit() with "import" event recording
- Tract facade, session.py, and spawn.py all use _event_repo
- CherryPickResult/Issue/Error removed from public API, replaced with ImportResult/Issue/ImportCommitError
- All 76 tests pass (33 compression + 17 GC + 26 rebase)

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewire compression, GC, rebase, and cherry-pick dissolution** - `51d19ab` (feat)
2. **Task 2: Wire Tract facade, session, spawn, exports, and update tests** - `757433d` (feat)

## Files Created/Modified

- `src/tract/operations/compression.py` - event_repo parameter, save_event/add_commit API
- `src/tract/operations/rebase.py` - import_commit function, reorganize event recording
- `src/tract/tract.py` - _event_repo, import_commit method, from_components event_repo param
- `src/tract/session.py` - event_repo wiring in create_tract
- `src/tract/operations/spawn.py` - child_event_repo in spawn_tract
- `src/tract/models/merge.py` - ImportResult/ImportIssue replacing CherryPickResult/CherryPickIssue
- `src/tract/models/compression.py` - GCResult.source_commits_removed
- `src/tract/exceptions.py` - ImportCommitError replacing CherryPickError
- `src/tract/__init__.py` - Updated public exports
- `src/tract/llm/protocols.py` - Updated docstring reference
- `src/tract/llm/resolver.py` - Updated docstring reference
- `tests/test_compression.py` - _event_repo.get_event/get_commits API
- `tests/test_gc.py` - source_commits_removed, event_repo references
- `tests/test_rebase.py` - import_commit/ImportResult/ImportCommitError

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 13-02-D1 | GCResult.archives_removed -> source_commits_removed | Clarity with unified event model |
| 13-02-D2 | event_repo optional (None skips recording) | Backward compat, operations work standalone |
| 13-02-D3 | Clean break: CherryPick* -> Import* types | No aliases, consistent new API surface |
| 13-02-D4 | Compression params in params_json dict | Unified OperationEvent schema handles all event types |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated __init__.py and tract.py TYPE_CHECKING in Task 1**
- **Found during:** Task 1 (import verification)
- **Issue:** __init__.py imported CherryPickIssue/CherryPickResult from merge.py, blocking all import chains
- **Fix:** Updated __init__.py exports and tract.py TYPE_CHECKING as part of Task 1 instead of Task 2
- **Files modified:** src/tract/__init__.py, src/tract/tract.py
- **Verification:** All imports succeed
- **Committed in:** 51d19ab (Task 1 commit)

**2. [Rule 1 - Bug] Updated LLM protocol/resolver docstrings**
- **Found during:** Task 2 (grep sweep for old references)
- **Issue:** llm/protocols.py and llm/resolver.py referenced CherryPickIssue in docstrings
- **Fix:** Updated to ImportIssue
- **Files modified:** src/tract/llm/protocols.py, src/tract/llm/resolver.py
- **Committed in:** 757433d (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All operations (compress, GC, rebase, import) now use unified OperationEventRepository
- Zero references to old compression_repo / CompressionRepository in source
- Zero references to CherryPickResult/Issue/Error in source (only documentation mentions)
- Ready for Plan 03: compile record persistence

---
*Phase: 13-unified-operation-events-compile-records*
*Completed: 2026-02-20*
