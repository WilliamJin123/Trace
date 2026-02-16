---
phase: 04
plan: 02
subsystem: compression
tags: [compression, llm, summarization, provenance]
dependency-graph:
  requires: ["04-01"]
  provides: ["compress_range operation", "Tract.compress() facade", "3 autonomy modes"]
  affects: ["04-03"]
tech-stack:
  added: []
  patterns: ["operations pattern (compress_range)", "3 autonomy modes (auto/collaborative/manual)", "chain rewriting with PINNED preservation"]
key-files:
  created:
    - src/tract/operations/compression.py
    - tests/test_compression.py
  modified:
    - src/tract/tract.py
    - src/tract/__init__.py
decisions:
  - id: "04-02-01"
    description: "Single summary in manual mode covers all groups (no per-group manual text)"
  - id: "04-02-02"
    description: "Chain rewriting: reset HEAD to pre-range parent, replay PINNED + summaries via create_commit()"
  - id: "04-02-03"
    description: "PendingCompression stores hidden context (_range_commits etc.) for deferred commit"
  - id: "04-02-04"
    description: "Root commit range handled by deleting branch ref so get_head returns None"
metrics:
  duration: "8m"
  completed: "2026-02-16"
---

# Phase 4 Plan 02: Compression Engine Summary

Compression engine with 3 autonomy modes (autonomous LLM, collaborative review, manual content), PINNED preservation, and provenance recording. 25 new tests, 535 total passing.

## Completed Tasks

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | compress_range() operation + Tract facade | ab96f4d | src/tract/operations/compression.py, src/tract/tract.py, src/tract/__init__.py |
| 2 | Compression integration tests | 7554846 | tests/test_compression.py |

## What Was Built

### operations/compression.py
- `_resolve_commit_range()`: First-parent chain walking with explicit/range/default modes
- `_classify_by_priority()`: Batch annotation lookup, PINNED/NORMAL/SKIP classification
- `_partition_around_pinned()`: Group NORMAL commits between PINNED boundaries
- `_build_messages_text()`: Format commits for LLM summarization (own implementation, not shared with merge)
- `_reconstruct_content()`: Deserialize blob back to Pydantic model for PINNED re-creation
- `_summarize_group()`: LLM call with configurable system prompt and instructions
- `_commit_compression()`: Core chain rewriting -- reset HEAD, replay summaries + PINNED, record provenance
- `compress_range()`: Orchestrator for all 3 modes

### tract.py Changes
- `compression_repo` parameter added to `__init__()` and `Tract.open()`
- `SqliteCompressionRepository` wired in `open()`
- `Tract.compress()`: 3 autonomy modes with detached HEAD guard
- `Tract._finalize_compression()`: Deferred commit for collaborative mode
- `Tract.approve_compression()`: Public alternative to `pending.approve()`

### Test Coverage (25 tests)
- **Autonomous mode** (7): all-normal, preserve-pinned, ignore-skip, range, commit-list, target-tokens, instructions
- **Collaborative mode** (4): auto_commit=False, edit-summary, approve, approve-method
- **Manual mode** (3): manual-content, no-llm-required, manual-preserves-pinned
- **Provenance** (4): record-created, unreachable-originals, query-sources, query-results
- **Edge cases** (5): no-commits, no-llm-no-content, all-pinned, cache-clear, compile-coherent
- **Multi-pinned interleaving** (2): ordering, boundaries

## Decisions Made

1. **Single summary in manual mode**: When `content=` is provided with multiple groups (due to PINNED interleaving), one summary covers the first group. Subsequent groups after PINNED commits have no separate summary. This is the simplest correct behavior.

2. **Chain rewriting approach**: Reset HEAD to pre-range parent, then replay PINNED commits (reconstructed content) and summary commits via `create_commit()`. Each call updates HEAD automatically. Original commits become unreachable but remain in DB.

3. **PendingCompression hidden state**: The pending object stores `_range_commits`, `_pinned_commits`, `_groups` etc. as private attributes for deferred commit. This avoids re-resolving the range on approval.

4. **Root commit handling**: When compression range starts at the root commit (no pre-range parent), delete the branch ref so `get_head()` returns None. First `create_commit()` then creates a fresh root.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Runtime import of PendingCompression**
- **Found during:** Task 2 (test execution)
- **Issue:** `PendingCompression` was only in `TYPE_CHECKING` block but used at runtime in `isinstance()` check
- **Fix:** Added runtime lazy import `from tract.models.compression import PendingCompression as _PendingCompression`
- **Commit:** 7554846

## Success Criteria Verification

1. compress() with LLM client produces summary commits and CompressResult -- VERIFIED
2. PINNED commits survive verbatim in correct positions -- VERIFIED (test_compress_preserves_pinned, test_pinned_interleaving_order)
3. SKIP commits are ignored during compression -- VERIFIED (test_compress_ignores_skip)
4. compress(auto_commit=False) returns PendingCompression; approve() creates commits -- VERIFIED
5. compress(content="...") works without LLM (manual mode) -- VERIFIED (test_compress_manual_no_llm_required)
6. CompressionRecord provenance is created and queryable -- VERIFIED (4 provenance tests)
7. Original commits remain in DB (non-destructive) -- VERIFIED (test_original_commits_unreachable)
8. Compile cache cleared after compression -- VERIFIED (test_compress_clears_cache)
9. 25 new tests; zero regressions on existing tests -- VERIFIED (535 total)

## Next Phase Readiness

Plan 04-03 (GC & CLI) can proceed. The compression engine is complete with all 3 autonomy modes working. The `CompressionRepository` provides the provenance data needed for GC decisions.
