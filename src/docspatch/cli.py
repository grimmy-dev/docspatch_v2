"""Docspatch CLI — entry point and command registration for the `dp` command."""

from collections.abc import Callable

import typer

from docspatch.commands import cache, cleanup, config, init
from docspatch.errors import DocspatchError
from docspatch.ui.console import console, err_console

app = typer.Typer(name="dp", help="AI-powered documentation for Python projects.", rich_markup_mode="rich")
cache_app = typer.Typer(help="Cache management.")
app.add_typer(cache_app, name="cache")

DEBUG_OPTION = typer.Option(False, "--debug", help="Show full traceback.")


def invoke_command(fn: Callable, debug: bool) -> None:
    """Run fn, catching DocspatchError. Re-raises on --debug; prints clean message otherwise."""
    try:
        fn()
    except DocspatchError as e:
        if debug:
            raise
        err_console.print(f"[bold red]Error:[/bold red] {e.message}")
        if e.hint:
            err_console.print(f"[yellow]Hint:[/yellow] {e.hint}")
        raise typer.Exit(1) from None


def stub_command() -> None:
    console.print("[dim]not yet implemented[/dim]")


@app.command("init")
def init_cmd(debug: bool = DEBUG_OPTION) -> None:
    """Initialise docspatch in this repo."""
    invoke_command(init.run, debug)


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


@app.command("config")
def config_cmd(debug: bool = DEBUG_OPTION) -> None:
    """Show merged config with scope labels."""
    invoke_command(config.run, debug)


@app.command("cleanup")
def cleanup_cmd(debug: bool = DEBUG_OPTION) -> None:
    """Interactively remove docspatch artefacts."""
    invoke_command(cleanup.run, debug)


@cache_app.callback(invoke_without_command=True)
def cache_cb(ctx: typer.Context, debug: bool = DEBUG_OPTION) -> None:
    """Cache management subcommand."""
    if ctx.invoked_subcommand is None:
        invoke_command(stub_command, debug)


@cache_app.command("info")
def cache_info() -> None:
    """Show indexed file count, total cache size, and last-build date."""
    cache.run_info()
