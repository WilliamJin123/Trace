# Phase 5: Multi-Agent & Release - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Coordinate multiple agent traces with spawn/collapse semantics, session persistence, crash recovery, cross-repo queries, and package the library for pip release. This phase delivers the multi-agent layer on top of the existing single-agent infrastructure (Phases 1-4) and prepares the library for public consumption.

</domain>

<decisions>
## Implementation Decisions

### Spawn/Collapse Model
- **Cross-tract architecture**: Each subagent gets its own full Tract with independent history, linked to the parent via a spawn pointer table. NOT branch-based within a single tract.
- **Single shared DB**: All tracts in a session share one SQLite file, isolated by tract_id. Cross-repo queries are JOINs, not ATTACH. (Claude's discretion on final call after researcher investigates SQLite concurrency.)
- **Three inheritance modes at spawn time** (caller chooses per spawn):
  - Full clone: subagent gets entire parent commit history
  - HEAD snapshot: subagent starts with compiled context at parent's current HEAD
  - Selective: caller specifies commit range, content type filter, or custom compiled context
- **Spawn creates a commit in the parent tract**: An APPEND commit documenting "Spawned subagent for: [purpose]". Timeline stays purely commit-based.
- **Required purpose metadata on every spawn**: Every spawn must include a task description/delegation intent. Makes the agent graph self-documenting.
- **Unlimited recursive depth**: Any tract can spawn children, forming a tree of arbitrary depth. No artificial limits — application layer can cap if needed.
- **Minimal spawn pointer table** (derive status from commits, no mutable status column):
  - parent_tract_id, parent_commit_hash, child_tract_id, purpose, created_at
  - Status inferred from commit history (consistent with commits-as-truth pattern)
- **Collapse is additive, not destructive**: Collapse compresses the subagent's history into a summary commit in the parent tract. The spawn pointer and child tract remain intact. Nothing is removed.
- **Collapse reuses compression engine** with a different default prompt: Same Phase 4 compression pipeline, but with a collapse-specific prompt focused on "what did this subagent accomplish" rather than generic summarization. Same 3 autonomy modes apply.
- **Multiple collapses allowed**: Subagent can report back multiple times with interim progress. Each collapse summarizes new work since the last one.

### Agent Identity & Sessions
- **Optional display name, tract_id always auto-generated**: Tracts always get a unique tract_id. Optional human-readable name/role can be assigned at spawn time.
- **Session = thin Python wrapper over the shared DB file**: Not a schema concept — no new tables, no session IDs. `Session.open("file.db")` is the multi-agent entry point. `Tract.open()` still works for single-agent use (backward compatible).
- **Session.resume() convenience helper**: Finds the most recent tract without a session-boundary commit and reopens it. Caller can always bypass and manually query + open.
- **Crash recovery = resume from last commit**: Commits are the durability boundary, just like git. Uncommitted work is lost on crash.
- **Dedicated session commit type**: Session boundaries (session knowledge: decisions, progress, failed approaches) use a first-class commit type, not just an APPEND with a convention. Makes session transitions queryable.
- **Unified spawn mechanism for handoff**: Cross-session handoff uses the same spawn + inheritance mechanism as subagent delegation. The session-boundary commit differentiates lifecycle (marks "this tract is done"). No separate handoff API.

### Cross-Repo Query Scope
- **Three query patterns supported**:
  - Point-in-time state: "What did agent-2 know when agent-1 made this commit?"
  - Content search: "Which agent committed something about topic X?"
  - Unified timeline: "Everything that happened chronologically across all agents"
- **Both raw commits and compiled context available**: Queries return CommitInfo objects by default. Can also compile any tract at any historical point for full context view.
- **Dual correlation strategy**: Causal ordering via spawn graph for parent-child relationships. Timestamp-based for unrelated agents.
- **Query API split**: Session gets full cross-tract queries (timeline, search, correlation). Tract gets immediate relationship helpers (parent(), children(), spawn()).
- **Search implementation**: Claude's discretion — researcher investigates whether SQLite FTS5 is worth the complexity for v1 or simple LIKE/regex suffices.

### Package & API Surface
- **Broad public API**: Export Tract, Session, core models (CommitInfo, CompiledContext, etc.), AND key operations (merge, rebase, compress, etc.) as standalone functions for advanced users.
- **Optional deps: core + [cli] only**: httpx/tenacity are core deps (LLM operations are central). Only CLI (Click+Rich) is optional via `pip install tract[cli]`.
- **Documentation: README + guides + API reference**: Solid README with quickstart, how-to guides (single agent, multi-agent, compression, custom resolvers), plus auto-generated API docs.
- **PyPI package name: `tract`**: Keep it simple.

### Autonomy Spectrum
- **Full 3-mode spectrum on ALL Phase 5 operations**: Spawn, collapse, session boundaries all support manual/collaborative/autonomous modes — consistent with the project's core value.
- **Spawn autonomy**: Manual (user explicitly spawns), Collaborative (library suggests delegation, user approves), Autonomous (library auto-spawns when it detects delegatable work).
- **Collapse autonomy**: Full spectrum on both WHEN to collapse and WHAT goes in the summary. Autonomous mode can detect "subagent done" and auto-summarize.
- **Session boundary autonomy**: Manual (user writes summary), Collaborative (LLM drafts, user reviews), Autonomous (LLM auto-commits boundary when session ends).
- **Session-level default + per-operation override**: `Session.open(..., autonomy="collaborative")` sets the default. Any operation can override per-call. Default is collaborative (matches PROJECT.md: "the LLM is a tool in the pipeline, not a gatekeeper").

### Claude's Discretion
- Single shared DB vs separate DB per tract (after researcher investigates SQLite concurrency)
- Search implementation for cross-repo queries (FTS5 vs LIKE/regex)
- Exact spawn pointer table schema details
- Session commit type implementation (new content type vs new operation)
- Collapse prompt design
- Session.resume() detection heuristics

</decisions>

<specifics>
## Specific Ideas

- Collapse mental model comes from Claude Code: parent calls subagent, gets summary after subagent formulates results, but subagent trace persists from that point
- Cross-session handoff is unified with spawn — same mechanism, differentiated by session-boundary commit lifecycle
- Session-level autonomy default follows the same override pattern as TractConfig and generation_config

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-multi-agent-release*
*Context gathered: 2026-02-16*
