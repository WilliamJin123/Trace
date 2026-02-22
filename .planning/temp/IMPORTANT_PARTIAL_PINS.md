# IMPORTANT Priority Tier — Partial Pins

> Status: **DESIGN APPROVED** (discussion 2026-02-21)
> Scope: New `IMPORTANT` priority level with retention-aware compression

## Problem

The current priority model (`PINNED / NORMAL / SKIP`) creates a hard cliff:
content is either untouchable or fully compressible. There is no way to say
"compress this, but be careful to preserve specific subpoints."

## Solution

Add an `IMPORTANT` priority tier that changes **how** content is compressed,
not **when**. IMPORTANT commits are compressed in normal order alongside NORMAL
commits, but their summarization prompt is enriched with retention criteria and
the output can be validated post-hoc.

## Design Decisions (from discussion)

1. **IMPORTANT does NOT mean "compress last."** It means "compress with extra
   care to preserve specified subpoints."
2. **Retention criteria are optional.** Bare `IMPORTANT` (no criteria) signals
   the LLM to be conservative. With criteria, the LLM gets explicit guidance.
3. **Two flavors of criteria:**
   - **Fuzzy (instructions):** Natural language guidance injected into the
     summarization prompt. No extra LLM pass. Example:
     `retain="preserve all financial figures and deadlines"`
   - **Deterministic (validation):** Concrete regex/substring checks run
     against the compressed output. No LLM pass — just string matching.
     Example: `retain_match=["$50k", r"\d{4}-\d{2}-\d{2}"]`
   - Both can be used together: fuzzy guides the LLM, deterministic validates.
