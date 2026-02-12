# Phase 2: Linear History & CLI - Research

**Researched:** 2026-02-11
**Domain:** SDK history operations (log, status, diff, reset, checkout) + CLI layer (Click + Rich)
**Confidence:** HIGH

## Summary

Phase 2 adds five SDK operations (log, status, diff, reset, checkout) to the existing Tract facade, then wraps them in a CLI using Click for command parsing and Rich for terminal formatting. The SDK layer builds on existing infrastructure: the commit chain walker (`get_ancestors`), ref management (`RefRow` with `symbolic_target`), and the blob storage system. The CLI layer is a thin presentation wrapper -- all logic lives in the SDK.

The most complex part is the diff operation, which must serialize structured content types (7 built-in types with different field layouts) to text and run `difflib.unified_diff()`. The symbolic ref infrastructure for HEAD (attached vs detached) and the short hash prefix matching are the two new storage-layer capabilities needed. Everything else composes existing components.

**Primary recommendation:** Split into two plans: Plan 1 builds the five SDK operations with full test coverage; Plan 2 adds the CLI layer using Click groups with Rich formatting and tests via Click's CliRunner.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Click | >=8.1,<9 | CLI command groups, argument parsing, help generation | Most widely-used Python CLI framework; decorator-based; official recommendation in CONTEXT.md |
| Rich | >=13.0,<15 | Terminal tables, colored diff output, styled text, progress bars | De facto standard for terminal formatting; auto-detects TTY; referenced in CONTEXT.md |
| difflib (stdlib) | Python 3.10+ | `unified_diff()` for text comparison | Stdlib, no dependency; CONTEXT.md decision: "use difflib.unified_diff()" |
| json (stdlib) | Python 3.10+ | Pretty-printing structured content for diff | Stdlib; needed to serialize tool_io payload and freeform content for text-level diff |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pygments (via Rich) | bundled | Diff syntax highlighting via "diff" lexer | Rich's `Syntax` class can render unified diff output with diff-aware coloring (+ green, - red) |
| click.testing | bundled | `CliRunner` for CLI integration tests | All CLI tests; captures output, exit codes, exception info |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Click | Typer | Typer is built on Click, adds type-hint-based syntax. Extra dependency for no clear benefit since this CLI is simple. Click is the roadmap decision. |
| Rich Syntax (Pygments diff lexer) | Manual ANSI coloring | Rich handles TTY detection automatically; manual ANSI would require reimplementing that logic |
| difflib.unified_diff | diff-match-patch | External dep; unified_diff is sufficient for line-level text diffs |

**Installation (optional extras):**
```bash
pip install tract[cli]
```

**pyproject.toml addition:**
```toml
[project.optional-dependencies]
cli = [
    "click>=8.1,<9",
    "rich>=13.0,<15",
]

[project.scripts]
tract = "tract.cli:cli"
```

## Architecture Patterns

### Recommended Project Structure
```
src/tract/
    cli/                     # NEW: CLI package (lazy-imported)
        __init__.py          # Click group + lazy import guard
        commands/
            __init__.py
            log.py           # tract log
            status.py        # tract status
            diff.py          # tract diff
            reset.py         # tract reset
            checkout.py      # tract checkout
        formatting.py        # Rich formatting helpers (tables, diff rendering, progress bar)
    operations/              # NEW: SDK operation logic (no CLI dependency)
        __init__.py
        history.py           # log() enhancement, status() data model
        diff.py              # Diff computation (two commits -> structured diff result)
        navigation.py        # reset(), checkout(), symbolic ref helpers
    tract.py                 # Extended with: status(), diff(), reset(), checkout()
    exceptions.py            # Extended with: DetachedHeadError, AmbiguousPrefixError
    storage/
        sqlite.py            # Extended with: get_commit_by_prefix(), symbolic ref methods
        repositories.py      # Extended with: prefix query ABC, ref get/set methods
```

### Pattern 1: SDK-first, CLI-as-presentation
**What:** All business logic lives in `Tract` methods and `operations/` modules. CLI commands are thin wrappers that parse args, call SDK methods, and format output.
**When to use:** Always. This is the fundamental architecture decision.
**Example:**
```python
# CLI command (thin wrapper)
@cli.command()
@click.argument("target", required=False)
@click.option("--limit", "-n", default=20, type=int)
@click.pass_obj
def log(tract_obj, target, limit):
    """Show commit history."""
    entries = tract_obj.log(limit=limit)
    format_log(entries, verbose=False)

# SDK method (all logic)
def log(self, limit: int = 20, *, op_filter: CommitOperation | None = None) -> list[CommitInfo]:
    ...
```

