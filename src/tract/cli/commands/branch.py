"""tract branch -- list, create, and delete branches."""

from __future__ import annotations

import click

from tract.cli.formatting import format_branches, format_error, get_console


@click.group(invoke_without_command=True)
@click.pass_context
def branch(ctx: click.Context) -> None:
    """Manage branches.

    With no subcommand, lists all branches with the current branch
    highlighted with a '*' marker (like git branch).
    """
    if ctx.invoked_subcommand is not None:
        return

    from tract.cli import _get_tract

    console = get_console()
    try:
        t = _get_tract(ctx)
        try:
            branches = t.list_branches()
            format_branches(branches, console)
        finally:
            t.close()
    except SystemExit:
        raise
    except Exception as e:
        format_error(str(e), console)
        raise SystemExit(1) from None


@branch.command("create")
@click.argument("name")
@click.option("--no-switch", is_flag=True, help="Create branch without switching to it.")
@click.option("--source", default=None, help="Commit hash to branch from (defaults to HEAD).")
@click.pass_context
def branch_create(ctx: click.Context, name: str, no_switch: bool, source: str | None) -> None:
    """Create a new branch.

    NAME is the new branch name. By default, switches to the new branch.
    """
    from tract.cli import _get_tract

    console = get_console()
    try:
        t = _get_tract(ctx)
        try:
            commit_hash = t.branch(name, source=source, switch=not no_switch)
            console.print(f"Created branch [green]{name}[/green] at [yellow]{commit_hash[:8]}[/yellow]")
            if not no_switch:
                console.print(f"Switched to branch [green]{name}[/green]")
        finally:
            t.close()
    except SystemExit:
        raise
    except Exception as e:
        format_error(str(e), console)
        raise SystemExit(1) from None


@branch.command("delete")
@click.argument("name")
@click.option("--force", is_flag=True, help="Force delete even with unmerged commits.")
@click.pass_context
def branch_delete(ctx: click.Context, name: str, force: bool) -> None:
    """Delete a branch.

    NAME is the branch to delete. Cannot delete the current branch.
    """
    from tract.cli import _get_tract

    console = get_console()
    try:
        t = _get_tract(ctx)
        try:
            t.delete_branch(name, force=force)
            console.print(f"Deleted branch [green]{name}[/green]")
        finally:
            t.close()
    except SystemExit:
        raise
    except Exception as e:
        format_error(str(e), console)
        raise SystemExit(1) from None
