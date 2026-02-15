"""tract switch -- switch to a branch (branch-only, unlike checkout)."""

from __future__ import annotations

import click

from tract.cli.formatting import format_error, get_console


@click.command()
@click.argument("target")
@click.pass_context
def switch(ctx: click.Context, target: str) -> None:
    """Switch to a branch.

    TARGET must be a branch name. Unlike checkout, this command will not
    silently detach HEAD on commit hashes.
    """
    from tract.cli import _get_tract
    from tract.exceptions import BranchNotFoundError

    console = get_console()
    try:
        t = _get_tract(ctx)
        try:
            commit_hash = t.switch(target)
            console.print(
                f"Switched to branch [green]{target}[/green] "
                f"at [yellow]{commit_hash[:8]}[/yellow]"
            )
        except BranchNotFoundError:
            # List available branches for a helpful error message
            branches = t.list_branches()
            branch_names = [b.name for b in branches]
            msg = f"Branch not found: {target}"
            if branch_names:
                msg += f". Available branches: {', '.join(branch_names)}"
            format_error(msg, console)
            raise SystemExit(1) from None
        finally:
            t.close()
    except SystemExit:
        raise
    except Exception as e:
        format_error(str(e), console)
        raise SystemExit(1) from None
