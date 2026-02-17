# Phase 6: Policy Engine - Research

**Researched:** 2026-02-17
**Domain:** Extensible policy evaluation system for automatic context operations
**Confidence:** HIGH

## Summary

The policy engine is an internal extension to the existing Trace (tract) codebase. It introduces a protocol-based policy system that automatically triggers context operations (compress, annotate/pin, branch, rebase) based on configurable rules and thresholds. Research focused entirely on understanding the existing codebase patterns (since this is an internal library, not an external integration) and identifying the correct architectural patterns to follow for consistency.

The codebase already has every building block needed. The existing `compress()` method already supports the three autonomy modes (autonomous/collaborative/manual) via `auto_commit` and `PendingCompression`. The annotation system already supports `PINNED`/`NORMAL`/`SKIP`. Branching, merging, and rebase operations are all callable through the `Tract` public API. The schema migration system (`v1->v2->v3->v4`) has a clear pattern for adding new tables. The policy engine is therefore a composition layer -- it does not need to modify any existing operations, only orchestrate them.

The key architectural insight is the "sidecar" pattern: `PolicyEvaluator` sits beside `Tract`, receives a reference to it, and calls its public API methods (`compress()`, `annotate()`, `branch()`, `rebase()`) as an external consumer would. This means zero changes to existing code and maximum testability.

**Primary recommendation:** Follow the existing codebase conventions exactly -- ABC for storage repositories, `@runtime_checkable Protocol` for user-facing extensibility, Pydantic `BaseModel` for config/data models, `@dataclass(frozen=True)` for result types, and the established `init_db()` migration chain for new tables.

## Standard Stack

No new external dependencies required. The policy engine uses only what's already in the project.

### Core (existing dependencies, no additions)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlalchemy | >=2.0.46,<2.2 | ORM for policy_proposals, policy_log tables | Already used for all storage |
| pydantic | >=2.10,<3.0 | Policy config models, validation | Already used for all models |
| tiktoken | >=0.12.0 | Token counting for budget threshold evaluation | Already used for compilation |

### Supporting (no new additions)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| abc (stdlib) | N/A | ABC base for PolicyRepository | Same pattern as `storage/repositories.py` |
| typing.Protocol | N/A | Policy protocol for user extensibility | Same pattern as `protocols.py` |
| enum (stdlib) | N/A | Policy status, trigger type enums | Same pattern as CommitOperation, Priority |
| dataclasses (stdlib) | N/A | Result types (PolicyAction, EvaluationResult) | Same pattern as CompressResult |
| logging (stdlib) | N/A | Policy evaluation logging | Same pattern as compression.py |
| uuid (stdlib) | N/A | Policy IDs, proposal IDs | Same pattern as compression_id |
| json (stdlib) | N/A | Policy config serialization to JSON columns | Same pattern as generation_config_json |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ABC for Policy base | Protocol only | ABC chosen per CONTEXT.md decision; also aligns with how repositories.py does it -- ABC for things with state/implementation, Protocol for pure structural typing |
| Separate policy_log table | Reuse commit metadata_json | Separate table allows time-range queries, status tracking, and doesn't pollute commit data |
| JSON policy config in DB | Separate config table with columns | JSON matches generation_config_json pattern -- extensible, arbitrary per-policy-type |

**Installation:**
```bash
# No new dependencies -- everything is already in pyproject.toml
```

## Architecture Patterns

### Recommended Project Structure
```
src/tract/
  policy/
    __init__.py           # Public exports
    protocols.py          # Policy ABC + PolicyAction dataclass
    evaluator.py          # PolicyEvaluator class
    builtin/
      __init__.py         # Re-export built-in policies
      compress.py         # CompressPolicy
      pin.py              # PinPolicy
      branch.py           # BranchPolicy
      rebase.py           # RebasePolicy
  models/
    policy.py             # Pydantic models: PolicyConfig, PolicyProposal, PolicyLogEntry, EvaluationResult
  storage/
    schema.py             # ADD: PolicyProposalRow, PolicyLogRow, PolicyConfigRow (or inline JSON)
    repositories.py       # ADD: PolicyRepository ABC
    sqlite.py             # ADD: SqlitePolicyRepository
  exceptions.py           # ADD: PolicyExecutionError, PolicyConfigError
```

