---
phase: "04"
plan: "03"
subsystem: compression
tags: [reorder, gc, garbage-collection, retention, safety-checks]
dependency-graph:
  requires: ["04-02"]
  provides: ["compile-reorder", "gc-operation", "phase-4-complete"]
  affects: ["05-multi-agent"]
tech-stack:
  added: []
  patterns: ["reachability-analysis", "retention-policy", "advisory-warnings"]
key-files:
  created:
    - tests/test_reorder.py
    - tests/test_gc.py
  modified:
    - src/tract/tract.py
    - src/tract/operations/compression.py
    - src/tract/storage/repositories.py
    - src/tract/storage/sqlite.py
    - src/tract/__init__.py
decisions:
  - id: "04-03-01"
    description: "Safety checks are advisory (warnings, not errors) and operate on commit DB, not compiled output"
  - id: "04-03-02"
    description: "compile(order=...) returns tuple (CompiledContext, list[ReorderWarning]) for clean warning delivery"
  - id: "04-03-03"
    description: "GC deletes RefRow entries (ORIG_HEAD etc.) pointing to removed commits to avoid FK violations"
  - id: "04-03-04"
    description: "CommitRepository.delete() handles all FK cleanup: annotations, parent refs, child nullification"
metrics:
  duration: "9m"
  completed: "2026-02-16"
---

# Phase 4 Plan 3: GC & Reorder Summary

Compile-time commit reordering with structural safety checks and garbage collection with configurable retention policies.

## One-liner

compile(order=[...]) reorders messages without mutating DAG; gc() removes unreachable commits with time-based retention for orphans and archives.

## What Was Done

### Task 1: Compile-time reordering with safety checks
- Added `compile(order=..., check_safety=True)` to `Tract.compile()`
- When `order` is provided, compile returns `(CompiledContext, list[ReorderWarning])` tuple
- Reordered compiles bypass the compile cache entirely (always full compile)
- Added `_reorder_compiled()` private method that reorders messages, configs, hashes, and recounts tokens
- Partial ordering supported: commits not in `order` are appended at their original relative positions
- Added `check_reorder_safety()` in `operations/compression.py` that detects:
  - `edit_before_target`: EDIT commit appears before its target in reordered sequence
  - `response_chain_break`: commit references edit_target that's not in the reordered set
- 13 tests covering basic reordering, safety checks (direct + integrated), and edge cases

### Task 2: Garbage collection operation + Tract facade
- Added `gc()` function in `operations/compression.py` with full reachability analysis
- Uses `dag.get_all_ancestors()` for DAG-aware BFS through both parent_hash and CommitParentRow
- Scans ALL branch tips + detached HEAD for reachability (unless `branch=` scoped)
- Retention policies:
  - Orphans: removed if older than `orphan_retention_days` (default 7)
  - Archives: preserved by default (`archive_retention_days=None`); removable when set
- Added `Tract.gc()` facade method
- Added repository methods: `CommitRepository.get_all()`, `CommitRepository.delete()`, `BlobRepository.delete_if_orphaned()`, `CompressionRepository.delete_source()`, `CompressionRepository.delete_result()`
- `CommitRepository.delete()` handles full FK cleanup: annotations, parent rows, child nullification, ref cleanup
- Returns `GCResult(commits_removed, blobs_removed, tokens_freed, archives_removed, duration_seconds)`
- 15 tests covering basic GC, archive preservation, multi-branch reachability, and edge cases

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FK constraint violations during commit deletion**
- **Found during:** Task 2 implementation
- **Issue:** SQLite FK enforcement prevents deleting commits that are referenced by annotations, refs (ORIG_HEAD), and other commits
- **Fix:** Extended `CommitRepository.delete()` to clean up all FK references: AnnotationRow entries, RefRow entries (e.g., ORIG_HEAD), child parent_hash nullification, and edit_target nullification before the actual delete
- **Files modified:** src/tract/storage/sqlite.py
- **Commit:** 9fa68b8

**2. [Rule 2 - Missing Critical] EDIT safety checks tested via direct function**
- **Found during:** Task 1 test development
- **Issue:** EDIT commits are resolved by the compiler (original commit hash replaces EDIT hash in compiled output), so EDIT hashes can't be passed to `compile(order=...)`. Safety checks for edit_before_target can't be tested through compile() integration.
- **Fix:** Tested edit_before_target and response_chain_break directly via `check_reorder_safety()` function, which operates on the commit DB. Integration tests use APPEND-only commits through compile().
- **Files modified:** tests/test_reorder.py
- **Commit:** 1bcfbb1

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 04-03-01 | Safety checks are advisory (warnings, not errors) | Users may have valid reasons to reorder EDITs; warnings inform but don't block |
| 04-03-02 | compile(order=...) returns tuple for warning delivery | CompiledContext is frozen; can't attach warnings. Tuple is clean and backward-compatible (no order = no tuple) |
| 04-03-03 | GC cleans up RefRow entries pointing to removed commits | ORIG_HEAD and similar refs may point to unreachable commits; FK enforcement requires cleanup |
| 04-03-04 | CommitRepository.delete() handles all FK cleanup | Centralizes cleanup logic rather than spreading it across GC; any future code that deletes commits gets the same safety |

## Test Results

- 28 new tests (13 reorder + 15 GC)
- 563 total tests passing (535 + 28)
- Zero regressions

## Phase 4 Success Criteria Verification

1. COMP-01 (Compression storage): Complete (04-01) -- CompressionRow/SourceRow/ResultRow tables, repository
2. COMP-02 (Compression engine): Complete (04-02) -- compress_range(), 3 autonomy modes, provenance
3. COMP-03 (Compile-time reordering): Complete (04-03) -- compile(order=...) with safety checks
4. COMP-04 (Garbage collection): Complete (04-03) -- gc() with retention policies, multi-branch reachability

All 4 Phase 4 success criteria satisfied.

## Next Phase Readiness

Phase 4 is fully complete. Phase 5 (Multi-Agent) can proceed.
- GC provides cleanup capability for multi-agent scenarios with shared databases
- Compression archives are protected by default, enabling safe concurrent use
- Reorder enables agents to customize context presentation without mutating shared history