### Pattern 2: Click Group with Tract Context Object
**What:** The top-level Click group opens a Tract instance and stores it in `ctx.obj`. Subcommands access it via `@click.pass_obj`.
**When to use:** Every CLI command needs a Tract instance.
**Example:**
```python
@click.group()
@click.option("--db", default=".tract.db", help="Database path")
@click.pass_context
def cli(ctx, db):
    """Tract: Git-like version control for LLM context windows."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db

# Lazy open: commands open the Tract when needed
def _get_tract(ctx) -> Tract:
    if "tract" not in ctx.obj:
        ctx.obj["tract"] = Tract.open(ctx.obj["db_path"])
    return ctx.obj["tract"]
```

### Pattern 3: Structured Diff Result (Not Raw Text)
**What:** The SDK returns a structured `DiffResult` dataclass, not raw unified diff text. The CLI formats it.
**When to use:** `tract.diff(commit_a, commit_b)` returns structured data; CLI renders it.
**Example:**
```python
@dataclass
class MessageDiff:
    """Diff for a single message position."""
    index: int
    status: Literal["added", "removed", "modified", "unchanged"]
    role_change: tuple[str, str] | None  # (old_role, new_role) or None
    content_diff: list[str]  # unified diff lines
    token_delta: int
    content_type_change: tuple[str, str] | None  # (old_type, new_type) or None

@dataclass
class DiffResult:
    """Structured diff between two commits."""
    commit_a: str  # hash
    commit_b: str  # hash
    message_diffs: list[MessageDiff]
    total_token_delta: int
    generation_config_changes: dict[str, tuple]  # field -> (old, new)
```

### Pattern 4: Symbolic Ref Resolution for HEAD
**What:** HEAD is a symbolic ref (points to `refs/heads/main`) when attached, or a direct ref (points to commit hash) when detached. All HEAD reads resolve through this.
**When to use:** Every operation that reads or writes HEAD.
**Example:**
```python
# In SqliteRefRepository:
def get_head(self, tract_id: str) -> str | None:
    """Get HEAD commit hash, resolving symbolic refs."""
    ref = self._get_ref_row(tract_id, "HEAD")
    if ref is None:
        return None
    # If symbolic ref, follow the chain
    if ref.symbolic_target:
        target_ref = self._get_ref_row(tract_id, ref.symbolic_target)
        return target_ref.commit_hash if target_ref else None
    return ref.commit_hash

def is_detached(self, tract_id: str) -> bool:
    """Check if HEAD is detached (points directly to commit, not branch)."""
    ref = self._get_ref_row(tract_id, "HEAD")
    return ref is not None and ref.symbolic_target is None

def attach_head(self, tract_id: str, branch_name: str) -> None:
    """Set HEAD as symbolic ref to a branch."""
    ref_name = f"refs/heads/{branch_name}"
    ref = self._get_ref_row(tract_id, "HEAD")
    if ref is None:
        self._session.add(RefRow(
            tract_id=tract_id, ref_name="HEAD",
            commit_hash=None, symbolic_target=ref_name,
        ))
    else:
        ref.symbolic_target = ref_name
        ref.commit_hash = None
    self._session.flush()

def detach_head(self, tract_id: str, commit_hash: str) -> None:
    """Set HEAD as direct ref to a commit hash (detached)."""
    ref = self._get_ref_row(tract_id, "HEAD")
    if ref is None:
        self._session.add(RefRow(
            tract_id=tract_id, ref_name="HEAD",
            commit_hash=commit_hash, symbolic_target=None,
        ))
    else:
        ref.symbolic_target = None
        ref.commit_hash = commit_hash
    self._session.flush()
```

### Pattern 5: Lazy Import Guard for CLI Dependencies
**What:** The `tract.cli` module catches ImportError for Click/Rich and provides a clear error message.
**When to use:** At CLI module import time.
**Example:**
```python
# src/tract/cli/__init__.py
try:
    import click
    import rich
except ImportError:
    raise ImportError(
        "CLI dependencies not installed. Install with: pip install tract[cli]"
    ) from None

# ... rest of CLI setup
```