### Pattern 1: Policy Protocol (ABC)
**What:** Abstract base class that all policies must implement
**When to use:** All policy implementations, both built-in and user-defined
**Why ABC over Protocol:** CONTEXT.md locks this as "Policy protocol (ABC) that users implement for custom policies". Also consistent with `storage/repositories.py` which uses ABC for things users subclass with state.

```python
# Source: Follows Pattern from src/tract/storage/repositories.py (ABC for things with implementations)
# and src/tract/protocols.py (Protocol for structural typing)

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from datetime import datetime

if TYPE_CHECKING:
    from tract.tract import Tract


class PolicyAction:
    """Describes what a policy wants to do."""
    # See Pattern 3 below for full structure


class Policy(ABC):
    """Abstract base class for all policies.

    Users implement this to create custom policies.
    Built-in CompressPolicy, PinPolicy, etc. also implement this.
    """

    @abstractmethod
    def evaluate(self, tract: Tract) -> PolicyAction | None:
        """Evaluate whether this policy should fire.

        Args:
            tract: The Tract instance to evaluate against.

        Returns:
            PolicyAction if the policy wants to fire, None if conditions not met.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this policy (e.g., 'auto-compress')."""
        ...

    @property
    def priority(self) -> int:
        """Execution priority. Lower runs first. Default 100."""
        return 100

    @property
    def trigger(self) -> str:
        """When this policy evaluates: 'compile' or 'commit'. Default 'compile'."""
        return "compile"
```

### Pattern 2: Sidecar PolicyEvaluator
**What:** Evaluator that sits beside Tract, iterates registered policies, executes actions
**When to use:** Called by Tract at evaluation points (compile, commit)
**Key insight:** The evaluator does NOT know about specific policy types. It receives a `list[Policy]`, calls `evaluate()` on each, and dispatches actions.

```python
# Source: Follows sidecar pattern from CONTEXT.md decisions

class PolicyEvaluator:
    """Evaluates registered policies and executes their actions.

    Sidecar to Tract: receives a Tract reference, calls its public API.
    Does NOT know about specific policy types (CompressPolicy, etc.).
    """

    def __init__(self, tract: Tract, policies: list[Policy] | None = None):
        self._tract = tract
        self._policies: list[Policy] = sorted(
            policies or [], key=lambda p: p.priority
        )
        self._paused = False

    def evaluate(self, trigger: str = "compile") -> list[EvaluationResult]:
        """Run all policies matching the trigger.

        Args:
            trigger: 'compile' or 'commit'

        Returns:
            List of EvaluationResult describing what happened.
        """
        if self._paused:
            return []

        results = []
        for policy in self._policies:
            if policy.trigger != trigger:
                continue
            action = policy.evaluate(self._tract)
            if action is not None:
                result = self._execute_action(policy, action)
                results.append(result)
        return results
```

### Pattern 3: PolicyAction as Dataclass (Follows CompressResult Pattern)
**What:** Frozen dataclass describing what a policy wants to do
**Why:** Matches the existing pattern -- `CompressResult`, `GCResult`, `ReorderWarning` are all frozen dataclasses. Policy actions should be too.

```python
# Source: Follows pattern from src/tract/models/compression.py

@dataclass(frozen=True)
class PolicyAction:
    """Describes what a policy wants to execute.

    The evaluator interprets this generically -- it calls the appropriate
    Tract method based on action_type.
    """

    action_type: str  # "compress", "annotate", "branch", "rebase", "archive"
    params: dict = field(default_factory=dict)  # Arguments to pass to the Tract method
    reason: str = ""  # Human-readable explanation
    autonomy: str = "collaborative"  # "autonomous", "collaborative", "manual"
```

