"""tract reset -- move HEAD to a target commit."""

from __future__ import annotations

import click

from tract.cli.formatting import format_error, format_short_hash, get_console


@click.command()
@click.argument("target")
@click.option("--soft", "mode", flag_value="soft", default="soft", help="Soft reset (default).")
@click.option("--hard", "mode", flag_value="hard", help="Hard reset (same as soft in Trace; requires --force).")
@click.option("--force", is_flag=True, help="Required for --hard reset.")
@click.pass_context
def reset(ctx: click.Context, target: str, mode: str, force: bool) -> None:
    """Reset HEAD to TARGET commit.

    TARGET can be a commit hash, hash prefix (min 4 chars), or branch name.
    In Trace, soft and hard resets behave identically (no working tree).
    Hard reset requires --force as a safety guard.
    """
    from tract.cli import _tract_session

    # Force guard for hard reset (before opening tract)
    if mode == "hard" and not force:
        console = get_console()
        format_error("Hard reset requires --force flag.", console)
        raise SystemExit(1)

    with _tract_session(ctx) as (t, console):
        resolved = t.reset(target, mode=mode)
        console.print(f"HEAD is now at {format_short_hash(resolved)} ({mode} reset)")
