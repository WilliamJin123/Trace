"""tract merge -- merge a branch into the current branch."""

from __future__ import annotations

import click

from tract.cli.formatting import format_error, format_merge_result, get_console


@click.command()
@click.argument("source")
@click.option("--no-ff", is_flag=True, help="Always create a merge commit (no fast-forward).")
@click.option(
    "--strategy",
    type=click.Choice(["auto", "semantic"], case_sensitive=False),
    default="auto",
    help="Merge strategy (default: auto).",
)
@click.pass_context
def merge(ctx: click.Context, source: str, no_ff: bool, strategy: str) -> None:
    """Merge SOURCE branch into the current branch.

    SOURCE is the name of the branch to merge in.
    """
    from tract.cli import _get_tract
    from tract.exceptions import NothingToMergeError

    console = get_console()
    try:
        t = _get_tract(ctx)
        try:
            result = t.merge(source, no_ff=no_ff, strategy=strategy)
            format_merge_result(result, console)
        except NothingToMergeError:
            console.print("Already up to date.")
        finally:
            t.close()
    except SystemExit:
        raise
    except Exception as e:
        format_error(str(e), console)
        raise SystemExit(1) from None