### Pattern 4: Integration with Tract (Minimal Coupling)
**What:** Tract gets a `_policy_evaluator` attribute set by `configure_policies()`, called at evaluation points
**Key:** compile() and commit() call the evaluator at appropriate points, but the evaluator is optional.

```python
# In tract.py -- minimal additions

class Tract:
    def configure_policies(self, policies: list[Policy] | None = None, **kwargs):
        """Configure the policy evaluator."""
        from tract.policy.evaluator import PolicyEvaluator
        self._policy_evaluator = PolicyEvaluator(self, policies, **kwargs)

    def register_policy(self, policy: Policy) -> None:
        """Register a policy at runtime."""
        if self._policy_evaluator is None:
            self.configure_policies()
        self._policy_evaluator.register(policy)

    def pause_all_policies(self) -> None:
        """Emergency kill switch."""
        if self._policy_evaluator:
            self._policy_evaluator.pause()

    def resume_all_policies(self) -> None:
        """Resume after pause."""
        if self._policy_evaluator:
            self._policy_evaluator.resume()
```

### Pattern 5: Collaborative Mode / Proposal Flow (Follows PendingCompression)
**What:** When autonomy is "collaborative", policy actions create proposals that must be approved
**Key insight:** The existing `PendingCompression` pattern is the exact blueprint. It stores state, has `edit_summary()` and `approve()` methods, and uses a `_commit_fn` closure.

```python
# Source: Follows PendingCompression from src/tract/models/compression.py

@dataclass
class PolicyProposal:
    """A proposed policy action awaiting human review.

    Mutable: users can edit before approving.
    Follows the PendingCompression pattern exactly.
    """

    proposal_id: str
    policy_name: str
    action: PolicyAction
    created_at: datetime
    status: str = "pending"  # "pending", "approved", "rejected", "expired"
    _execute_fn: Callable | None = field(default=None, repr=False)

    def approve(self) -> object:
        """Execute the proposed action."""
        if self._execute_fn is None:
            raise PolicyExecutionError("No execute function set")
        self.status = "approved"
        return self._execute_fn(self)

    def reject(self, reason: str = "") -> None:
        """Reject the proposal."""
        self.status = "rejected"
```

### Pattern 6: Schema Migration v4 -> v5 (Follows Existing Chain)
**What:** Add new tables via the existing init_db() migration chain
**Key:** The pattern in `storage/engine.py` is clear: check version, create tables with `checkfirst=True`, bump version.

```python
# Source: Follows pattern from src/tract/storage/engine.py

# In init_db(), after v3->v4 migration block:
if existing is not None and existing.value == "4":
    # Migrate v4 -> v5: create policy tables
    for table_name in ["policy_proposals", "policy_log"]:
        Base.metadata.tables[table_name].create(engine, checkfirst=True)
    existing.value = "5"
    session.commit()
```

### Pattern 7: Policy Config Storage (Follows generation_config_json Pattern)
**What:** Store policy definitions as JSON in a column, loaded on Tract.open()
**Key:** The `generation_config_json` column on CommitRow is the exact precedent -- JSON column for extensible, per-instance config that varies by type.

Decision point: Where to store policy config? Two options:
1. **_trace_meta table** (key-value): Simple, uses existing table, store as `"policy_config" -> JSON string`
2. **New policy_config column on a new table**: More structured

**Recommendation:** Use `_trace_meta` table for policy configuration. It already exists, supports key-value storage, and policy config is inherently per-database (not per-commit). This avoids creating yet another table for what is essentially a single JSON blob. Store as key=`"policy_config:{tract_id}"`, value=JSON string.

