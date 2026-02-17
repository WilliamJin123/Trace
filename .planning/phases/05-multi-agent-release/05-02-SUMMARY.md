---
phase: 05-multi-agent-release
plan: 02
subsystem: multi-agent
tags: [session, spawn, collapse, multi-agent, cross-repo-queries, crash-recovery, threading]

# Dependency graph
requires:
  - phase: 05-01
    provides: "SpawnPointerRow schema, SpawnPointerRepository, SessionContent, CollapseResult, collapse prompt, SpawnError/SessionError"
provides:
  - "Session class: multi-agent entry point with shared SQLite DB"
  - "spawn_tract() and collapse_tract() operations with 3 autonomy modes"
  - "5 cross-repo query functions: timeline, search, compile_at, resume, list_tracts"
  - "Tract.parent() and Tract.children() spawn graph helpers"
  - "get_child_tract() for expand-for-debugging from collapse commits"
  - "Crash recovery via Session.open() + resume()"
affects: ["05-03 CLI & Packaging"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Session as shared-engine multi-agent entry point (Tract.open() for single-agent, Session.open() for multi-agent)"
    - "Pre-capture parent state before spawn commit to avoid inheritance pollution"
    - "Commit spawn pointer session before parent commit to avoid SQLite write lock contention"
    - "Pure function cross-repo queries in session_ops.py (no class state)"

key-files:
  created:
    - "src/tract/session.py"
    - "src/tract/operations/spawn.py"
    - "src/tract/operations/session_ops.py"
    - "tests/test_session.py"
    - "tests/test_spawn.py"
  modified:
    - "src/tract/tract.py"
    - "src/tract/__init__.py"

key-decisions:
  - "Pre-capture parent compiled context and commit list before creating spawn commit, preventing inheritance from including the spawn commit itself"
  - "Commit spawn_repo session before parent tract commit to release SQLite write lock and avoid database locked errors"
  - "head_snapshot produces exactly 1 InstructionContent commit with role-prefixed text; full_clone replays all commits with new hashes"
  - "collapse_tract auto_commit defaults based on session autonomy level (autonomous=True, collaborative=False, manual=True)"
  - "get_child_tract reads collapse_source_tract_id from commit metadata for expand-for-debugging"
  - "Concurrent tests use separate tracts per thread (same-tract concurrent writes are not safe due to SQLAlchemy session state)"

patterns-established:
  - "Session.open() as multi-agent entry point, Tract.open() preserved for single-agent backward compatibility"
  - "Spawn operations use pre-captured parent state to ensure clean inheritance boundaries"
  - "Cross-repo query functions are pure (accept session + repos as params)"

# Metrics
duration: 13min
completed: 2026-02-17
---

# Phase 5 Plan 2: Session & Spawn Operations Summary

**Session class with spawn/collapse (3 modes), 5 cross-repo queries, Tract.parent()/children() helpers, crash recovery, and concurrent thread safety**

## Performance

- **Duration:** 13 min
- **Started:** 2026-02-17T17:13:20Z
- **Completed:** 2026-02-17T17:26:17Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Session.open() as multi-agent entry point with shared SQLite engine and per-tract sessions
- spawn_tract() with head_snapshot (compiled context seed) and full_clone (commit replay) inheritance modes
- collapse_tract() with manual, collaborative, and autonomous autonomy modes
- 5 cross-repo queries: timeline(), search(), compile_at(), resume(), list_tracts()
- Tract.parent() and Tract.children() expose spawn graph relationships
- get_child_tract() navigates from collapse commit back to child tract (expand for debugging)
- Crash recovery: reopen Session.open() resumes from last committed state
- 46 new tests including concurrent thread tests; 648 total passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Session class, spawn/collapse operations, and Tract helpers** - `a1ce306` (feat)
2. **Task 2: Cross-repo query operations, exports, and comprehensive tests** - `f55dfaf` (feat)

## Files Created/Modified
- `src/tract/session.py` - Session class: multi-agent entry point with open/create_tract/spawn/collapse/timeline/search/compile_at/resume/list_tracts/get_child_tract
- `src/tract/operations/spawn.py` - spawn_tract(), collapse_tract(), _head_snapshot(), _full_clone(), _row_to_spawn_info()
- `src/tract/operations/session_ops.py` - Pure function cross-repo queries: list_tracts, timeline, search, compile_at, resume
- `src/tract/tract.py` - Added _spawn_repo, parent(), children(), spawn_repo property; SqliteSpawnPointerRepository in open()
- `src/tract/__init__.py` - Exported Session, SessionContent, SpawnInfo, CollapseResult, SpawnError, SessionError
- `tests/test_spawn.py` - 21 tests: spawn creation, inheritance modes, collapse modes, Tract parent/children
- `tests/test_session.py` - 25 tests: lifecycle, cross-repo queries, crash recovery, concurrency, expand-for-debugging

## Decisions Made
- Pre-capture parent state before spawn commit to prevent inheritance pollution (spawn commit should not be inherited by child)
- Commit spawn pointer session before parent commit to avoid SQLite write lock contention between sessions
- head_snapshot compiles parent to text with role prefixes, creates one InstructionContent commit in child
- full_clone replays commits with new hashes (correct behavior: independent commit chains)
- collapse auto_commit defaults based on session autonomy level
- Concurrent thread safety tested with separate tracts per thread (same-session/same-tract concurrent writes are SQLAlchemy limitation)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SQLite database locked during spawn operations**
- **Found during:** Task 2 (test execution)
- **Issue:** spawn_repo.save() flushes but doesn't commit, holding write lock while parent_tract.commit() tries to write through a different session
- **Fix:** Added explicit session.commit() on spawn_repo._session after save() and before parent commit
- **Files modified:** src/tract/operations/spawn.py
- **Verification:** All spawn tests pass without database locked errors
- **Committed in:** f55dfaf (Task 2 commit)

**2. [Rule 1 - Bug] Spawn inheritance included the spawn commit itself**
- **Found during:** Task 2 (test_spawn_full_clone, test_head_snapshot_empty_parent)
- **Issue:** head_snapshot and full_clone captured parent state AFTER spawn commit was created, causing child to inherit the "Spawned subagent for..." commit
- **Fix:** Pre-capture parent compiled context and commit list before creating spawn commit
- **Files modified:** src/tract/operations/spawn.py
- **Verification:** full_clone produces correct commit count; empty parent produces empty child
- **Committed in:** f55dfaf (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered
- SQLite concurrent write locking required careful session commit ordering (resolved by committing spawn pointer before parent commit)
- Pre-capturing parent state before spawn commit required refactoring _head_snapshot to accept CompiledContext instead of Tract

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Session and spawn operations complete, ready for CLI integration in 05-03
- All 13 must-have truths verified through tests
- 648 total tests passing with zero regressions

---
*Phase: 05-multi-agent-release*
*Completed: 2026-02-17*
