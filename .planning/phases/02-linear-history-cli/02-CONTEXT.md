# Phase 2: Linear History & CLI - Context

**Gathered:** 2026-02-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can inspect, navigate, and manipulate linear commit history through both the SDK and a CLI. Includes log, status, diff, reset, and checkout operations. Branching is Phase 3 — Phase 2 operates on a single linear branch (main).

</domain>

<decisions>
## Implementation Decisions

### Diff for structured content
- Metadata header style: role displayed as labeled header above content diff, not inline prefix
- Role changes annotated with arrow notation (e.g., `role: user → assistant`)
- Line-level diffs within messages (not just message-level add/remove)
- Content displayed in chronological order when commit has multiple types (not sectioned by type)
- Token count changes shown per-message AND as total delta
- EDIT commits auto-resolve: `tract diff <edit-commit>` automatically finds and diffs against the original target (user can still specify two commits explicitly)
- `--stat` flag for summary mode (e.g., "2 messages modified, 1 added, tokens: -55")
- generation_config changes shown in diff header (e.g., `temperature: 0.7 → 0.9`)
- Priority annotation changes NOT shown in diffs (annotations are metadata, not diff material)
- JSON/tool_result content: pretty-printed key-level diff (not raw text diff)

### CLI output style
- Hybrid aesthetic: plain text for most output, Rich formatting for tables (log) and diffs
- CLI command name: `tract` (matches package import, avoids stdlib `trace` collision)
- No `--json` flag on CLI — SDK is the programmatic interface, CLI is for humans only
- No built-in pager — history is bounded by context window size; users can pipe to `less`
- Auto-detect TTY for Rich formatting degradation when piped
- `-n`/`--limit` flag on `log` only (other commands don't list multiple items)
- Error messages include fuzzy-match suggestions (e.g., "Commit abc123 not found. Did you mean abc124?")
- No confirmation prompts — user said what they meant; `--force` as safety valve (like git)

### Log & status display
- Two modes: compact (default, `--oneline`) and detailed (`--verbose`)
- Compact: hash (short), timestamp, operation type, content preview (truncated). One line per commit.
- Verbose: hash, timestamp, operation, content type, token count, generation_config key params inline (temp, model, max_tokens). 2-3 lines per commit.
- Both cumulative and per-commit token counts shown
- `--op` filter for operation type (append/edit). No content type filter (too niche).
- Status shows: HEAD position, branch name, token budget progress bar (`[=========>......] 67% of 128k`), plus last 3 commits as mini-preview for quick orientation

### Reset & checkout behavior
- Hard reset: orphans forward commits (stay in DB, unreachable). GC in Phase 4 cleans them up. Matches git behavior.
- Soft reset: moves HEAD back, stores ORIG_HEAD ref pointing to previous HEAD position. Explicit recovery path.
- Checkout moves HEAD (git-style), not a separate "view pointer". Simpler mental model.
- Detached HEAD is read-only — cannot commit. Error message: "Cannot commit in detached HEAD. Use 'tract checkout main' to return to your branch."
- Short hash prefix matching (like git) — accepts unique prefixes for commit references
- `tract checkout -` shortcut to return to previous position (like `cd -` / `git checkout -`)
- Reset available as both SDK method (`tract.reset(target, mode='soft')`) and CLI command

### Compile cache upgrade (Phase 2)
- Replace single-snapshot cache with LRU cache keyed by head_hash
- Checkout, reset, and future branch switching all naturally handled: HEAD changes → LRU lookup → hit or miss
- Incremental APPEND still works: check if new commit's parent matches a cached snapshot → O(1) extend
- EDIT uses snapshot patching: copy parent's cached snapshot, patch the edited message in-memory, re-aggregate. Zero DB re-reads.
- Annotate (priority change) also uses snapshot patching
- batch() remains full recompile (special case)
- On crash, cache is lost — next compile() rebuilds from SQLite (DB is always source of truth)

### Claude's Discretion
- CLI framework choice (Click vs Typer — roadmap mentions Click + Rich)
- Rich formatting degradation strategy for piped output
- Exact progress bar rendering for token budget
- Compact log format exact layout
- LRU cache capacity (number of snapshots to retain)

</decisions>

<specifics>
## Specific Ideas

- Status command inspired by the difference from git: "Trace doesn't have a working tree, so status is about 'where am I in my context?' — showing recent commits gives immediate orientation"
- Hard reset follows git's orphan model specifically to align with Phase 4 GC which already plans configurable retention policies
- LRU cache design is branch-unaware by intent — keyed by head_hash, not branch name — so Phase 3 branching works without cache changes
- Snapshot patching avoids the expensive part of recompilation (SQLite I/O for chain walking) by operating entirely on in-memory data already in the cached snapshot
- Double-sided (child) pointers explicitly rejected — breaks commit immutability and content-addressable hashing

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-linear-history-cli*
*Context gathered: 2026-02-11*