### Pattern 6: Short Hash Prefix Matching
**What:** Accept unique hash prefixes (min 4 chars) to identify commits, like git.
**When to use:** Any user-facing commit hash input (CLI args, SDK methods).
**Example:**
```python
# In SqliteCommitRepository:
def get_by_prefix(self, prefix: str, tract_id: str | None = None) -> CommitRow | None:
    """Find commit by hash prefix. Raises AmbiguousPrefixError if multiple matches."""
    if len(prefix) < 4:
        raise ValueError("Commit hash prefix must be at least 4 characters")
    stmt = select(CommitRow).where(CommitRow.commit_hash.startswith(prefix))
    if tract_id:
        stmt = stmt.where(CommitRow.tract_id == tract_id)
    matches = list(self._session.execute(stmt).scalars().all())
    if len(matches) == 0:
        return None
    if len(matches) == 1:
        return matches[0]
    raise AmbiguousPrefixError(prefix, [m.commit_hash for m in matches[:5]])
```

### Anti-Patterns to Avoid
- **CLI logic in SDK methods:** SDK returns data structures; CLI formats them. Never have SDK methods return formatted strings.
- **Direct database access in CLI:** CLI always goes through Tract facade; never imports storage or engine modules.
- **Eager import of Click/Rich in SDK modules:** CLI dependencies must be optional; importing `tract` must never require Click/Rich.
- **Mutable HEAD during detached state:** Committing in detached HEAD must raise `DetachedHeadError`, not silently advance HEAD.
- **Full-chain walk for log with --limit:** The existing `get_ancestors(limit=N)` already short-circuits; don't fetch all then truncate.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Text diffing | Custom diff algorithm | `difflib.unified_diff()` | Handles edge cases (empty lines, binary-like content, context windows) correctly |
| Terminal width detection | Manual `os.get_terminal_size()` | Rich Console auto-detection | Handles pipes, redirects, fallback widths, environment variables |
| TTY detection for color | `sys.stdout.isatty()` checks | Rich Console auto-detection | Rich handles NO_COLOR, FORCE_COLOR, TERM=dumb, pipe detection |
| Colored diff output | Manual ANSI escape codes | Rich `Syntax` with "diff" lexer | Pygments diff lexer correctly colors +/- lines, headers, context |
| Progress bar for token budget | Custom `[===>....]` string | Rich Text with styled characters or Rich BarColumn | Rich handles terminal width, Unicode vs ASCII fallback |
| CLI argument parsing | Manual sys.argv parsing | Click decorators | Click handles type validation, help generation, error messages |
| CLI test harness | subprocess-based tests | `click.testing.CliRunner` | In-process testing, captures output, exception info, no subprocess overhead |
| Hash prefix matching SQL | Python-side filtering | SQLAlchemy `startswith()` (SQL LIKE) | Database-side filtering is O(log n) with index; Python-side is O(n) |

**Key insight:** The CLI layer should be entirely presentation logic. Rich and Click handle all the terminal complexity; the SDK handles all the business logic. The CLI is glue code.

## Common Pitfalls

### Pitfall 1: Circular Import with CLI Module
**What goes wrong:** Importing `tract.cli` at module level in `tract/__init__.py` would force Click/Rich as hard dependencies.
**Why it happens:** Natural instinct to export CLI in the package init.
**How to avoid:** CLI module is only imported when the `tract` console script entry point is invoked. Never import `tract.cli` from `tract/__init__.py` or any SDK module. Use the `[project.scripts]` entry point to point directly at the CLI group.
**Warning signs:** `ImportError: No module named 'click'` when just doing `import tract`.

### Pitfall 2: Breaking Existing HEAD Behavior During Symbolic Ref Migration
**What goes wrong:** The current `update_head()` stores commit_hash directly on the HEAD RefRow. Converting to symbolic refs could break existing behavior where HEAD is used.
**Why it happens:** The `get_head()` method currently reads `ref.commit_hash` directly. After migration, it needs to resolve through `symbolic_target`.
**How to avoid:**
1. Add a migration path: first commit in a tract initializes symbolic HEAD (HEAD -> refs/heads/main).
2. Make `get_head()` handle both old-style (direct) and new-style (symbolic) refs gracefully.
3. Keep `update_head()` working for backward compat; add `attach_head()`/`detach_head()` as new methods.
4. All 267 existing tests must pass without modification after the refactor.
**Warning signs:** Existing tests fail when HEAD resolution changes.

