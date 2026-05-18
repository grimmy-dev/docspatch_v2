"""Docspatch CLI — entry point and command registration for the `dp` command."""

from collections.abc import Callable

import typer

from docspatch.commands import cache, cleanup, config, init
from docspatch.ui.console import console, err_console
from docspatch.utils.errors import DocspatchError

app = typer.Typer(name="dp", help="AI-powered documentation for Python projects.", rich_markup_mode="rich")
cache_app = typer.Typer(help="Cache management.")
config_app = typer.Typer(help="View or edit docspatch config.")
app.add_typer(cache_app, name="cache")
app.add_typer(config_app, name="config")

DEBUG_OPTION = typer.Option(False, "--debug", help="Show full traceback.")
RECONFIGURE_OPTION = typer.Option(
    False,
    "--reconfigure",
    help="Re-prompt every field even if already set. Per-provider api keys retained.",
)


def invoke_command(fn: Callable[..., None], debug: bool) -> None:
    """Run fn with central error handling.

    - DocspatchError: prints `message` + `hint`, exits 1.
    - KeyboardInterrupt: prints cancellation, exits 130.
    - Other exceptions: prints generic error + hint to re-run with --debug.
    - `--debug` re-raises everything for full traceback.
    """
    try:
        fn()
    except DocspatchError as e:
        if debug:
            raise
        err_console.print(e.render())
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(130) from None
    except Exception as e:
        if debug:
            raise
        err_console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        err_console.print("[yellow]Hint:[/yellow] re-run with --debug for the full traceback.")
        raise typer.Exit(1) from None


def stub_command() -> None:
    console.print("[dim]not yet implemented[/dim]")


@app.command("init")
def init_cmd(reconfigure: bool = RECONFIGURE_OPTION, debug: bool = DEBUG_OPTION) -> None:
    """Initialise docspatch in this repo."""
    invoke_command(lambda: init.run(reconfigure=reconfigure), debug)


@app.command()
def docs(debug: bool = DEBUG_OPTION) -> None:
    """Generate documentation for changed functions."""
    invoke_command(stub_command, debug)


@app.command()
def readme(debug: bool = DEBUG_OPTION) -> None:
    """Generate or update README."""
    invoke_command(stub_command, debug)


@app.command()
def clg(debug: bool = DEBUG_OPTION) -> None:
    """Generate or update CHANGELOG."""
    invoke_command(stub_command, debug)


@app.command("cleanup")
def cleanup_cmd(debug: bool = DEBUG_OPTION) -> None:
    """Interactively remove docspatch artefacts."""
    invoke_command(cleanup.run, debug)


@config_app.callback(invoke_without_command=True)
def config_cb(ctx: typer.Context, debug: bool = DEBUG_OPTION) -> None:
    """Show merged config when called bare; subcommands edit individual keys."""
    if ctx.invoked_subcommand is None:
        invoke_command(config.run, debug)


@config_app.command("set")
def config_set(key: str, value: str, debug: bool = DEBUG_OPTION) -> None:
    """Set a single config key (scope inferred from key)."""
    invoke_command(lambda: config.run_set(key, value), debug)


@cache_app.callback(invoke_without_command=True)
def cache_cb(ctx: typer.Context, debug: bool = DEBUG_OPTION) -> None:
    """Cache management subcommand."""
    if ctx.invoked_subcommand is None:
        invoke_command(stub_command, debug)


@cache_app.command("info")
def cache_info() -> None:
    """Show indexed file count, total cache size, and last-build date."""
    cache.run_info()