### Anti-Patterns to Avoid
- **Modifying existing operations:** The policy engine must NOT change compress_range(), annotate(), branch(), or rebase(). It calls them through Tract's public API.
- **Tight coupling to specific policy types:** The PolicyEvaluator must iterate `list[Policy]` generically. It should NOT have `if isinstance(policy, CompressPolicy)` branches.
- **Global policy registration:** Policies are per-Tract instance, matching the per-instance custom_type_registry pattern. No module-level global state.
- **Synchronous LLM calls in evaluation:** The `evaluate()` method should be fast (check thresholds, count tokens). LLM calls happen only during `execute()` (e.g., when compression actually runs).
- **Breaking the compile() hot path:** Policy evaluation in compile() must not significantly slow down compilation. Fast threshold check, then defer execution.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token counting for threshold checks | Custom counter | `tract.status().token_count` or `tract.compile().token_count` | Already computed, cached, correct |
| Branch staleness detection | Custom time comparison | `tract.log()` + `created_at` on commits | Commit timestamps are already tracked |
| Pinning commits | Custom annotation writes | `tract.annotate(hash, Priority.PINNED)` | Full annotation lifecycle handled |
| Compressing commits | Custom compression pipeline | `tract.compress(auto_commit=True/False)` | All 3 autonomy modes built-in |
| Branch archiving | Custom branch rename | `tract.branch("archive/{name}")` + branch pointer copy | Branch operations already support this |
| Schema migration | Manual SQL ALTER TABLE | `init_db()` chain in `storage/engine.py` | Idempotent, handles all upgrade paths |
| Proposal lifecycle | Custom state machine | Dataclass with `status` field + `_commit_fn` closure | PendingCompression is the exact pattern |
| Content type detection | Parsing blob JSON | `commit.content_type` on CommitRow | Stored as a column, no parsing needed |
| Priority checks | Direct annotation queries | `annotation_repo.batch_get_latest()` | Batch query already optimized |
| Config persistence | Custom file I/O | `_trace_meta` table (key-value) | Already exists for schema versioning |

**Key insight:** The policy engine is 90% orchestration code calling existing Tract methods. The remaining 10% is new storage (2 tables), new models (Pydantic + dataclass), and the evaluation loop. There is almost nothing to build from scratch.

## Common Pitfalls

### Pitfall 1: Policy Evaluation Recursion
**What goes wrong:** Policy fires compress(), which changes HEAD, which triggers compile(), which triggers policy evaluation again, causing infinite recursion.
**Why it happens:** If compile() triggers policy evaluation and policy execution calls compress() which triggers another compile().
**How to avoid:** Use a `_evaluating` flag on PolicyEvaluator. Set to True during evaluation, skip if already True. Same pattern as `_in_batch` on Tract.
**Warning signs:** Stack overflow, infinite loops in tests.

```python
def evaluate(self, trigger: str = "compile") -> list[EvaluationResult]:
    if self._paused or self._evaluating:
        return []
    self._evaluating = True
    try:
        # ... run policies
    finally:
        self._evaluating = False
```

### Pitfall 2: Compile-Time Evaluation Performance
**What goes wrong:** Policy evaluation during compile() adds latency to every compile() call, even when no policies should fire.
**Why it happens:** If evaluation does expensive work (full chain walks, LLM calls) during the check phase.
**How to avoid:** Policy.evaluate() must be FAST -- it should only check thresholds (token count vs budget, commit count, timestamps). The actual work (LLM summarization, etc.) happens only if the action is approved/executed. Use the compile result that's already being computed.
**Warning signs:** compile() regression in benchmarks, test slowdowns.

### Pitfall 3: TOCTOU Between Evaluation and Execution
**What goes wrong:** Policy evaluates "threshold exceeded" but by the time it executes, HEAD has changed (another policy ran first, or user committed).
**Why it happens:** Time-of-check/time-of-use gap between evaluate() and execute().
**How to avoid:** The existing compress() already has a TOCTOU guard via `expected_head` parameter. Policy actions should capture the current HEAD at evaluation time and pass it to the execution. If HEAD changes, re-evaluate.
**Warning signs:** CompressionError("HEAD changed since compression was planned").

