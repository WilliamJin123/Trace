---
date: 2026-02-12
summary: "How Trace implements git-like history navigation, structured diff, and a terminal CLI — the first user-facing layer on top of the foundation"
audience: intermediate
---

# Phase 2: Linear History & CLI

Phase 1 gave us the ability to commit structured context and compile it for LLM consumption. But there was no way to *look back* — no log, no diff, no way to move HEAD to a previous commit and inspect what the context looked like at that point. Phase 2 fills that gap by building three categories of functionality: navigation operations (reset, checkout), read operations (log, status, diff), and a terminal CLI that wraps everything for human debugging.

The design follows git's model closely — not because we're building git, but because git's abstractions (symbolic refs, detached HEAD, prefix matching) solve exactly the problems we face. The key insight is that "where am I?" and "what changed?" are questions every debugging session starts with, and answering them well requires real infrastructure, not just printing commit hashes.

## Symbolic References: Git-Style HEAD

### The Problem with Direct HEAD

In Phase 1, HEAD was simple: a row in the `refs` table with `ref_name="HEAD"` and `commit_hash` pointing directly at the latest commit. Every `update_head()` call overwrote that hash. This worked because there was only one thing HEAD could do — advance forward on each commit.

But Phase 2 introduces *movement*. You need to checkout a specific commit for inspection (detached HEAD), then return to your branch (attached HEAD). You need reset to move HEAD backward. And Phase 3 will need branches, where HEAD points to a branch name and the branch points to a commit. A single `commit_hash` field can't express all of these states.

### The Symbolic Ref Design

The solution is git's two-level indirection. HEAD can be in one of two states:

**Attached** (normal operation): HEAD stores a `symbolic_target` like `"refs/heads/main"` and a null `commit_hash`. The branch ref `refs/heads/main` stores the actual commit hash. When you commit, `update_head()` follows the symbolic target and updates the branch ref — HEAD itself doesn't change.

**Detached** (read-only inspection): HEAD stores a `commit_hash` directly and a null `symbolic_target`. This happens when you checkout a specific commit. Committing is blocked because there's no branch to advance.

The `RefRow` schema already had a `symbolic_target` column from Phase 1's schema design (forward-thinking), so no migration was needed. The implementation lives in `SqliteRefRepository`:

```python
# src/tract/storage/sqlite.py — get_head() resolves the symbolic chain
def get_head(self, tract_id: str) -> str | None:
    head_ref = self._get_ref_row(tract_id, "HEAD")
    if head_ref is None:
        return None
    # Attached: follow symbolic target to branch ref
    if head_ref.symbolic_target:
        branch_ref = self._get_ref_row(tract_id, head_ref.symbolic_target)
        return branch_ref.commit_hash if branch_ref else None
    # Detached: commit_hash stored directly
    return head_ref.commit_hash
```

### Backward Compatibility: The Critical Constraint

The hardest part of this change wasn't the new methods — it was ensuring `update_head()` still worked correctly for Phase 1's `CommitEngine`, which calls it on every commit without knowing about symbolic refs. The solution: `update_head()` detects the current HEAD state and does the right thing:

- **No HEAD exists** (first commit): Creates a symbolic HEAD pointing to `refs/heads/main` *and* creates the branch ref. This means the very first commit in a tract sets up the full symbolic ref infrastructure transparently.
- **Attached HEAD** (normal commits): Follows `symbolic_target` to find the branch ref and updates the branch's `commit_hash`. HEAD itself is untouched.
- **Detached HEAD** (shouldn't happen for commits, but handled): Updates `commit_hash` directly.

This design means all 267 existing Phase 1 tests pass without modification — they never knew HEAD became symbolic under the hood. The `get_head()` → `update_head()` contract is preserved; only the internal representation changed.

### Why Not Just Store State as an Enum?

An alternative would have been a `head_state` enum column (ATTACHED, DETACHED) with conditional logic everywhere. We rejected this because the symbolic ref model is *self-describing* — the presence or absence of `symbolic_target` tells you the state. There's no enum to get out of sync with reality. It also naturally extends to Phase 3's branches: creating a branch is just adding a new `refs/heads/{name}` row, and switching branches is just changing HEAD's `symbolic_target`.

## The Operations Layer

Phase 2 introduces a new architectural layer: `src/tract/operations/`. Before this, the code had two layers — storage (repositories) and facade (Tract class), with the engine sitting between them for commit/compile logic. The operations layer fills a gap: *composable business logic that uses storage primitives but doesn't belong in the Tract facade*.

The reasoning is separation of concerns. `resolve_commit()` needs to try three different resolution strategies (exact hash, branch name, prefix). That's 20+ lines of logic with error handling. Putting it directly in `Tract.resolve_commit()` would work, but then testing it requires a full Tract instance. By extracting it to `operations/navigation.py` as a pure function that takes repositories as parameters, we can test the logic independently and reuse it across multiple Tract methods.

Phase 2 creates three operations modules:

- **`navigation.py`**: `resolve_commit()`, `reset()`, `checkout()` — write operations that manipulate HEAD position
- **`history.py`**: `StatusInfo` dataclass — data model for tract status reporting
- **`diff.py`**: `compute_diff()`, `DiffResult`, `MessageDiff`, `DiffStat` — structured diff computation

The pattern is consistent: operations modules contain either pure functions (taking repos as args) or frozen dataclasses (immutable return values). No global state, no database sessions, no side effects beyond what's passed in.

## Navigation: reset, checkout, resolve_commit

### Three-Tier Commit Resolution

Every navigation operation starts with resolving a user-provided string to a full commit hash. Users might type a full 64-character SHA-256 hash, a branch name like `"main"`, or a short prefix like `"a1b2c3d"`. The resolution logic in `operations/navigation.py` tries each strategy in order:

```python
def resolve_commit(ref_or_prefix, tract_id, commit_repo, ref_repo):
    # 1. Exact hash match
    row = commit_repo.get(ref_or_prefix)
    if row is not None:
        return row.commit_hash

    # 2. Branch name
    branch_hash = ref_repo.get_branch(tract_id, ref_or_prefix)
    if branch_hash is not None:
        return branch_hash

    # 3. Hash prefix (minimum 4 characters, like git)
    if len(ref_or_prefix) >= 4:
        row = commit_repo.get_by_prefix(ref_or_prefix, tract_id=tract_id)
        if row is not None:
            return row.commit_hash

    raise CommitNotFoundError(ref_or_prefix)
```

Prefix matching uses SQL's `LIKE` operator via `CommitRow.commit_hash.startswith(prefix)`. If multiple commits match, `get_by_prefix()` raises `AmbiguousPrefixError` with the list of candidates — practically impossible with SHA-256 at normal repo sizes, but the code handles it correctly.

### Reset: Moving HEAD Backward

Reset is conceptually simple: move HEAD to a target commit. Both `--soft` and `--hard` modes exist for API compatibility with git, but in Trace they're identical at the storage level. There's no working directory to clean, no staged changes to unstage. The distinction is semantic — soft means "I might come back" and hard means "I'm discarding forward history." Phase 4's garbage collector will differentiate: hard reset will mark orphaned commits for aggressive GC, while soft preserves them under normal retention.

Before moving HEAD, reset saves the current position as `ORIG_HEAD`:

```python
def reset(target_hash, mode, tract_id, ref_repo):
    current_head = ref_repo.get_head(tract_id)
    if current_head is not None:
        ref_repo.set_ref(tract_id, "ORIG_HEAD", current_head)
    ref_repo.update_head(tract_id, target_hash)
    return target_hash
```

At the Tract facade level, `reset()` also clears the compile cache (since HEAD changed, cached compiled context is stale) and commits the database transaction.

### Checkout: Attach vs Detach

Checkout is the most complex navigation operation because it has three modes:

**Branch checkout** (`tract.checkout("main")`): Attaches HEAD to the branch. The branch ref must exist. After this, `is_detached` returns False and commits go to that branch.

**Commit checkout** (`tract.checkout("a1b2c3d")`): Detaches HEAD at that commit. The user can inspect the context at that point, but committing is blocked by the `DetachedHeadError` guard that Phase 2 adds to `Tract.commit()`.

**Dash checkout** (`tract.checkout("-")`): Returns to the previous position via `PREV_HEAD`, like `cd -` in bash. Before every checkout, the current HEAD is saved as `PREV_HEAD`, so `-` always takes you back to where you were.

The implementation distinguishes branch from commit by attempting a branch lookup first:

```python
def checkout(target, tract_id, commit_repo, ref_repo):
    # Save current position
    current_head = ref_repo.get_head(tract_id)
    if current_head is not None:
        ref_repo.set_ref(tract_id, "PREV_HEAD", current_head)

    # Try as branch name first
    branch_hash = ref_repo.get_branch(tract_id, target)
    if branch_hash is not None:
        ref_repo.attach_head(tract_id, target)
        return branch_hash, False  # not detached

    # Resolve as commit hash or prefix
    resolved = resolve_commit(target, tract_id, commit_repo, ref_repo)
    ref_repo.detach_head(tract_id, resolved)
    return resolved, True  # detached
```

A subtle design choice: unlike reset, checkout does *not* clear the LRU compile cache. The cache is keyed by `head_hash`, so switching HEAD to a previously-compiled position gets a cache hit. This is the whole point of Phase 1.4's LRU cache — checkout, reset, and future branch switching benefit from cached compilations.

### The DetachedHeadError Guard

Phase 2 adds a guard at the top of `Tract.commit()`:

```python
def commit(self, content, ...):
    if self._ref_repo.is_detached(self._tract_id):
        raise DetachedHeadError()
    # ... rest of commit logic
```

The error message is actionable: *"Cannot commit in detached HEAD state. Use 'tract checkout main' to return to your branch."* This guard lives in the Tract facade, not in CommitEngine, because detached HEAD is a facade-level concept — CommitEngine operates at a lower level and doesn't know about symbolic refs.

## Read Operations: log, status, diff

### Enhanced Log with Operation Filter

Phase 1's `Tract.log()` walked the commit chain from HEAD and returned a list of `CommitInfo` objects. Phase 2 enhances it with two changes:

1. **Default limit raised from 10 to 20** — more context is usually better for debugging.
2. **`op_filter` parameter** — filter by `CommitOperation.APPEND` or `CommitOperation.EDIT` to see only specific operation types.

The filter implementation is worth noting: `get_ancestors()` walks through *all* ancestors but only collects commits matching the filter. The limit applies to matches, not total traversed. This means `log(limit=5, op_filter=EDIT)` might walk 20 commits to find 5 edits, but the caller gets exactly 5 results.

### Status: A Snapshot of Current State

`Tract.status()` returns a frozen `StatusInfo` dataclass that captures everything you need to understand the current tract state:

```python
@dataclass(frozen=True)
class StatusInfo:
    head_hash: str | None
    branch_name: str | None       # None if detached
    is_detached: bool
    commit_count: int             # total commits in compiled chain
    token_count: int              # compiled token count
    token_budget_max: int | None  # None if no budget
    token_source: str
    recent_commits: list[CommitInfo]  # last 3 commits
```

The implementation calls `compile()` to get token counts (leveraging the LRU cache), queries the ref repo for branch/detached state, and fetches the last 3 commits via `log(limit=3)`. It's a composition of existing operations, not new logic — exactly what the facade pattern is for.

We chose a frozen dataclass over a Pydantic model because StatusInfo is a lightweight read-only snapshot, not a validated input. There's no serialization or deserialization — it's constructed internally and consumed by the CLI or user code.

### Diff: SequenceMatcher for Message Alignment

The diff operation is the most algorithmically interesting part of Phase 2. The challenge: given two compiled message lists (from two different commits), produce a structured diff showing which messages were added, removed, modified, or unchanged.

The naive approach would be index-based comparison — message 0 in A vs message 0 in B, etc. But this fails when messages are inserted or deleted in the middle: all subsequent messages would show as "modified" even if their content is identical, just shifted.

Instead, `compute_diff()` uses `difflib.SequenceMatcher` to find the optimal alignment between the two message lists. SequenceMatcher computes the longest common subsequence (LCS) and produces opcodes that describe how to transform A into B:

```python
def compute_diff(commit_a_hash, commit_b_hash, messages_a, messages_b, ...):
    # Serialize messages to comparable strings
    serialized_a = [_serialize_message(m) for m in messages_a]
    serialized_b = [_serialize_message(m) for m in messages_b]

    # SequenceMatcher finds optimal alignment
    matcher = difflib.SequenceMatcher(None, serialized_a, serialized_b)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":    # unchanged messages
        elif tag == "replace": # modified messages (content differs)
        elif tag == "delete":  # removed messages
        elif tag == "insert":  # added messages
```

Each message is serialized to a comparable string format (`role: {role}\n---\n{content}`), so SequenceMatcher can identify which messages are "the same" across the two lists. For modified messages, we additionally run `difflib.unified_diff()` on the serialized content to produce line-by-line diff output — the familiar `+++`/`---`/`@@` format from git.

The return value is a structured `DiffResult`, not raw text:

```python
@dataclass(frozen=True)
class DiffResult:
    commit_a: str
    commit_b: str
    message_diffs: list[MessageDiff]  # per-message diffs
    stat: DiffStat                    # summary counts
    generation_config_changes: dict[str, tuple[Any, Any]]
```

This structured output means the CLI can format it with colors, but SDK users can also programmatically inspect specific changes — "did the system prompt change between these two commits?" is a single field lookup, not string parsing.

### EDIT Auto-Resolution

A key usability feature in `Tract.diff()`: when you diff an EDIT commit without specifying what to compare against, the diff automatically resolves to the original target. EDIT commits store a `edit_target` field pointing at the commit they're editing. So `tract.diff(commit_b=edit_hash)` automatically sets `commit_a` to the original commit, showing you exactly what the edit changed.

This is implemented in the Tract facade, not in `compute_diff()` itself:

```python
def diff(self, commit_a=None, commit_b=None):
    # ... resolve commit_b to HEAD if not provided
    row_b = self._commit_repo.get(commit_b)

    if commit_a is None:
        if row_b.operation == CommitOperation.EDIT and row_b.edit_target:
            commit_a = row_b.edit_target  # auto-resolve to edit target
        elif row_b.parent_hash:
            commit_a = row_b.parent_hash  # default to parent
```

### Cache Leverage via _compile_at()

Diff needs to compile two commits to get their message lists. A naive implementation would call the full compiler twice. Instead, `Tract._compile_at()` checks the LRU cache first:

```python
def _compile_at(self, commit_hash):
    cached = self._cache_get(commit_hash)
    if cached is not None:
        return self._snapshot_to_compiled(cached)
    return self._compiler.compile(self._tract_id, commit_hash)
```

If you've recently compiled at that commit (via `checkout` or a previous `diff`), the cache hit avoids a full chain walk. This is especially valuable for repeated diffs against the same base commit.

## The CLI: Click + Rich as Optional Extra

### Architecture: Why Optional Dependencies

The CLI uses Click for argument parsing and Rich for terminal formatting. But these are *not* core dependencies — `pip install tract` gives you the SDK with zero extra deps (beyond SQLAlchemy, Pydantic, tiktoken). The CLI is an optional extra: `pip install tract[cli]`.

This matters because Trace is designed to be embedded in agent frameworks. If you're using Trace programmatically inside a LangChain pipeline, you shouldn't need Click and Rich in your dependency tree. The implementation enforces this at the import level: `tract/__init__.py` never imports from `tract.cli`. The CLI module is only loaded when the `tract` console script entry point is invoked.

The guard is explicit in `src/tract/cli/__init__.py`:

```python
try:
    import click
except ImportError:
    raise ImportError(
        "CLI dependencies not installed. Install with: pip install tract[cli]"
    ) from None
```

### Click Group with Auto-Discovery

The CLI is structured as a Click group with five subcommands:

```
tract [--db PATH] [--tract-id ID] COMMAND
  log       Show commit history
  status    Show current state
  diff      Compare two commits
  reset     Move HEAD to a previous commit
  checkout  Switch to a commit or branch
```

The `--db` option (default `.tract.db`, overridable via `TRACT_DB` env var) specifies the database path. The `--tract-id` option is usually unnecessary: `_discover_tract()` queries the database for distinct tract IDs and auto-selects if there's exactly one. Multiple tracts require explicit `--tract-id`.

Each command follows the same pattern: open Tract via `_get_tract(ctx)`, call the SDK method, format the output, close the Tract. Error handling catches `TraceError` subclasses and formats them as user-friendly messages via `format_error()`.

### Rich Formatting with TTY Degradation

The formatting module (`src/tract/cli/formatting.py`) provides Rich-based formatting for each command's output. Key formatters:

- **`format_log_compact()`**: A `Rich.Table` with columns for hash (yellow, 8 chars), timestamp (dim), operation (cyan), token count (green, right-aligned), and message. Box-less layout for clean output.
- **`format_status()`**: Branch name or "HEAD detached at ..." header, token budget progress bar (30 chars, color-coded: green <70%, yellow <90%, red >90%), and last 3 commits as a mini-preview.
- **`format_diff()`**: Per-message diffs with color-coded unified diff output (green for additions, red for removals). A `--stat` mode shows just the summary counts.

Rich's `Console` auto-detects whether stdout is a TTY. When piped (`tract log | grep "system"`), ANSI escape codes are stripped automatically — no special handling needed in our code.

### The --force Guard

Hard reset requires `--force` as a safety mechanism:

```python
if mode == "hard" and not force:
    format_error("Hard reset requires --force flag.", console)
    raise SystemExit(1)
```

This is a CLI-level guard, not an SDK-level one. The SDK's `tract.reset(target, mode="hard")` works without confirmation — it's a programmatic API where the caller is presumed to know what they're doing. The CLI adds the safety rail because humans type things they didn't mean.

## Connections & What's Next

### What Phase 2 Enables

Phase 2's symbolic ref infrastructure is the foundation for Phase 3's branching. Creating a branch is just adding a new `refs/heads/{name}` row. Switching branches is changing HEAD's `symbolic_target`. The `attach_head()` and `detach_head()` methods from Phase 2 are exactly what Phase 3 needs.

The operations layer pattern (`operations/navigation.py`) establishes the architecture that Phase 3 will follow for merge, rebase, and cherry-pick operations. These are all "composable logic over storage primitives" — the exact use case the operations layer was designed for.

The CLI infrastructure (Click group, Rich formatting, auto-discovery) will absorb Phase 3's branch/merge commands without structural changes — just new command files in `cli/commands/`.

### Dependency Map

Phase 2 depends on:
- **Storage layer** (Phase 1): `CommitRepository`, `RefRepository`, `BlobRepository` ABCs and SQLite implementations
- **Engine layer** (Phase 1): `CommitEngine` for `_row_to_info()` conversion
- **Compiler** (Phase 1/1.1/1.4): `compile()` for token counts in status, `_compile_at()` for diff
- **LRU cache** (Phase 1.4): Cache hits on checkout for previously-compiled positions

Phase 2 is depended on by:
- **Phase 3** (Branching): Uses symbolic refs, operations layer pattern, CLI infrastructure
- **Phase 4** (Compression): GC will differentiate soft vs hard reset semantics
- **Phase 5** (Multi-Agent): Cross-repo queries will use log/diff infrastructure

### Test Coverage

Phase 2 added 92 new tests across three test files:
- `test_navigation.py` (35 tests): Symbolic refs, prefix matching, reset, checkout, detached HEAD, PREV_HEAD/ORIG_HEAD, LRU cache survival
- `test_operations.py` (27 tests): Enhanced log, status fields, diff algorithm, EDIT auto-resolution, DiffStat computation
- `test_cli.py` (30 tests): All 5 commands via CliRunner, error handling, --force guard, help output, isolated filesystem with file-backed databases

Total suite: 359 tests (267 existing + 92 new), all passing.

## Examples

### SDK: Navigation Flow

```python
from tract import Tract, InstructionContent, DialogueContent

# Create a tract and commit some context
t = Tract.open(":memory:")
t.commit(InstructionContent(text="You are a helpful assistant"), message="system prompt")
t.commit(DialogueContent(role="user", text="What is Python?"), message="user question")
t.commit(DialogueContent(role="assistant", text="Python is a programming language"), message="response")

# Check current state
status = t.status()
print(f"Branch: {status.branch_name}")        # "main"
print(f"Commits: {status.commit_count}")       # 3
print(f"Tokens: {status.token_count}")         # compiled token count
print(f"Detached: {status.is_detached}")       # False

# Look at history
for entry in t.log():
    print(f"{entry.commit_hash[:8]} {entry.operation.value} {entry.message}")
```

### SDK: Checkout and Inspect

```python
# Save the first commit's hash
first_hash = t.log()[-1].commit_hash  # oldest commit

# Checkout to inspect early state
t.checkout(first_hash)
print(f"Detached: {t.is_detached}")  # True

# Compile at this point — see context as it was after first commit
ctx = t.compile()
print(f"Messages at first commit: {len(ctx.messages)}")  # 1

# Can't commit in detached state
try:
    t.commit(DialogueContent(role="user", text="test"))
except DetachedHeadError as e:
    print(e)  # "Cannot commit in detached HEAD state..."

# Return to branch
t.checkout("main")
print(f"Detached: {t.is_detached}")  # False — can commit again
```

### SDK: Diff Between Commits

```python
# Diff HEAD against its parent (default behavior)
result = t.diff()
print(f"Added: {result.stat.messages_added}")
print(f"Modified: {result.stat.messages_modified}")

# Diff two specific commits by prefix
first = t.log()[-1].commit_hash[:8]
last = t.log()[0].commit_hash[:8]
result = t.diff(commit_a=first, commit_b=last)

for md in result.message_diffs:
    if md.status != "unchanged":
        print(f"Message {md.index}: {md.status}")
        if md.content_diff_lines:
            for line in md.content_diff_lines:
                print(f"  {line}")
```

### SDK: Reset and Recovery

```python
# Reset HEAD to first commit (soft — preserves forward history)
first_hash = t.log()[-1].commit_hash
t.reset(first_hash, mode="soft")
print(f"HEAD now at: {t.head[:8]}")  # first commit

# Compile at this point — only 1 message
ctx = t.compile()
print(f"Messages: {len(ctx.messages)}")  # 1

# The other commits still exist in the database
# They're just not reachable from HEAD anymore
```

### CLI: Typical Debugging Session

```bash
# Check where you are
tract status --db my_agent.db

# See recent history
tract log --db my_agent.db -n 10

# See only EDIT operations
tract log --db my_agent.db --op edit

# Diff HEAD against its parent
tract diff --db my_agent.db

# Quick summary of what changed
tract diff --db my_agent.db --stat

# Checkout an earlier commit to inspect
tract checkout a1b2c3d4 --db my_agent.db
tract status --db my_agent.db  # shows "HEAD detached at a1b2c3d4"

# Return to branch
tract checkout main --db my_agent.db

# Reset to an earlier point
tract reset a1b2c3d4 --db my_agent.db        # soft reset (default)
tract reset a1b2c3d4 --hard --force --db my_agent.db  # hard reset
```
