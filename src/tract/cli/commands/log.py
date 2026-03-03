"""tract log -- show commit history."""

from __future__ import annotations

import click

from tract.cli.formatting import format_log_compact, format_log_verbose


@click.command()
@click.option("-n", "--limit", default=20, type=click.IntRange(min=1), help="Maximum number of commits to show.")
@click.option("-v", "--verbose", is_flag=True, help="Show verbose commit details.")
@click.option("--op", "op_filter", default=None, type=click.Choice(["append", "edit"], case_sensitive=False), help="Filter by operation type.")
@click.option("--skipped", is_flag=True, help="Show only skipped commits (excluded from compile).")
@click.option("--pinned", is_flag=True, help="Show only pinned commits (always in compile).")
@click.pass_context
def log(ctx: click.Context, limit: int, verbose: bool, op_filter: str | None, skipped: bool, pinned: bool) -> None:
    """Show commit history from HEAD backward."""
    from tract.cli import _tract_session
    from tract.models.commit import CommitOperation

    with _tract_session(ctx) as (t, console):
        if skipped:
            entries = t.skipped(limit=limit)
        elif pinned:
            entries = t.pinned(limit=limit)
        else:
            op = CommitOperation(op_filter) if op_filter else None
            entries = t.log(limit=limit, op_filter=op)
        if verbose:
            format_log_verbose(entries, console)
        else:
            format_log_compact(entries, console)
