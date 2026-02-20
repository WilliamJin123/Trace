---
phase: 13-unified-operation-events-compile-records
plan: 03
subsystem: api, database, testing
tags: [compile-records, provenance, sqlite, testing, cleanup]

# Dependency graph
requires:
  - phase: 13-01
    provides: CompileRecordRow/CompileEffectiveRow schema, SqliteCompileRecordRepository
  - phase: 13-02
    provides: Operation event rewiring, cherry-pick dissolution
provides:
  - Compile record auto-creation in chat()/generate()
  - compile_records() and compile_record_commits() public API
  - Zero old artifact references across entire codebase
  - Full test suite green (1087 tests)
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Compile records created at generate() level, not compile() level"
    - "Compile record saved BEFORE LLM call (records intent, not outcome)"

key-files:
  created:
    - tests/test_compile_records.py
  modified:
    - src/tract/tract.py
    - src/tract/storage/schema.py
    - src/tract/exceptions.py
    - src/tract/models/merge.py
    - tests/test_compression_storage.py
    - tests/test_integration_multiagent.py
    - tests/test_policy_storage.py
    - tests/test_spawn_storage.py
    - tests/test_storage/test_schema.py
    - tests/test_gc.py

key-decisions:
  - "13-03-D1: Compile record created in generate() only, not compile() -- per SC-3 requirement"
  - "13-03-D2: Record saved BEFORE LLM call -- captures what was sent even if LLM fails"
  - "13-03-D3: compile_records() returns newest-first with configurable limit"

patterns-established:
  - "Compile records as provenance: every chat/generate auto-records what was compiled"
  - "Schema version assertions updated to v6 across all migration tests"

# Metrics
duration: 9min
completed: 2026-02-20
---

# Phase 13 Plan 03: Compile Record Wiring + Codebase Sweep Summary

**Compile records auto-persisted by chat()/generate() with 11 integration tests, schema v6 assertions fixed, zero old artifact references**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-20T22:29:32Z
- **Completed:** 2026-02-20T22:39:24Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Wired SqliteCompileRecordRepository into Tract.__init__(), open(), from_components(), and generate()
- generate() auto-creates compile records with head_hash, token_count, commit_count, token_source, and ordered effective commits
- Manual compile() does NOT create records (per SC-3)
- 11 comprehensive compile record integration tests
- Full test suite passing: 1087 tests (1057 existing + 11 new + 19 fixed)
- Zero references to old CompressionRow, CompressionSourceRow, CompressionResultRow, CherryPickResult, CherryPickIssue, CherryPickError in src/ or tests/

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire compile records into Tract.generate() and Tract.open()** - `be8f9a3` (feat)
2. **Task 2: Compile record tests + full suite sweep** - `07cf354` (feat)

## Files Created/Modified
- `src/tract/tract.py` - Added compile_record_repo wiring, generate() record creation, compile_records()/compile_record_commits() accessors
- `tests/test_compile_records.py` - 11 integration tests for compile record lifecycle
- `src/tract/storage/schema.py` - Cleaned old CompressionRow docstring reference
- `src/tract/exceptions.py` - Cleaned old CherryPickError docstring reference
- `src/tract/models/merge.py` - Cleaned old CherryPickIssue/CherryPickResult docstring references
- `tests/test_compression_storage.py` - Fixed archives_removed -> source_commits_removed
- `tests/test_integration_multiagent.py` - Updated schema version assertion v5 -> v6
- `tests/test_policy_storage.py` - Updated schema version assertions and migration test names for v6
- `tests/test_spawn_storage.py` - Updated schema version assertions and migration tests for v6
- `tests/test_storage/test_schema.py` - Updated schema version assertion v5 -> v6
- `tests/test_gc.py` - Cleaned old CompressionResultRow references in comments

## Decisions Made
- **13-03-D1**: Compile record created in generate() only (not compile()) per SC-3 design
- **13-03-D2**: Record saved BEFORE LLM call to capture intent even if LLM fails
- **13-03-D3**: compile_records() returns newest-first with configurable limit (default 100)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed GCResult.archives_removed test**
- **Found during:** Task 2 (full suite run)
- **Issue:** test_compression_storage.py used old field name `archives_removed` instead of `source_commits_removed`
- **Fix:** Updated field name to match renamed model from Plan 13-02
- **Files modified:** tests/test_compression_storage.py
- **Committed in:** 07cf354

**2. [Rule 1 - Bug] Fixed schema version assertions across 4 test files**
- **Found during:** Task 2 (full suite run)
- **Issue:** Multiple tests expected schema_version="5" but Plan 13-01 migrated to v6
- **Fix:** Updated all assertions to expect "6", renamed test methods to reflect v6
- **Files modified:** tests/test_integration_multiagent.py, tests/test_policy_storage.py, tests/test_spawn_storage.py, tests/test_storage/test_schema.py
- **Committed in:** 07cf354

**3. [Rule 1 - Bug] Updated migration tests to account for v5->v6 table changes**
- **Found during:** Task 2 (full suite run)
- **Issue:** Migration tests expected old compression tables to exist post-migration, but v5->v6 drops them
- **Fix:** Updated assertions to verify v6 tables exist and old compression tables are gone
- **Files modified:** tests/test_policy_storage.py, tests/test_spawn_storage.py
- **Committed in:** 07cf354

**4. [Rule 2 - Missing Critical] Removed old type name references from docstrings**
- **Found during:** Task 2 (codebase sweep)
- **Issue:** Docstrings in schema.py, exceptions.py, merge.py still referenced old types (CompressionRow, CherryPickError, etc.)
- **Fix:** Cleaned all docstrings to remove transitional "replaces X" language
- **Files modified:** src/tract/storage/schema.py, src/tract/exceptions.py, src/tract/models/merge.py, tests/test_gc.py
- **Committed in:** 07cf354

---

**Total deviations:** 4 auto-fixed (3 bug fixes, 1 missing critical cleanup)
**Impact on plan:** All fixes necessary for correctness and SC-8 compliance. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 13 is COMPLETE: all 3 plans executed, all 8 success criteria met
- 1087 tests passing with zero old artifact references
- Unified event model (OperationEvent + OperationCommit) replaces all per-operation tables
- Compile records provide full provenance for chat/generate operations
- Ready for next milestone planning

---
*Phase: 13-unified-operation-events-compile-records*
*Completed: 2026-02-20*