### Pitfall 3: Diff on EDIT Commits Without Auto-Resolution
**What goes wrong:** User does `tract diff <edit-commit-hash>` and gets confused because the EDIT commit's content doesn't make sense in isolation.
**Why it happens:** EDIT commits replace another commit's content; diffing an EDIT against its parent shows the new content vs the previous commit, not the edit delta.
**How to avoid:** CONTEXT.md decision: "EDIT commits auto-resolve: tract diff <edit-commit> automatically finds and diffs against the original target." Implement this by checking if commit is an EDIT, then using `response_to` to find the target, and diffing target's original content vs edit's new content.
**Warning signs:** Diff output that doesn't show what the edit actually changed.

### Pitfall 4: Token Count Ambiguity in Log vs Status
**What goes wrong:** Log shows per-commit raw token counts (from blob), but status shows compiled total (from compile()). Users get confused when they don't add up.
**Why it happens:** Raw token counts are per-content-piece; compiled token count includes message overhead and edit resolution.
**How to avoid:** CONTEXT.md decision: "Per-commit token counts shown [in log]; cumulative is available via tract status which uses compile(); log stays fast." Make this explicit in CLI output labels: log shows "tokens: 42" (per-commit), status shows "Total tokens: 1,234 (compiled)".
**Warning signs:** User confusion about why sum of log tokens != status total.

### Pitfall 5: `difflib.unified_diff` Returns Iterator, Not String
**What goes wrong:** Treating `unified_diff()` return value as a string. It returns a generator of lines.
**Why it happens:** Common mistake with Python generators.
**How to avoid:** Always `list()` or `"\n".join()` the result. Also note: lines already have trailing newlines (set `lineterm=""` to avoid double newlines).
**Warning signs:** Empty output or `<generator object>` in diff display.

### Pitfall 6: PREV_HEAD vs ORIG_HEAD Confusion
**What goes wrong:** Mixing up the two refs. PREV_HEAD is for `checkout -`; ORIG_HEAD is for reset recovery.
**Why it happens:** Both store "where HEAD was before."
**How to avoid:** Clear naming and separate update paths. Checkout updates PREV_HEAD; reset updates ORIG_HEAD. Both update PREV_HEAD.
**Warning signs:** `tract checkout -` goes to wrong place after a reset.

### Pitfall 7: Click CliRunner and File-Backed SQLite Isolation
**What goes wrong:** CLI tests using CliRunner with file-backed databases leave temp files or have path issues.
**Why it happens:** CliRunner doesn't automatically manage temp directories.
**How to avoid:** Use `runner.isolated_filesystem()` or pytest's `tmp_path` fixture. For most tests, use `:memory:` databases where possible. For persistence tests, use `tmp_path`.
**Warning signs:** Test pollution between CLI test runs; "database is locked" errors.

## Code Examples

Verified patterns from official sources and stdlib:

### difflib.unified_diff for Content Comparison
```python
# Source: Python stdlib docs (https://docs.python.org/3/library/difflib.html)
import difflib
import json

def diff_content(old_text: str, new_text: str,
                 from_label: str = "a", to_label: str = "b") -> list[str]:
    """Generate unified diff lines between two content strings."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    return list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=from_label, tofile=to_label,
        lineterm="",  # avoid double newlines
    ))

def serialize_content_for_diff(content_data: dict) -> str:
    """Serialize any content type to diffable text."""
    content_type = content_data.get("content_type", "unknown")
    if content_type in ("tool_io", "freeform"):
        # Pretty-print structured content for key-level diff
        payload = content_data.get("payload", {})
        return json.dumps(payload, indent=2, sort_keys=True)
    if "text" in content_data:
        return content_data["text"]
    if "content" in content_data:
        return content_data["content"]
    return json.dumps(content_data, indent=2, sort_keys=True)
```

