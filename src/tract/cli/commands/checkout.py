"""tract checkout -- switch to a commit or branch."""

from __future__ import annotations

import click

from tract.cli.formatting import format_short_hash


@click.command()
@click.argument("target")
@click.pass_context
def checkout(ctx: click.Context, target: str) -> None:
    """Checkout a commit or branch.

    TARGET can be a branch name, commit hash, hash prefix, or "-" to
    return to the previous position.

    Checking out a branch attaches HEAD (commits go to that branch).
    Checking out a commit detaches HEAD (read-only inspection).
    """
    from tract.cli import _tract_session

    with _tract_session(ctx) as (t, console):
        resolved = t.checkout(target)
        is_detached = t.is_detached
        if is_detached:
            console.print(
                f"HEAD detached at {format_short_hash(resolved)}"
            )
        else:
            branch = t.current_branch
            console.print(
                f"Switched to branch [green]{branch}[/green] "
                f"({format_short_hash(resolved)})"
            )
