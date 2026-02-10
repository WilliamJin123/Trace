---
phase: 01-foundations
plan: 01
subsystem: data-model-and-storage
tags: [pydantic, sqlalchemy, orm, repository-pattern, content-types, discriminated-union]
requires: []
provides:
  - 7 built-in content types with discriminated union validation
  - validate_content with per-repo custom_registry support
  - SQLAlchemy ORM schema (5 tables)
  - Repository pattern (4 ABCs + 4 SQLite implementations)
  - Engine/session factory with SQLite pragmas
  - Exception hierarchy, protocols, config models
affects:
  - 01-02 (commit engine imports models, storage, protocols)
  - 01-03 (Repo class wraps repositories and engine)
  - All subsequent phases (everything builds on this layer)
tech-stack:
  added: [sqlalchemy-2.0, pydantic-2.12, tiktoken-0.12, hatchling]
  patterns: [repository-pattern, discriminated-union, type-decorator-bridge, content-addressable-storage]
key-files:
  created:
    - pyproject.toml
    - src/trace_context/__init__.py
    - src/trace_context/_version.py
    - src/trace_context/exceptions.py
    - src/trace_context/protocols.py
    - src/trace_context/models/__init__.py
    - src/trace_context/models/content.py
    - src/trace_context/models/commit.py
    - src/trace_context/models/annotations.py
    - src/trace_context/models/config.py
    - src/trace_context/storage/__init__.py
    - src/trace_context/storage/schema.py
    - src/trace_context/storage/types.py
    - src/trace_context/storage/engine.py
    - src/trace_context/storage/repositories.py
    - src/trace_context/storage/sqlite.py
    - tests/__init__.py
    - tests/conftest.py
    - tests/strategies.py
    - tests/test_models/__init__.py
    - tests/test_models/test_content.py
    - tests/test_storage/__init__.py
    - tests/test_storage/test_schema.py
    - tests/test_storage/test_repositories.py
  modified: []
key-decisions:
  - Import package renamed from `trace` to `trace_context` to avoid stdlib shadow
  - CommitOperation and Priority enums shared between domain models and ORM (not redefined)
  - content_type stored as String in DB (not Enum) to support custom types without migration
  - metadata_json as plain JSON column (no MutableDict, metadata is immutable after commit)
duration: 8m
completed: 2026-02-10
---

# Phase 1 Plan 01: Data Foundation Summary

SQLAlchemy ORM schema with 5 tables, Pydantic discriminated union for 7 content types, repository pattern with SQLite implementations, and full test coverage (66 tests).

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~8 minutes |
| Started | 2026-02-10T23:21:20Z |
| Completed | 2026-02-10T23:29:01Z |
| Tasks | 2/2 |
| Tests | 66 passing |
| Files created | 24 |

## Accomplishments

### Task 1: Project scaffolding, domain models, and protocols
- Created pyproject.toml with hatchling build system and all Phase 1 dependencies
- Defined 7 content type models (InstructionContent, DialogueContent, ToolIOContent, ReasoningContent, ArtifactContent, OutputContent, FreeformContent) with Pydantic discriminated union
- Implemented `validate_content()` with optional `custom_registry` dict for per-repo custom types
- Defined CommitInfo and CommitOperation (APPEND, EDIT) for SDK-facing commit data
- Defined PriorityAnnotation and Priority (SKIP, NORMAL, PINNED) for annotation system
- Defined RepoConfig and TokenBudgetConfig for per-repo configuration
- Defined TokenCounter, ContextCompiler, and TokenUsageExtractor protocols
- Created ContentTypeHints dataclass with BUILTIN_TYPE_HINTS registry for all 7 types
- Created exception hierarchy: TraceError base + 6 specific exceptions
- Created Hypothesis strategies for property-based testing of all content types
- Wrote 35 content model tests (unit + property-based round-trip)

### Task 2: SQLAlchemy ORM schema, repositories, and storage tests
- Implemented PydanticJSON TypeDecorator for Pydantic-to-JSON column bridge
- Created ORM schema with 5 tables: blobs, commits, refs, annotations, _trace_meta
- Created engine factory with SQLite pragmas (WAL, busy_timeout, synchronous, FK enforcement)
- Created init_db function that creates tables and sets schema_version=1
- Defined 4 abstract repository interfaces (CommitRepository, BlobRepository, RefRepository, AnnotationRepository)
- Implemented 4 SQLite repository classes using SQLAlchemy 2.0-style queries
- SqliteBlobRepository implements content-addressable deduplication via save_if_absent
- SqliteAnnotationRepository implements batch_get_latest using single query with subquery (avoids N+1)
- Created test conftest with engine, session, and repository fixtures
- Wrote 31 storage tests (schema creation, CRUD operations, FK constraints, deduplication, indexes)

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Project scaffolding, domain models, and protocols | 2cb18e4 | pyproject.toml, models/content.py, protocols.py, exceptions.py |
| 2 | SQLAlchemy ORM schema, repositories, and storage tests | 49fb80c | storage/schema.py, storage/sqlite.py, storage/repositories.py |

## Decisions Made

1. **Import package renamed to `trace_context`**: The Python stdlib has a `trace` module that shadows our package on Python 3.14. Renamed import from `trace` to `trace_context` while keeping PyPI distribution name as `trace-context`. This is a blocking fix (Rule 3) -- without it, no imports work.

2. **Shared enums between domain and ORM**: CommitOperation and Priority enums are defined once in models/ and imported by storage/schema.py. Not redefined in the ORM layer.

3. **String content_type in DB**: content_type is stored as String(50) in the commits table, not as a DB Enum. This allows custom types to be stored without schema migration.

4. **Immutable metadata**: metadata_json uses plain JSON column without MutableDict. Metadata is set at commit time and not changed afterwards, preserving immutability.

5. **Clean layer separation**: No SQLAlchemy imports in models/ or protocols.py. Storage layer is the only module that touches the ORM.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Import package renamed from `trace` to `trace_context`**
- **Found during:** Task 1 (test execution)
- **Issue:** Python stdlib `trace` module (C:\...\Lib\trace.py) shadows our package. On Python 3.14, stdlib paths come before site-packages in sys.path, making `from trace.models import ...` impossible.
- **Fix:** Renamed package directory from `src/trace/` to `src/trace_context/`. Updated all imports across source and test files. Updated hatchling package config.
- **Files modified:** All source and test files (import paths), pyproject.toml (package discovery)
- **Impact:** All subsequent plans must use `from trace_context.` instead of `from trace.`. MEMORY.md should be updated with this decision.

## Issues Encountered

- **stdlib shadowing**: The plan stated "the stdlib trace module is rarely used and this library runs in its own venv" but this does not prevent shadowing on Python 3.14 where stdlib paths take precedence. Fixed by renaming.

## Next Phase Readiness

Plan 01-02 can proceed immediately. All models, storage, and protocols are in place. The commit engine (01-02) will import from:
- `trace_context.models.content` for content types and validation
- `trace_context.models.commit` for CommitOperation
- `trace_context.storage` for repositories and engine
- `trace_context.protocols` for TokenCounter
- `trace_context.exceptions` for error types

**Note for subsequent plans**: All imports must use `trace_context` (not `trace`) as the package name.
