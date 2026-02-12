---
phase: 02-linear-history-cli
plan: 03
subsystem: cli
tags: [click, rich, cli, terminal, formatting]

# Dependency graph
requires:
  - phase: 02-linear-history-cli (02-01, 02-02)
    provides: "Navigation ops (reset, checkout) and read ops (log, status, diff) on Tract"
provides:
  - "CLI package with Click group and 5 terminal commands"
  - "Rich formatting helpers for log, status, diff output"
  - "pyproject.toml [cli] optional extra and entry point"
  - "Auto-discovery of tract_id from database"
  - "30 CLI tests via CliRunner"
affects: [phase-03-branching, phase-05-packaging]

# Tech tracking
tech-stack:
  added: ["click>=8.1,<9", "rich>=13.0,<15"]
  patterns: ["Click group with lazy import guard", "Rich TTY auto-detection for pipe degradation", "File-backed database in CLI tests"]

key-files:
  created:
    - "src/tract/cli/__init__.py"
    - "src/tract/cli/formatting.py"
    - "src/tract/cli/commands/__init__.py"
    - "src/tract/cli/commands/log.py"
    - "src/tract/cli/commands/status.py"
    - "src/tract/cli/commands/diff.py"
    - "src/tract/cli/commands/reset.py"
    - "src/tract/cli/commands/checkout.py"
    - "tests/test_cli.py"
  modified:
    - "pyproject.toml"

key-decisions:
  - "CLI module never imported from tract/__init__.py; only loaded via entry point"
  - "Auto-discovery queries refs table for single tract_id when --tract-id omitted"
  - "Token budget not persisted to DB, so CLI shows 'no budget set' by default"
  - "Click CliRunner tests use file-backed databases (not :memory:) since CLI opens own connection"
  - "--force guard on hard reset as safety mechanism"

patterns-established:
  - "CLI as thin presentation wrapper: all logic in SDK, CLI just formats and invokes"
  - "Rich Console auto-detects TTY for graceful pipe degradation (no ANSI when piped)"
  - "Click group with --db/--tract-id options passed via context object"

# Metrics
duration: 5min
completed: 2026-02-12
---

# Phase 2 Plan 3: CLI Layer Summary

**Click CLI with 5 commands (log, status, diff, reset, checkout), Rich terminal formatting, and optional [cli] dependency extra**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-12T18:09:50Z
- **Completed:** 2026-02-12T18:14:54Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- CLI package with Click group registering 5 subcommands
- Rich formatting for log (compact/verbose), status (with budget bar), diff (colored unified diff)
- pyproject.toml updated with `[cli]` optional extra and `tract` entry point
- 30 CLI tests passing via CliRunner with file-backed databases
- `import tract` works without click/rich installed (lazy import guard)

## Task Commits

Each task was committed atomically:

1. **Task 1: CLI package structure, Click group, formatting helpers, and pyproject.toml** - `23c94b2` (feat)
2. **Task 2: Five CLI commands + CLI tests** - `3379097` (test)

## Files Created/Modified
- `pyproject.toml` - Added [cli] optional extra, entry point, click/rich to dev deps
- `src/tract/cli/__init__.py` - Click group with --db/--tract-id, _get_tract(), _discover_tract()
- `src/tract/cli/formatting.py` - Rich formatting: format_log_compact/verbose, format_status, format_diff, format_error
- `src/tract/cli/commands/__init__.py` - Empty commands package
- `src/tract/cli/commands/log.py` - tract log with -n/--limit, -v/--verbose, --op filter
- `src/tract/cli/commands/status.py` - tract status showing HEAD, branch, tokens, recent commits
- `src/tract/cli/commands/diff.py` - tract diff with --stat, accepts commit_a/commit_b args
- `src/tract/cli/commands/reset.py` - tract reset with --soft/--hard and --force guard
- `src/tract/cli/commands/checkout.py` - tract checkout for branch/commit/"-"
- `tests/test_cli.py` - 30 tests covering all 5 commands and integration scenarios

## Decisions Made
- CLI module is never imported from tract/__init__.py (only loaded via entry point) to keep core package lightweight
- Auto-discovery of tract_id from database refs table when --tract-id not specified
- Token budget is not persisted to the database; CLI opens with default config showing "no budget set"
- CliRunner tests use file-backed databases because CLI opens its own DB connection separate from SDK setup
- --force flag required for hard reset as a safety guard (even though soft == hard in Trace)
- Click 8.3 removed mix_stderr parameter from CliRunner

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Click 8.3 CliRunner API change**
- **Found during:** Task 2 (CLI tests)
- **Issue:** `CliRunner(mix_stderr=False)` raises TypeError in Click 8.3 -- parameter was removed
- **Fix:** Changed to `CliRunner()` without the deprecated parameter
- **Files modified:** tests/test_cli.py
- **Verification:** All 30 tests pass
- **Committed in:** 3379097 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial API compatibility fix. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 complete: all 3 plans executed (navigation, read ops, CLI)
- CLI wraps all 5 SDK operations with proper formatting
- Ready for Phase 3 (branching) which will add branch-aware commands

---
*Phase: 02-linear-history-cli*
*Completed: 2026-02-12*
