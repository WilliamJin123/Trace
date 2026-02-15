"""tract branch -- list, create, and delete branches."""

from __future__ import annotations

import click

from tract.cli.formatting import format_branches, format_short_hash


@click.group(invoke_without_command=True)
@click.pass_context
def branch(ctx: click.Context) -> None:
    """Manage branches.

    With no subcommand, lists all branches with the current branch
    highlighted with a '*' marker (like git branch).
    """
    if ctx.invoked_subcommand is not None:
        return

    from tract.cli import _tract_session

    with _tract_session(ctx) as (t, console):
        branches = t.list_branches()
        format_branches(branches, console)


@branch.command("create")
@click.argument("name")
@click.option("--no-switch", is_flag=True, help="Create branch without switching to it.")
@click.option("--source", default=None, help="Commit hash to branch from (defaults to HEAD).")
@click.pass_context
def branch_create(ctx: click.Context, name: str, no_switch: bool, source: str | None) -> None:
    """Create a new branch.

    NAME is the new branch name. By default, switches to the new branch.
    """
    from tract.cli import _tract_session

    with _tract_session(ctx) as (t, console):
        commit_hash = t.branch(name, source=source, switch=not no_switch)
        console.print(f"Created branch [green]{name}[/green] at {format_short_hash(commit_hash)}")
        if not no_switch:
            console.print(f"Switched to branch [green]{name}[/green]")


@branch.command("delete")
@click.argument("name")
@click.option("--force", is_flag=True, help="Force delete even with unmerged commits.")
@click.pass_context
def branch_delete(ctx: click.Context, name: str, force: bool) -> None:
    """Delete a branch.

    NAME is the branch to delete. Cannot delete the current branch.
    """
    from tract.cli import _tract_session

    with _tract_session(ctx) as (t, console):
        t.delete_branch(name, force=force)
        console.print(f"Deleted branch [green]{name}[/green]")
