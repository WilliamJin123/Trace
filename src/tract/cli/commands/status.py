"""tract status -- show current tract status."""

from __future__ import annotations

import click

from tract.cli.formatting import format_status


@click.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current HEAD position, branch, token usage, and recent commits."""
    from tract.cli import _tract_session

    with _tract_session(ctx) as (t, console):
        info = t.status()
        format_status(info, console)