### Click Group with Context Pattern
```python
# Source: Click docs (https://click.palletsprojects.com/en/stable/complex/)
import click

@click.group()
@click.option("--db", default=".tract.db", envvar="TRACT_DB",
              help="Path to tract database.")
@click.pass_context
def cli(ctx, db):
    """Tract: Git-like version control for LLM context windows."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db

@cli.command()
@click.option("-n", "--limit", default=20, type=int, help="Max commits to show.")
@click.option("-v", "--verbose", is_flag=True, help="Detailed output.")
@click.option("--op", type=click.Choice(["append", "edit"]), help="Filter by operation.")
@click.pass_context
def log(ctx, limit, verbose, op):
    """Show commit history."""
    from tract.cli.formatting import format_log
    tract = _get_tract(ctx)
    entries = tract.log(limit=limit)
    format_log(entries, verbose=verbose, op_filter=op)
```

### Rich TTY-Aware Console Setup
```python
# Source: Rich docs (https://rich.readthedocs.io/en/latest/console.html)
import sys
from rich.console import Console

def get_console() -> Console:
    """Create a Rich Console that degrades gracefully when piped."""
    # Rich auto-detects TTY. When piped, it strips ANSI codes.
    # force_terminal=False is the default (auto-detect).
    return Console()

def format_diff_output(diff_lines: list[str], console: Console) -> None:
    """Render unified diff with syntax highlighting."""
    if not diff_lines:
        console.print("[dim]No differences[/dim]")
        return
    from rich.syntax import Syntax
    diff_text = "\n".join(diff_lines)
    syntax = Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
    console.print(syntax)
```

### Rich Table for Log Output
```python
# Source: Rich docs (https://rich.readthedocs.io/en/latest/tables.html)
from rich.table import Table
from rich.console import Console

def format_log_compact(entries, console: Console) -> None:
    """Render compact log as a Rich table."""
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Hash", style="yellow", width=8, no_wrap=True)
    table.add_column("Time", style="dim", width=19)
    table.add_column("Op", width=6)
    table.add_column("Tokens", justify="right", width=7)
    table.add_column("Message", overflow="ellipsis")

    for entry in entries:
        table.add_row(
            entry.commit_hash[:7],
            entry.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            entry.operation.value,
            str(entry.token_count),
            entry.message or "",
        )
    console.print(table)
```

### Token Budget Progress Bar (Static)
```python
# Custom pattern using Rich Text for static bar display
from rich.text import Text
from rich.console import Console

def format_token_budget(current: int, max_tokens: int | None, console: Console) -> None:
    """Display token budget as a static progress bar."""
    if max_tokens is None:
        console.print(f"Tokens: {current:,} (no budget set)")
        return

    pct = min(current / max_tokens, 1.0)
    bar_width = 30
    filled = int(bar_width * pct)
    bar = "=" * filled + ">" + "." * (bar_width - filled - 1) if pct < 1.0 else "=" * bar_width

    style = "green" if pct < 0.7 else "yellow" if pct < 0.9 else "red"
    text = Text()
    text.append("[")
    text.append(bar, style=style)
    text.append(f"] {pct:.0%} of {max_tokens:,}")
    console.print(text)
```

