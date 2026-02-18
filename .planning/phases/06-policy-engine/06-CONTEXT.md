# Phase 6: Policy Engine - Context

**Gathered:** 2026-02-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Extensible, protocol-based policy system that automatically triggers context operations (compress, pin, branch, rebase) based on configurable rules and thresholds. Users can define custom policies via a Policy protocol. Built-in implementations cover the four core auto-operations. Every automatic action supports the full autonomy spectrum (manual/collaborative/autonomous) with human override at any point.

</domain>

<decisions>
## Implementation Decisions

### Architecture: Level 3 — Protocol-based extensible policies
- Policy protocol (ABC) that users implement for custom policies
- 4 built-in implementations: CompressPolicy, PinPolicy, BranchPolicy, RebasePolicy
- Generic PolicyEvaluator that iterates registered policies — doesn't know/care about specific policy types
- Module: `src/tract/policy/` with `PolicyEvaluator` class
- Sidecar architecture: policy evaluator sits beside Tract facade, calls existing operations (compress, annotate, branch, rebase) via the same public API. No changes to existing operations.

### Policy registration: Hybrid (config + runtime)
- Declarative policy definitions stored in config (persisted to DB as JSON)
- Runtime overrides and custom callables registered separately via `tract.register_policy()`
- Declarative rules survive restarts; runtime registrations don't

### Default policies
- Only auto-compress is ON by default for new tracts
- Auto-pin, auto-branch, auto-rebase are opt-in (user explicitly enables)
- Sensible defaults for each policy when enabled (see below)

### Auto-compress defaults (ON by default)
- Trigger threshold: 90% of token budget
- Target: compress ALL eligible (non-pinned) commits — maximize headroom, similar to Claude Code / agentic systems
- Autonomy mode: collaborative (propose, user approves before commit)
- Preserves pinned content verbatim (existing compression behavior)

### Auto-pin defaults (opt-in)
- Auto-pin InstructionContent and SessionContent commits out of the box
- User can add custom pattern rules (content type + role + text regex/substring matching)
- Rules are additive — user rules layer on top of defaults, can also override
- Manual overrides always win: if user explicitly sets NORMAL or SKIP, auto-pin won't re-pin
- Retroactive scan: when enabled or rules change, scans existing commits and pins matches
- Evaluates at commit time (evaluate_on="commit") — pins immediately, no gap before compression
- A pin is a pin — no confidence levels. Binary pinned/not-pinned.

### Auto-branch defaults (opt-in)
- Claude's discretion on tangent detection heuristic (researcher/planner decide approach)

### Auto-rebase defaults (opt-in)
- Staleness = low commit count + configurable time threshold
- Action: archive to `archive/` prefix (non-destructive rename, not deletion)

### Trigger evaluation model
- Default evaluation point: on compile() — "just in time" before context consumption
- Policies can declare evaluate_on="commit" for post-commit evaluation (auto-pin uses this)
- Priority ordering: policies have explicit priority field, lower runs first (auto-pin before auto-compress)
- Error handling: retry with backoff on transient failures, then raise PolicyExecutionError if exhausted
- Cooldown: Claude's discretion on whether proposal tracking handles this naturally

### Human override flow
- Collaborative mode: propose → approve/reject/edit (same pattern as existing PendingCompression)
- Autonomous mode rollback: via existing reset/checkout — no new undo API
- Per-policy autonomy: global default mode + per-policy override (e.g., engine=collaborative, auto-pin=autonomous)
- Emergency kill switch: tract.pause_all_policies() / tract.resume_all_policies()
- Conflict resolution: priority ordering resolves — auto-pin runs before auto-compress, so pins are set before compression evaluates

### Auditability
- Policy actions produce commits with metadata marking them as policy-generated
- Separate queryable audit log for evaluation history (including evaluations that didn't fire)
- Both commit metadata AND audit log table — full visibility

### Storage
- Policy definitions: JSON column (extensible, arbitrary config per policy type — same pattern as generation_config)
- Pending proposals: new `policy_proposals` table (transactional lifecycle, queryable by status)
- Audit log: new `policy_log` table (append-only, time-range queries)
- Schema version: bump to v5 with auto-migration (same pattern as v1→v2→v3→v4)
- All policy state persisted to SQLite (survives restarts)

### Claude's Discretion
- Policy definition format (Pydantic models matching existing codebase patterns)
- Notification mechanism for collaborative mode proposals (return value vs callback)
- Auto-branch tangent detection heuristic
- Cooldown implementation details
- Whether CLI commands are added for policy management (SDK-only is fine for v2)

</decisions>

<specifics>
## Specific Ideas

- "Compress as much as possible when triggered — similar to Claude Code or agentic systems, maximize headroom"
- Auto-rebase should archive branches, not delete them — non-destructive by default
- The policy system should be a library-grade extensible protocol, not hardcoded policy types — agent framework developers need to define domain-specific policies
- Core Value 2 integration: the policy evaluator is the mechanism that makes the autonomy spectrum configurable and automatic

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-policy-engine*
*Context gathered: 2026-02-17*
