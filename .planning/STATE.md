# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-10)

**Core value:** Agents produce better outputs when their context is clean, coherent, and relevant. Trace makes context a managed, version-controlled resource.
**Current focus:** Phase 1.1 - Incremental Compile Cache & Token Tracking (IN PROGRESS)

## Current Position

Phase: 1.1 of 5 (Compile Cache & Token Tracking)
Plan: 1 of 2 in current phase
Status: In progress
Last activity: 2026-02-11 - Completed 01.1-01-PLAN.md

Progress: [####..........] 25% (4/16 plans)

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: 8m
- Total execution time: 0.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3/3 | 27m | 9m |
| 1.1 | 1/2 | 3m | 3m |

**Recent Trend:**
- Last 5 plans: 01-01 (8m), 01-02 (15m), 01-03 (4m), 01.1-01 (3m)
- Trend: incremental plans on solid foundation execute very fast

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 5-phase structure derived from dependency analysis (Foundations -> Linear History -> Branching -> Compression -> Multi-Agent)
- [Roadmap]: LLM client (INTF-03/04) placed in Phase 3 with branching since semantic merge is the first consumer
- [Roadmap]: INTF-05 (packaging) placed in Phase 5 as final delivery step after all features complete
- [01-01]: Import package renamed from `trace` to `tract` (stdlib shadow fix on Python 3.14). All imports must use `tract`.
- [01-01]: CommitOperation and Priority enums shared between domain models and ORM (not redefined)
- [01-01]: content_type stored as String in DB (not Enum) to support custom types without migration
- [01-01]: Clean layer separation enforced: no SQLAlchemy imports in models/ or protocols.py
- [01-02]: Timezone normalization: _normalize_dt() strips tzinfo for datetime comparison (SQLite stores naive datetimes)
- [01-02]: Edit resolution: latest edit wins when multiple edits target same commit (by created_at)
- [01-02]: Token count distinction: per-commit = raw content, CompiledContext = formatted with message overhead
- [01-02]: Same-role aggregation: consecutive same-role messages concatenated with double newline
- [01-03]: Compile cache keyed by head_hash, cleared on commit/annotate
- [01-03]: Batch implemented by temporarily replacing session.commit with noop, committing on exit
- [01-03]: Repo.open() does not create branch ref upfront; first commit sets HEAD via CommitEngine
- [01.1-01]: Compile cache replaced with CompileSnapshot-based incremental cache (APPEND = O(1) extend, EDIT/annotate/batch = full invalidation)
- [01.1-01]: build_message_for_commit() extracted as public method on DefaultContextCompiler for reuse by Repo incremental path
- [01.1-01]: CompileSnapshot stores both raw and aggregated messages for correct tail aggregation
- [01.1-01]: Time-travel and custom compilers bypass incremental cache entirely

### Pending Todos

None.

### Roadmap Evolution

- Phase 1.1 inserted after Phase 1: Incremental Compile Cache & Token Tracking (INSERTED) — addresses two design issues: (1) full chain walk on every compile adds latency, incremental cache makes APPEND O(1); (2) tiktoken used as sole token source, but API-reported usage should be source of truth post-call

### Blockers/Concerns

- ~~Phase 1: Edit commit semantics (override vs in-place)~~ RESOLVED: Full commit replacement (new commit supersedes original via reply_to). No in-place mutation.
- ~~Phase 1: stdlib `trace` module shadowing~~ RESOLVED: Package renamed to `tract`.
- WATCH: External linter keeps renaming `tract` back to `trace` in working tree. The git commits have correct `tract` imports. If this affects future plan execution, may need to configure ruff to ignore this rename.
- Phase 3: Semantic merge quality is unproven for natural language context -- research flag for plan-phase
- Phase 4: Compression is inherently lossy (3-55% degradation in research) -- need validation strategy
- Phase 5: SQLite concurrent write behavior under multi-agent load is untested -- research flag for plan-phase

## Phase 1 Final Stats

| Plan | Name | Tests | Duration |
|------|------|-------|----------|
| 01-01 | Domain Models + Storage | 87 | 8m |
| 01-02 | Engine Layer | 66 | 15m |
| 01-03 | Repo Class + Public API | 47 | 4m |
| **Total** | | **200** | **27m** |

All 5 Phase 1 success criteria verified end-to-end.

## Session Continuity

Last session: 2026-02-11T03:30:02Z
Stopped at: Completed 01.1-01-PLAN.md (Incremental compile cache with CompileSnapshot). Phase 1.1 plan 1/2 complete.
Resume file: None
