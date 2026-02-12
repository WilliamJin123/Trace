---
phase: 02-linear-history-cli
plan: 01
subsystem: storage, navigation
tags: [symbolic-refs, prefix-matching, reset, checkout, detached-head, navigation]

# Dependency graph
requires:
  - phase: 01-foundations
    provides: "CommitRepository, RefRepository, CommitEngine, Tract facade, RefRow.symbolic_target column"
  - phase: 01.4-lru-compile-cache-snapshot-patching
    provides: "LRU compile cache that navigation operations interact with"
provides:
  - "Symbolic ref infrastructure (HEAD -> refs/heads/main resolution)"
  - "Prefix matching for user-friendly commit references (min 4 chars)"
  - "Navigation operations: reset (soft/hard), checkout (branch/commit/-)"
  - "Detached HEAD state detection and commit guard"
  - "PREV_HEAD and ORIG_HEAD ref tracking"
  - "DetachedHeadError and AmbiguousPrefixError exceptions"
  - "Tract.reset(), Tract.checkout(), Tract.resolve_commit() facade methods"
  - "Tract.is_detached, Tract.current_branch properties"
affects:
  - 02-02 (log, status, diff need symbolic ref state awareness)
  - 02-03 (CLI needs all navigation commands)
  - 03 (branching builds on symbolic ref infrastructure)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "operations/ package for higher-level composites over storage primitives"
    - "Symbolic refs: HEAD -> refs/heads/{branch} -> commit_hash (git model)"
    - "PREV_HEAD/ORIG_HEAD tracking for position history"
    - "checkout('-') swap pattern: read PREV_HEAD before overwriting"

key-files:
  created:
    - src/tract/operations/__init__.py
    - src/tract/operations/navigation.py
    - tests/test_navigation.py
  modified:
    - src/tract/exceptions.py
    - src/tract/storage/repositories.py
    - src/tract/storage/sqlite.py
    - src/tract/tract.py
    - src/tract/__init__.py

key-decisions:
  - "Symbolic HEAD: first commit creates HEAD -> refs/heads/main symbolic ref (git-style)"
  - "update_head backward compat: detects attached/detached/new state and updates correctly"
  - "checkout('-') reads PREV_HEAD before overwriting to avoid self-reference bug"
  - "reset soft and hard are identical in Trace (no working directory); distinction exists for API compatibility"
  - "Prefix matching minimum 4 characters (same as git)"

patterns-established:
  - "operations/ package: higher-level operations composing storage primitives"
  - "Symbolic ref resolution chain: HEAD.symbolic_target -> branch_ref.commit_hash"
  - "Navigation functions are pure (take repos as args), Tract methods are facade"

# Metrics
duration: 5min
completed: 2026-02-12
---

# Phase 2 Plan 1: Navigation Infrastructure Summary

**Symbolic refs with prefix matching, reset/checkout operations, and detached HEAD guard through new operations/ package**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-12T17:55:08Z
- **Completed:** 2026-02-12T18:00:28Z
- **Tasks:** 2
- **Files modified:** 8 (5 modified, 3 created)

## Accomplishments
- Storage layer extended with symbolic ref infrastructure (HEAD -> refs/heads/main) and prefix matching (LIKE query, min 4 chars)
- Navigation operations module (reset, checkout, resolve_commit) with PREV_HEAD/ORIG_HEAD position tracking
- Detached HEAD blocks commits with clear error message guiding user to checkout branch
- LRU compile cache survives navigation operations -- checkout back to previously-compiled HEAD gets cache hit
- 35 new tests covering all navigation paths; 302 total tests passing (267 existing + 35 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Storage infrastructure -- symbolic refs, prefix matching, new exceptions** - `ffed06b` (feat)
2. **Task 2: Navigation operations -- reset, checkout, resolve_commit + Tract facade + tests** - `55ad1ef` (feat)

## Files Created/Modified
- `src/tract/exceptions.py` - Added DetachedHeadError, AmbiguousPrefixError
- `src/tract/storage/repositories.py` - Extended CommitRepository (get_by_prefix) and RefRepository (symbolic ref ops)
- `src/tract/storage/sqlite.py` - Implemented prefix LIKE query, symbolic ref HEAD resolution, attach/detach ops
- `src/tract/operations/__init__.py` - New operations package
- `src/tract/operations/navigation.py` - resolve_commit, reset, checkout functions
- `src/tract/tract.py` - Tract.reset(), checkout(), resolve_commit(), is_detached, current_branch + detached HEAD guard
- `src/tract/__init__.py` - Exported DetachedHeadError, AmbiguousPrefixError
- `tests/test_navigation.py` - 35 tests across 7 test classes (444 lines)

## Decisions Made
- **Symbolic HEAD model:** First commit creates `HEAD -> refs/heads/main` symbolic ref and `refs/heads/main -> commit_hash` branch ref. This mirrors git's model and naturally supports branching in Phase 3.
- **update_head backward compatibility:** Existing callers (CommitEngine) call `update_head(tract_id, commit_hash)` without knowing about symbolic refs. The method auto-detects state (no HEAD, attached, detached) and does the right thing.
- **checkout('-') order of operations:** Must read PREV_HEAD before overwriting it with current HEAD, otherwise the swap self-references. This was caught and fixed during development (Rule 1 bug fix).
- **reset soft == hard in Trace:** Both modes are identical because Trace has no working directory. The distinction exists for API familiarity with git and future extensions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] checkout('-') read order**
- **Found during:** Task 2 (test_checkout_dash_returns_to_prev)
- **Issue:** checkout() wrote PREV_HEAD = current_head before reading it for "-" target, causing self-reference
- **Fix:** Restructured checkout() to read PREV_HEAD before overwriting when target is "-"
- **Files modified:** src/tract/operations/navigation.py
- **Verification:** test_checkout_dash_returns_to_prev passes
- **Committed in:** 55ad1ef (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential correctness fix for checkout('-'). No scope creep.

## Issues Encountered
None beyond the checkout('-') bug fixed above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Storage layer has full symbolic ref and prefix matching infrastructure
- Navigation operations (reset, checkout) ready for CLI integration (Plan 03)
- Log/status/diff (Plan 02) can query HEAD state via is_detached/current_branch
- Branching (Phase 3) can build directly on symbolic ref infrastructure

---
*Phase: 02-linear-history-cli*
*Completed: 2026-02-12*
