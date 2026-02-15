"""tract switch -- switch to a branch (branch-only, unlike checkout)."""

from __future__ import annotations

import click

from tract.cli.formatting import format_error, format_short_hash


@click.command()
@click.argument("target")
@click.pass_context
def switch(ctx: click.Context, target: str) -> None:
    """Switch to a branch.

    TARGET must be a branch name. Unlike checkout, this command will not
    silently detach HEAD on commit hashes.
    """
    from tract.cli import _tract_session
    from tract.exceptions import BranchNotFoundError

    with _tract_session(ctx) as (t, console):
        try:
            commit_hash = t.switch(target)
            console.print(
                f"Switched to branch [green]{target}[/green] "
                f"at {format_short_hash(commit_hash)}"
            )
        except BranchNotFoundError:
            branches = t.list_branches()
            branch_names = [b.name for b in branches]
            msg = f"Branch not found: {target}"
            if branch_names:
                msg += f". Available branches: {', '.join(branch_names)}"
            format_error(msg, console)
            raise SystemExit(1) from None