### Pitfall 4: Auto-Pin Retroactive Scan Edge Cases
**What goes wrong:** Retroactive scan tries to pin commits that user explicitly set to NORMAL or SKIP.
**Why it happens:** Auto-pin doesn't check for manual override annotations.
**How to avoid:** Per CONTEXT.md decision: "Manual overrides always win: if user explicitly sets NORMAL or SKIP, auto-pin won't re-pin." Check annotation history, not just latest annotation. If any manual annotation exists (one without a policy source), don't override.
**Warning signs:** Test: user sets SKIP, auto-pin changes it back to PINNED.

### Pitfall 5: Policy Config Serialization Roundtrip
**What goes wrong:** Policy config stored as JSON doesn't roundtrip correctly -- Pydantic enums serialize as values, datetime objects need special handling.
**Why it happens:** JSON column stores primitive types. Complex types need explicit serialization.
**How to avoid:** Use Pydantic's `model_dump(mode="json")` and `model_validate()` for config serialization/deserialization. Same as how generation_config is stored -- it's a dict/JSON column.
**Warning signs:** Config loads with wrong types after restart.

### Pitfall 6: Auto-Branch Tangent Detection is Hard
**What goes wrong:** Tangent detection heuristic produces false positives (branches on legitimate follow-up questions) or false negatives (misses actual tangents).
**Why it happens:** Tangent detection is fundamentally a semantic problem. Simple heuristics (topic change, keyword analysis) are brittle.
**How to avoid:** Start with the simplest possible heuristic. CONTEXT.md gives this as "Claude's discretion." Consider: consecutive commits with very different content types, or user explicitly tagging messages as tangential. Don't try to build a sophisticated NLP pipeline -- keep it rule-based and let users configure sensitivity. Consider making this policy require LLM if configured, or be purely threshold-based (e.g., "if content type switches from dialogue to artifact more than N times").
**Warning signs:** Users disabling auto-branch because it's too aggressive.

