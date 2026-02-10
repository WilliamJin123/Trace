---
phase: 01-foundations
plan: 03
subsystem: public-api
tags: [repo, sdk, facade, integration-tests, public-api, context-manager, compile-cache]
requires:
  - 01-01 (domain models, storage layer, repository interfaces)
  - 01-02 (commit engine, context compiler, token counting, hashing)
provides:
  - Repo class -- single public entry point for Trace SDK
  - Repo.open() for in-memory and file-backed SQLite repositories
  - Repo.from_components() for dependency injection / testing
  - Complete public API exported from trace_context package root
  - Compile cache with invalidation on commit/annotate
  - Batch context manager for atomic multi-commit transactions
  - Per-repo custom content type registry
  - 47 integration tests validating all 5 Phase 1 success criteria
affects:
  - 02-XX (linear history will extend Repo with undo/redo/squash)
  - 03-XX (branching will extend Repo with branch/merge operations)
  - 04-XX (compression will integrate with compile pipeline via Repo)
  - 05-XX (packaging builds on this complete public API surface)
tech-stack:
  added: []
  patterns:
    - Facade pattern (Repo wraps CommitEngine + DefaultContextCompiler)
    - Factory method (Repo.open classmethod)
    - DI constructor (Repo.from_components classmethod)
    - Context manager protocol (__enter__/__exit__)
    - Compile cache with invalidation
    - Batch commit via session.commit monkey-patching
key-files:
  created:
    - src/trace_context/repo.py
    - tests/test_repo.py
  modified:
    - src/trace_context/__init__.py
decisions:
  - "Compile cache keyed by head_hash, cleared on commit/annotate (simple and correct)"
  - "Batch implemented by temporarily replacing session.commit with noop, committing on exit"
  - "__repr__ returns safe string after close() (no DB access)"
  - "Repo.open() does not create a branch ref upfront; first commit sets HEAD via CommitEngine"
metrics:
  duration: 4m
  completed: 2026-02-10
  tests-added: 47
  total-tests: 200
---

# Phase 01 Plan 03: Repo Class and Public API Summary

**Repo facade with full public API, compile cache, batch support, and 47 integration tests covering all 5 Phase 1 success criteria**

## What Was Built

### Task 1: Repo Class (Public SDK Entry Point)

**File: `src/trace_context/repo.py`** (300+ lines)

The `Repo` class is a thin facade that ties together the storage, commit engine, and context compiler layers from Plans 01 and 02 into a clean user-facing API.

**Construction:**
- `Repo.open(path, *, repo_id, config, tokenizer, compiler)` -- factory method that creates engine, session, repositories, and wires everything together
- `Repo.from_components(...)` -- DI constructor for testing with pre-built components
- Context manager support (`with Repo.open() as repo:`)

**Public API:**
- `repo.commit(content, *, operation, message, reply_to, metadata)` -- accepts Pydantic models or dicts
- `repo.compile(*, as_of, up_to, include_edit_annotations)` -- with compile cache
- `repo.get_commit(hash)` -- lookup by hash
- `repo.annotate(target_hash, priority, *, reason)` -- priority annotations
- `repo.get_annotations(target_hash)` -- annotation history
- `repo.log(limit)` -- commit history walk
- `repo.batch()` -- atomic multi-commit context manager
- `repo.register_content_type(name, model)` -- per-repo custom types
- Properties: `repo_id`, `head`, `config`

**File: `src/trace_context/__init__.py`** (92 lines)

Exports 30+ symbols from the package root including Repo, all content types, commit/annotation types, config, protocols, and exceptions.

### Task 2: Integration Tests (All Phase 1 Success Criteria)

**File: `tests/test_repo.py`** (470+ lines, 47 tests)

Tests organized by success criterion:

| Category | Tests | Coverage |
|----------|-------|----------|
| SC1: Initialization & persistence | 6 | open, file-backed, reopen, context manager, DI |
| SC2: Commits & annotations | 7 | append, edit, get, chain, skip/restore, batch |
| SC3: Content types | 11 | All 7 types + dict + mixed + custom |
| SC4: Compilation | 9 | Default, edit, skip, time-travel, aggregation, custom compiler, cache |
| SC5: Token counting | 5 | Counts, custom tokenizer, budget warn/reject |
| History | 3 | Log ordering, limit, empty |
| Edge cases | 6 | Error paths, repr, config access |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed __repr__ crash after close()**

- **Found during:** Task 2 (test_open_as_context_manager)
- **Issue:** `__repr__` called `self.head` which hit the database after `close()` disposed the engine
- **Fix:** Added `self._closed` check in `__repr__` to return safe string without DB access
- **Files modified:** `src/trace_context/repo.py`
- **Commit:** Included in Task 2 commit

## Verification Results

### Full Test Suite
```
200 passed in 1.92s
```

### End-to-End Success Criteria
```
SC1 PASS: Repo opened
SC2 PASS: 3 commits created, retrievable by hash
SC3 PASS: Compiled 3 messages with correct roles
SC4 PASS: Edit resolution works in compilation
SC5 PASS: Token counts present (commit: 4, compiled: 22)
ALL 5 SUCCESS CRITERIA VERIFIED
```

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Compile cache keyed by head_hash | Simple, correct: head changes on every commit |
| Cache cleared on annotate too | Priority changes affect compilation output |
| Batch via session.commit replacement | Avoids nested transaction complexity; simple for single-user SDK |
| No branch ref created upfront | HEAD set naturally by first commit via CommitEngine |
| __repr__ safe after close | Prevents confusing errors when inspecting closed repo |

## Phase 1 Completion Status

Phase 1 (Foundations) is now **complete**. All 3 plans executed:

| Plan | What | Tests |
|------|------|-------|
| 01-01 | Domain models + storage layer | 87 |
| 01-02 | Engine layer (hashing, tokens, commit, compiler) | 66 |
| 01-03 | Repo class + public API + integration tests | 47 |
| **Total** | | **200** |

### Architecture Summary (Phase 1)

```
User API:           Repo  (01-03)
                     |
Engine Layer:   CommitEngine + DefaultContextCompiler  (01-02)
                     |
Storage Layer:  Sqlite*Repository (4x)  (01-01)
                     |
ORM/Schema:     SQLAlchemy Base + 5 tables  (01-01)
                     |
Domain Models:  Pydantic content/commit/annotation/config  (01-01)
```

## Next Phase Readiness

Phase 2 (Linear History) can begin. The Repo class provides the extension point for:
- `repo.undo()` / `repo.redo()` -- will extend commit chain management
- `repo.squash()` -- will add new engine method
- `repo.tag()` -- will extend RefRepository
- `repo.diff()` -- will add blob comparison

No blockers. All infrastructure is in place.