### Click CliRunner Test Pattern
```python
# Source: Click docs (https://click.palletsprojects.com/en/stable/testing/)
from click.testing import CliRunner
from tract.cli import cli

def test_log_default():
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Setup: create a tract with commits via SDK
        result = runner.invoke(cli, ["--db", "test.db", "log"])
        assert result.exit_code == 0
        assert "No commits" in result.output or "commit" in result.output.lower()

def test_log_with_limit():
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", ":memory:", "log", "-n", "5"])
    assert result.exit_code == 0

def test_reset_hard_requires_force():
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", "test.db", "reset", "--hard", "abc1234"])
    assert result.exit_code != 0
    assert "--force" in result.output
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `update_head()` stores commit_hash directly | Symbolic ref: HEAD -> refs/heads/main (attached) or HEAD -> commit_hash (detached) | Phase 2 (now) | Enables checkout, detached HEAD, foundation for Phase 3 branching |
| No prefix matching on commit hashes | `get_by_prefix()` with SQL LIKE query, min 4 chars | Phase 2 (now) | User-friendly commit references |
| `Tract.log()` returns list of CommitInfo | Extended with op_filter; new `status()`, `diff()`, `reset()`, `checkout()` methods | Phase 2 (now) | Full history navigation |
| No CLI | Click + Rich CLI via `pip install tract[cli]` | Phase 2 (now) | Human-facing debugging interface |

**Deprecated/outdated:**
- `update_head()`: Will still work but should be used only by the commit engine internally. New code should use `attach_head()` / `detach_head()` for explicit intent.

## Open Questions

Things that couldn't be fully resolved:

1. **Exact compact log format layout**
   - What we know: One line per commit. Hash (short), timestamp, operation, content preview (truncated). CONTEXT.md says this is Claude's discretion.
   - What's unclear: Exact column widths, whether to use Rich Table or plain text for compact mode.
   - Recommendation: Use Rich Table with no borders (box=None) for compact. Gives automatic column alignment and terminal width handling. 8-char hash, ISO timestamp, op, tokens, truncated message.

2. **How to handle `tract checkout -` when PREV_HEAD doesn't exist**
   - What we know: PREV_HEAD ref should be set by every checkout/reset before moving HEAD.
   - What's unclear: What happens on first checkout when no PREV_HEAD exists yet?
   - Recommendation: Error message: "No previous position to return to. PREV_HEAD not set."

3. **Progress bar rendering for token budget (Claude's discretion)**
   - What we know: CONTEXT.md says "progress bar or raw count" based on whether budget is configured.
   - What's unclear: Whether to use Rich Progress (animated) or a static text-based bar.
   - Recommendation: Static text-based bar using Rich Text styling (not animated Progress). Status is a one-shot display, not a long-running task. Pattern: `[=========>......] 67% of 128k` with green/yellow/red coloring based on percentage.

4. **How CLI discovers tract_id for multi-tract databases**
   - What we know: Current Tract.open() generates a random tract_id if not provided.
   - What's unclear: CLI needs to know which tract to operate on.
   - Recommendation: For Phase 2 (single-tract use case), use a default convention: store tract_id in a `.tract` metadata file or use a `--tract-id` option. Simplest: default to the most recently created tract, or require explicit `--tract-id` if multiple exist. This can be refined in later phases.

5. **Rich formatting degradation specifics (Claude's discretion)**
   - What we know: Rich auto-strips ANSI when not writing to TTY. Respects NO_COLOR.
   - What's unclear: Should tables become plain text when piped, or simplified format?
   - Recommendation: Let Rich handle it automatically. Rich Console with default settings strips escape codes when piped. Tables degrade to space-separated columns. Diff output becomes plain unified diff text. No custom logic needed.

## Sources

### Primary (HIGH confidence)
- Python difflib documentation (https://docs.python.org/3/library/difflib.html) - unified_diff API, line-level diff behavior
- Click 8.3.x documentation (https://click.palletsprojects.com/) - groups, context, testing, entry points
- Rich 14.x documentation (https://rich.readthedocs.io/) - Console TTY detection, Table API, Syntax highlighting, Text styling
- Existing codebase: `src/tract/storage/schema.py` - RefRow.symbolic_target column already exists
- Existing codebase: `src/tract/storage/sqlite.py` - SqliteRefRepository already has get_head, update_head, get_branch, set_branch
- Existing codebase: `src/tract/tract.py` - Tract.log() already exists with basic chain walk

### Secondary (MEDIUM confidence)
- Click PyPI page - version 8.3.1 latest (Nov 2025)
- Rich PyPI page - version 14.3.2 latest (Feb 2026)
- Click complex application docs - ctx.obj pattern for passing state to subcommands
- Rich Syntax class with Pygments "diff" lexer for colored diff output

### Tertiary (LOW confidence)
- Click vs Typer comparisons - Typer builds on Click but adds type-hint syntax; not needed for this simple CLI
- Static progress bar rendering - no official Rich pattern for this; custom implementation with Rich Text

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Click and Rich are explicitly named in CONTEXT.md decisions; difflib is stdlib
- Architecture: HIGH - SDK-first pattern is well-established; existing codebase provides clear extension points
- Pitfalls: HIGH - Based on direct analysis of existing codebase (RefRow.symbolic_target, current get_head/update_head behavior, content type serialization)
- CLI patterns: HIGH - Click and Rich documentation is authoritative and verified via WebFetch
- Diff implementation: HIGH - difflib.unified_diff is stdlib with stable API; content serialization patterns come from existing compiler code

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days - stable libraries, no fast-moving concerns)