### Pitfall 7: Audit Log Growth
**What goes wrong:** policy_log table grows unbounded, slowing queries.
**Why it happens:** Every evaluation (including ones that don't fire) is logged.
**How to avoid:** Only log evaluations that produce a PolicyAction (not "nothing to do" checks). Provide a `gc_policy_log(retention_days=30)` method. Add index on `created_at` for time-range queries.
**Warning signs:** Slow `get_policy_history()` queries in long-running tracts.

## Code Examples

Verified patterns from the existing codebase:

### Example 1: CompressPolicy.evaluate() - Threshold Check
```python
# Pattern: Fast threshold check during evaluation, defer expensive work to execution

class CompressPolicy(Policy):
    """Auto-compress when token budget threshold is exceeded."""

    def __init__(self, threshold: float = 0.9):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "auto-compress"

    @property
    def priority(self) -> int:
        return 200  # Run AFTER auto-pin (which is 100)

    @property
    def trigger(self) -> str:
        return "compile"

    def evaluate(self, tract: Tract) -> PolicyAction | None:
        config = tract.config
        if config.token_budget is None or config.token_budget.max_tokens is None:
            return None

        max_tokens = config.token_budget.max_tokens
        # Use status() which uses cached compilation
        status = tract.status()
        current_tokens = status.token_count

        if current_tokens >= max_tokens * self._threshold:
            return PolicyAction(
                action_type="compress",
                params={"auto_commit": True},  # or False for collaborative
                reason=f"Token usage {current_tokens}/{max_tokens} exceeds {self._threshold:.0%} threshold",
                autonomy="collaborative",
            )
        return None
```

### Example 2: PinPolicy.evaluate() - Content-Type Based Auto-Pin
```python
# Pattern: Examine recent commits for content types that should be pinned

class PinPolicy(Policy):
    """Auto-pin commits matching content type rules."""

    def __init__(
        self,
        pin_types: set[str] | None = None,
        patterns: list[dict] | None = None,
    ):
        self._pin_types = pin_types or {"instruction", "session"}
        self._patterns = patterns or []

    @property
    def name(self) -> str:
        return "auto-pin"

    @property
    def priority(self) -> int:
        return 100  # Run BEFORE auto-compress

    @property
    def trigger(self) -> str:
        return "commit"  # Evaluate immediately after commit

    def evaluate(self, tract: Tract) -> PolicyAction | None:
        head = tract.head
        if head is None:
            return None

        # Check the most recent commit
        commit = tract.get_commit(head)
        if commit is None:
            return None

        # Already pinned? Skip.
        annotations = tract.get_annotations(head)
        if annotations and annotations[-1].priority == Priority.PINNED:
            return None

        # Check if user manually set to NORMAL or SKIP
        if annotations:
            # If there's any annotation, user already made a choice
            return None

        # Content type match
        if commit.content_type in self._pin_types:
            return PolicyAction(
                action_type="annotate",
                params={
                    "target_hash": head,
                    "priority": "pinned",
                    "reason": f"Auto-pinned: content type '{commit.content_type}'",
                },
                reason=f"Content type '{commit.content_type}' matches auto-pin rule",
                autonomy="autonomous",  # Pinning is low-risk, auto-execute
            )
        return None
```

### Example 3: Schema Tables (Follows Existing ORM Patterns)
```python
# Source: Follows pattern from src/tract/storage/schema.py

class PolicyProposalRow(Base):
    """A pending policy action proposal awaiting human review."""

    __tablename__ = "policy_proposals"

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tract_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_params_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # status: "pending", "approved", "rejected", "expired", "executed"
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_policy_proposals_tract_status", "tract_id", "status"),
    )


class PolicyLogRow(Base):
    """Append-only audit log for policy evaluations."""

    __tablename__ = "policy_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tract_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    # outcome: "executed", "proposed", "skipped", "error"
    commit_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # The commit produced by this action (if any)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_policy_log_tract_time", "tract_id", "created_at"),
    )
```

### Example 4: PolicyRepository (Follows Existing ABC Pattern)
```python
# Source: Follows pattern from src/tract/storage/repositories.py

class PolicyRepository(ABC):
    """Abstract interface for policy storage operations."""

    @abstractmethod
    def save_proposal(self, proposal: PolicyProposalRow) -> None:
        """Save a policy proposal."""
        ...

    @abstractmethod
    def get_proposal(self, proposal_id: str) -> PolicyProposalRow | None:
        """Get a proposal by ID."""
        ...

    @abstractmethod
    def get_pending_proposals(self, tract_id: str) -> list[PolicyProposalRow]:
        """Get all pending proposals for a tract."""
        ...

    @abstractmethod
    def update_proposal_status(
        self, proposal_id: str, status: str, resolved_at: datetime
    ) -> None:
        """Update proposal status."""
        ...

    @abstractmethod
    def save_log_entry(self, entry: PolicyLogRow) -> None:
        """Append an audit log entry."""
        ...

    @abstractmethod
    def get_log(
        self,
        tract_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        policy_name: str | None = None,
        limit: int = 100,
    ) -> list[PolicyLogRow]:
        """Query audit log with optional filters."""
        ...
```

### Example 5: Commit Metadata for Policy-Generated Commits
```python
# Pattern: Use existing metadata_json field on CommitRow to mark policy-generated commits

# When a policy-triggered compress() executes:
result = tract.compress(
    auto_commit=True,
    # The compress operation doesn't directly support metadata,
    # but the commits it creates can be identified by the policy audit log.
)

# The audit log entry links policy_name + action to the resulting commit_hash.
# This is queryable: "show me all commits generated by auto-compress"
```

### Example 6: Tract.compile() Integration Point
```python
# Pattern: Minimal addition to existing compile() method

def compile(self, *, evaluate_policies: bool = True, **kwargs):
    """Compile with optional policy evaluation."""
    # Run compile-triggered policies BEFORE compilation
    if evaluate_policies and hasattr(self, '_policy_evaluator') and self._policy_evaluator:
        self._policy_evaluator.evaluate(trigger="compile")

    # ... existing compile logic unchanged ...
```

### Example 7: RebasePolicy - Stale Branch Archiving
```python
# Pattern: Check branch staleness by examining commit timestamps

class RebasePolicy(Policy):
    """Auto-archive stale branches."""

    def __init__(
        self,
        stale_days: int = 7,
        min_commits: int = 3,
        archive_prefix: str = "archive/",
    ):
        self._stale_days = stale_days
        self._min_commits = min_commits
        self._archive_prefix = archive_prefix

    @property
    def name(self) -> str:
        return "auto-rebase"

    @property
    def priority(self) -> int:
        return 500  # Run last

    @property
    def trigger(self) -> str:
        return "compile"

    def evaluate(self, tract: Tract) -> PolicyAction | None:
        from datetime import datetime, timezone

        current_branch = tract.current_branch
        if current_branch is None or current_branch == "main":
            return None

        # Check branch staleness via recent commits
        recent = tract.log(limit=1)
        if not recent:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        last_commit_time = recent[0].created_at
        if last_commit_time.tzinfo:
            last_commit_time = last_commit_time.replace(tzinfo=None)

        age_days = (now - last_commit_time).total_seconds() / 86400

        # Check staleness criteria
        all_commits = tract.log(limit=self._min_commits + 1)
        if age_days >= self._stale_days and len(all_commits) <= self._min_commits:
            archive_name = f"{self._archive_prefix}{current_branch}"
            return PolicyAction(
                action_type="archive",
                params={
                    "source_branch": current_branch,
                    "archive_name": archive_name,
                },
                reason=f"Branch '{current_branch}' stale ({age_days:.0f} days, {len(all_commits)} commits)",
                autonomy="collaborative",
            )
        return None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual compress() calls | Policy-triggered auto-compress | Phase 6 (new) | Removes need for users to manually monitor token budgets |
| Manual annotate() for pinning | Auto-pin by content type + patterns | Phase 6 (new) | Critical content protected automatically |
| Manual branch management | Auto-archive stale branches | Phase 6 (new) | Reduces branch clutter |
| No tangent detection | Auto-branch on tangent (heuristic) | Phase 6 (new) | Keeps main context line focused |

**Existing codebase conventions that MUST be followed:**
- `from __future__ import annotations` at top of every module
- `if TYPE_CHECKING:` for heavy import guards
- `logger = logging.getLogger(__name__)` for module loggers
- `str, enum.Enum` for string enums (not plain Enum)
- Frozen dataclasses for result types (`@dataclass(frozen=True)`)
- Mutable dataclasses for pending/proposal types (`@dataclass`)
- Pydantic BaseModel for config/validation models
- ABC for repository interfaces, Protocol for user-facing pluggable interfaces
- `self._session.flush()` after every individual DB write (not batch)
- `self._session.commit()` at Tract facade level after operation completes
- Imports from `tract.xyz` (not relative imports)

## Open Questions

Things that couldn't be fully resolved and are marked as "Claude's Discretion" in CONTEXT.md:

1. **Auto-branch tangent detection heuristic**
   - What we know: User wants this feature but left heuristic design to Claude's discretion.
   - What's unclear: What constitutes a "tangent" in an LLM context. Content type switching? Topic change? User-defined markers?
   - Recommendation: Start with the simplest heuristic: consecutive commits with a dramatic content type shift (e.g., dialogue->artifact->tool_io rapid cycling). Make the heuristic configurable and conservative (low false-positive rate). Users can provide custom BranchPolicy implementations for domain-specific tangent detection.

2. **Cooldown mechanism between policy firings**
   - What we know: CONTEXT.md says "Claude's discretion on whether proposal tracking handles this naturally."
   - What's unclear: Whether cooldowns should be time-based, event-based, or count-based.
   - Recommendation: Use proposal tracking as the natural cooldown. If a `PolicyProposal` with status="pending" exists for a given policy, skip evaluation for that policy. This prevents re-proposing the same action before the user responds. For autonomous policies, track last execution time in a simple `_last_fired: dict[str, datetime]` on the evaluator with a configurable cooldown period (default: 0 for no cooldown).

3. **Notification mechanism for collaborative mode proposals**
   - What we know: CONTEXT.md says "Claude's discretion."
   - What's unclear: Whether proposals should be returned from compile(), use a callback, or require polling.
   - Recommendation: Return proposals as part of the compile() result. Add an optional `PolicyProposal` list to the return. For commit-triggered policies, return proposals from commit(). Alternatively, use a callback-based approach: `tract.configure_policies(on_proposal=my_callback)`. The callback approach is more flexible and doesn't change compile()'s return type. **Recommended: callback approach** since it doesn't require breaking the compile() signature.

4. **Whether to add CLI commands for policy management**
   - What we know: CONTEXT.md says "SDK-only is fine for v2."
   - Recommendation: Skip CLI commands for now. The SDK API is sufficient. CLI commands can be added later as the interface stabilizes.

5. **Policy config persistence strategy**
   - What we know: Policy definitions should persist to DB as JSON and survive restarts.
   - What's unclear: Whether to use `_trace_meta` table or a dedicated table.
   - Recommendation: Use `_trace_meta` table with key format `"policy_config"`. Simple, uses existing infrastructure. Store as JSON string containing a list of policy configurations. Each config has `{name, type, enabled, priority, params}`. On `Tract.open()`, load config and instantiate built-in policies. Runtime-registered custom policies don't persist (as per CONTEXT.md).

## Sources

### Primary (HIGH confidence)
- **Existing codebase analysis** -- All patterns documented above are derived directly from reading the source files:
  - `src/tract/tract.py` -- Tract facade, sidecar pattern, method signatures
  - `src/tract/operations/compression.py` -- Compression operation, 3 autonomy modes, PendingCompression flow
  - `src/tract/models/compression.py` -- PendingCompression dataclass, result types
  - `src/tract/storage/schema.py` -- ORM table definitions, all existing tables
  - `src/tract/storage/engine.py` -- init_db() migration chain (v1->v2->v3->v4)
  - `src/tract/storage/repositories.py` -- ABC interface pattern for all repositories
  - `src/tract/storage/sqlite.py` -- SQLite implementation pattern
  - `src/tract/protocols.py` -- Protocol pattern for user-facing interfaces
  - `src/tract/llm/protocols.py` -- LLMClient, ResolverCallable protocols
  - `src/tract/models/config.py` -- TractConfig Pydantic model, BudgetAction enum
  - `src/tract/models/annotations.py` -- Priority enum, PriorityAnnotation model
  - `src/tract/models/content.py` -- Content type system, BUILTIN_TYPE_HINTS
  - `src/tract/exceptions.py` -- Exception hierarchy pattern
  - `tests/conftest.py` -- Test fixture patterns
  - `tests/test_compression.py` -- MockLLMClient pattern, test structure

### Secondary (MEDIUM confidence)
- None needed -- this is entirely an internal codebase pattern extension.

### Tertiary (LOW confidence)
- **Auto-branch tangent detection**: No established pattern exists in the codebase or general literature for "LLM context tangent detection." This is novel and heuristic-based. Marked as needing iterative refinement.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies, all patterns from existing codebase
- Architecture: HIGH - Sidecar pattern directly specified by CONTEXT.md, all building blocks exist
- Storage/schema: HIGH - Follows exact pattern of existing tables and migrations
- Policy protocol: HIGH - ABC pattern matches repositories.py, Protocol pattern matches protocols.py
- Built-in policies (compress, pin): HIGH - Direct orchestration of existing operations
- Built-in policies (branch, rebase): MEDIUM - Heuristics for tangent detection and staleness are novel
- Pitfalls: HIGH - Derived from understanding actual codebase constraints
- Cooldown/notification: MEDIUM - Discretionary decisions, recommendations provided

**Research date:** 2026-02-17
**Valid until:** Indefinite (internal codebase patterns, not external library versions)