4. **Failure handling (deferred):** When deterministic validation fails, the
   preferred approach is isolate-and-patch (targeted follow-up LLM call to fix
   only what's missing), not full redo. Exact thresholds for patch-vs-redo are
   deferred to the smarter failure handling design.

## Priority Enum Change

```python
# src/tract/models/annotations.py
class Priority(str, enum.Enum):
    SKIP = "skip"
    NORMAL = "normal"
    IMPORTANT = "important"   # NEW
    PINNED = "pinned"
```

Compression order: SKIP (excluded) -> NORMAL (freely compressible) ->
IMPORTANT (compressible with retention) -> PINNED (never compressed).

## Retention Criteria Model

```python
# src/tract/models/annotations.py (new or extended)
class RetentionCriteria(BaseModel):
    """Retention criteria for IMPORTANT commits."""
    instructions: str | None = None          # Fuzzy: NL guidance for the LLM
    match_patterns: list[str] | None = None  # Deterministic: substrings/regexes to validate
    match_mode: Literal["substring", "regex"] = "substring"  # How to interpret patterns
```

Stored as JSON on the `PriorityAnnotation` (new nullable `retention_json` column).

## Schema Change

```sql
-- Annotation table: add retention_json column
ALTER TABLE annotation ADD COLUMN retention_json TEXT;  -- JSON-encoded RetentionCriteria
```

Schema version bump required (v6 -> v7 or whatever is current).

## API Surface

### Annotate with retention

```python
# On Tract facade
t.annotate(commit_hash, priority=IMPORTANT)                    # bare: conservative
t.annotate(commit_hash, priority=IMPORTANT,
           retain="preserve all dollar amounts")               # fuzzy
t.annotate(commit_hash, priority=IMPORTANT,
           retain_match=["$50k", r"\d{4}-\d{2}-\d{2}"])       # deterministic
t.annotate(commit_hash, priority=IMPORTANT,
           retain="keep financial details",
           retain_match=["$50k"])                              # both
```

### Shorthand at commit time

```python
t.user("Long requirements doc...",
       priority=IMPORTANT,
       retain="preserve budget and timeline constraints")
```

## Compression Engine Changes

### `_classify_by_priority` (compression.py)

Currently returns `(pinned, normal, skip)`. Change to return
`(pinned, important, normal, skip)`. IMPORTANT commits are compressed
alongside NORMAL commits (same partitioning logic) but flagged for
enriched summarization.

### `_summarize_group` (compression.py)

When a group contains IMPORTANT commits, gather their retention criteria
and inject into the summarization prompt:

1. Collect all `RetentionCriteria.instructions` from IMPORTANT commits in
   the group. Append to the `instructions` parameter of
   `build_summarize_prompt()`.
2. After summarization, if any IMPORTANT commits have `match_patterns`,
   run deterministic validation against the summary output.
3. On validation failure: **deferred** (see Failure Protocol below).

### `build_summarize_prompt` (prompts/summarize.py)

Add optional `retention_instructions` parameter that gets a dedicated
section in the prompt:

```
IMPORTANT: The following content was marked as important. You MUST
preserve these specific details in your summary:
- {instruction_1}
- {instruction_2}
```

### Deterministic Validation (new: `_validate_retention`)

```python
def _validate_retention(
    summary: str,
    criteria: list[RetentionCriteria],
) -> list[RetentionFailure]:
    """Check summary against deterministic retention criteria.

    Returns list of failures (empty = all passed).
    """
```

Runs substring or regex checks. No LLM call. Returns structured failures
with the specific pattern that wasn't found.

## Failure Protocol (via Unified Retry Protocol)

Uses `retry_with_steering()` from `src/tract/retry.py` (implemented in the
Retry Protocol plan). The compression retry is wired as follows:

**validate callable — `_validate_retention()`:**
```python
def _validate_retention(
    summary: str,
    criteria: list[RetentionCriteria],
) -> tuple[bool, str | None]:
    """Check summary against deterministic retention criteria.

    Returns (True, None) if all checks pass, or
    (False, diagnosis) with a description of what's missing.
    """
    failures = []
    for c in criteria:
        if c.match_patterns:
            for pattern in c.match_patterns:
                if c.match_mode == "regex":
                    if not re.search(pattern, summary):
                        failures.append(f"regex not found: {pattern}")
                else:
                    if pattern not in summary:
                        failures.append(f"substring not found: {pattern}")
    if failures:
        return (False, "Summary missing: " + "; ".join(failures))
    return (True, None)
```

**steer callable — amends the summarization prompt:**

On validation failure, steering appends the diagnosis to the `instructions`
parameter for the next `_summarize_group()` call. This is a prompt amendment,
not a committed message (compression operates outside the commit chain).

```python
def _steer(diagnosis: str):
    nonlocal instructions
    instructions = (instructions or "") + (
        f"\n\nPrevious summary failed validation: {diagnosis}\n"
        "Revise to include the missing details while keeping the summary concise."
    )
```

**attempt callable — `_summarize_group()` re-call:**

Each retry re-invokes `_summarize_group()` with the amended instructions.
The LLM sees its previous failure diagnosis and can surgically patch.

**Escalation:** If all retries exhaust (`max_retries`, default 3),
`RetryExhaustedError` propagates. The caller receives the last diagnosis
in the exception and can decide whether to surface it, fall back to manual
compression, or widen the retry scope.

Key principle: **isolate and patch, don't redo** — minimize wasted LLM passes
by surgically fixing only what's broken.

## Implementation Order

1. **Priority enum + RetentionCriteria model** — add IMPORTANT to enum,
   create RetentionCriteria model, schema migration
2. **Annotation storage** — retention_json column, read/write in repository
3. **API surface** — `annotate()` and shorthand methods accept retention params
4. **Prompt enrichment** — modify `build_summarize_prompt` and `_summarize_group`
   to inject retention instructions for IMPORTANT commits
5. **Deterministic validation** — `_validate_retention` function,
   wired into compress_range via `retry_with_steering()` from retry protocol
6. **Tests** — unit tests for each layer, integration test for full
   compress-with-retention flow including retry on validation failure

## Files to Modify

- `src/tract/models/annotations.py` — Priority enum, RetentionCriteria model
- `src/tract/storage/schema.py` — retention_json column on annotation table
- `src/tract/storage/repositories.py` — read/write retention_json
- `src/tract/operations/compression.py` — classify, summarize, validate
- `src/tract/prompts/summarize.py` — retention-aware prompt building
- `src/tract/tract.py` — annotate() and shorthand commit methods
- `src/tract/models/compression.py` — RetentionFailure model, CompressResult extension

## Open Questions (for implementation time)

- Exact schema version number (check current before implementing)
- Whether `retain` / `retain_match` should also be passable to `compress_range()`
  directly (ad-hoc retention without prior annotation)
- Default type priorities: should any built-in types default to IMPORTANT?
  (Candidate: `instruction` could downgrade from PINNED to IMPORTANT)
