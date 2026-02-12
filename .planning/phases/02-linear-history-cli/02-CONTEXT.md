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
- Line-level diffs within messages (not just message-level add/remove). Strategy: serialize all content to pretty-printed text (JSON for dicts, plain for text fields), then use Python's `difflib.unified_diff()`. Consistent across all content types, no new dependency.
- Content displayed in chronological order when commit has multiple types (not sectioned by type)
- Cross-type diffs: show `content type changed: dialogue → artifact` in header, then unified diff of both serialized to text
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
- Error messages include prefix-match suggestions (e.g., "Commit abc12 not found. Closest prefix: abc123f...") — hex hashes don't fuzzy-match meaningfully, so this is prefix-based only
- No confirmation prompts — user said what they meant. `--force` required specifically for hard reset (orphans commits, data loss risk); other commands don't need it

### Log & status display
- Two modes: compact (default) and detailed (`--verbose` / `-v`)
- Compact: hash (short), timestamp, operation type, content preview (truncated). One line per commit.
- Verbose: hash, timestamp, operation, content type, token count, generation_config key params inline (temp, model, max_tokens). 2-3 lines per commit.
- Per-commit token counts shown (cumulative is available via `tract status` which uses compile(); log stays fast and avoids the raw-sum-vs-compiled ambiguity)
- `--op` filter for operation type (append/edit). No content type filter (too niche).
- Status shows: HEAD position, branch name, token budget progress bar (`[=========>......] 67% of 128k`) when budget is configured, or raw count (`Tokens: 1,234 (no budget set)`) when no budget, plus last 3 commits as mini-preview for quick orientation

### Reset & checkout behavior
- Hard reset: orphans forward commits (stay in DB, unreachable). GC in Phase 4 cleans them up. Matches git behavior.
- Soft reset: moves HEAD back, stores ORIG_HEAD ref pointing to previous HEAD position. Explicit recovery path.
- Checkout moves HEAD (git-style), not a separate "view pointer". Simpler mental model.
- Detached HEAD is read-only — cannot commit. Error message: "Cannot commit in detached HEAD. Use 'tract checkout main' to return to your branch."
- **Symbolic ref infrastructure required**: HEAD becomes a symbolic ref when attached (HEAD → `refs/heads/main`) and a direct ref when detached (HEAD → commit hash). The existing `symbolic_target` column on RefRow is used for this. `get_head()` resolves symbolic refs. `update_head()` is split into `attach_head(branch_name)` and `detach_head(commit_hash)`. `is_detached()` checks whether HEAD has a symbolic_target. Commit flow checks `is_detached()` and raises error. This lays the foundation for Phase 3 branching.
- Short hash prefix matching (like git) — accepts unique prefixes for commit references. Minimum 4 chars. Ambiguous prefix errors with up to 5 candidates: "Ambiguous prefix abc12. Matches: abc123f..., abc124a...". Requires new `get_commit_by_prefix()` repository method.
- `tract checkout -` shortcut to return to previous position (like `cd -` / `git checkout -`). Uses a dedicated `PREV_HEAD` ref (separate from `ORIG_HEAD` used by reset) — every checkout/reset updates PREV_HEAD before moving HEAD.
- Reset available as both SDK method (`tract.reset(target, mode='soft')`) and CLI command

### CLI dependency strategy
- Click + Rich are optional extras: `pip install tract[cli]`. SDK-only users (`pip install tract`) don't pull CLI deps.
- CLI module uses lazy imports with clear error message if Click/Rich not installed.

### Claude's Discretion
- CLI framework choice (Click vs Typer — roadmap mentions Click + Rich)
- Rich formatting degradation strategy for piped output
- Exact progress bar rendering for token budget
- Compact log format exact layout

</decisions>

<specifics>
## Specific Ideas

- Status command inspired by the difference from git: "Trace doesn't have a working tree, so status is about 'where am I in my context?' — showing recent commits gives immediate orientation"
- Hard reset follows git's orphan model specifically to align with Phase 4 GC which already plans configurable retention policies
- Double-sided (child) pointers explicitly rejected — breaks commit immutability and content-addressable hashing

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-linear-history-cli*
*Context gathered: 2026-02-11*
