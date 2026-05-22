"""Docspatch CLI — entry point and command registration for the `dp` command."""

from collections.abc import Callable
from pathlib import Path

import typer

from docspatch.commands import cleanup, config, docs, init
from docspatch.ui.console import err_console
from docspatch.utils.errors import EXIT_INTERNAL, DocspatchError
from docspatch.utils.logging import configure_logging, get_logger

log = get_logger("cli")

app = typer.Typer(
    name="dp",
    help="AI-powered documentation for Python projects.",
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)
config_app = typer.Typer(help="View or edit docspatch config.")
app.add_typer(config_app, name="config")

DEBUG_OPTION = typer.Option(
    False, "--debug", help="Trace every step, show error context, and print full tracebacks."
)
RECONFIGURE_OPTION = typer.Option(
    False,
    "--reconfigure",
    help="Re-prompt every field even if already set. Per-provider api keys retained.",
)


def invoke_command(fn: Callable[..., None], debug: bool, name: str = "command") -> None:
    """Run a command with central logging + error handling.

    - DocspatchError: prints `[code] message` + `hint`, exits with the code
      mapped to the error class. With `--debug` it also shows the context dict
      and re-raises for a full traceback.
    - KeyboardInterrupt: prints cancellation, exits 130.
    - Any other exception is an internal bug: generic error, exit 3.
    """
    configure_logging(debug)
    log.debug("running command: %s", name)
    try:
        fn()
    except DocspatchError as e:
        log.debug("command %s failed: %s", name, e.code)
        err_console.print(e.render(debug=debug))
        if debug:
            raise
        raise typer.Exit(e.exit_code) from None
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(130) from None
    except typer.Exit:
        raise
    except Exception as e:
        if debug:
            raise
        err_console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        err_console.print("[yellow]Hint:[/yellow] re-run with --debug for the full traceback.")
        raise typer.Exit(EXIT_INTERNAL) from None
    log.debug("command %s finished", name)


@app.command("init")
def init_cmd(reconfigure: bool = RECONFIGURE_OPTION, debug: bool = DEBUG_OPTION) -> None:
    """Initialise docspatch in this repo."""
    invoke_command(lambda: init.run(reconfigure=reconfigure), debug, "init")


@app.command("docs")
def docs_cmd(
    paths: list[Path] = docs.PATHS_ARG,
    check: bool = docs.CHECK_OPTION,
    update: bool = docs.UPDATE_OPTION,
    remarks: str | None = docs.REMARKS_OPTION,
    resume: bool = docs.RESUME_OPTION,
    no_ignore: bool = docs.NO_IGNORE_OPTION,
    debug: bool = DEBUG_OPTION,
) -> None:
    """Generate documentation for undocumented functions in files or directories.

    Examples:
        dp docs                     document the whole repo
        dp docs src/                document everything under src/
        dp docs src/app.py          document a single file
        dp docs --check src/        preview what needs docs, write nothing
        dp docs --resume           continue the most recent interrupted run
    """
    flags = docs.RunFlags(
        paths=tuple(paths or ()),
        check=check,
        update=update,
        remarks=remarks,
        resume=resume,
        no_ignore=no_ignore,
    )
    invoke_command(lambda: docs.run(flags), debug, "docs")


@app.command("cleanup")
def cleanup_cmd(debug: bool = DEBUG_OPTION) -> None:
    """Interactively remove docspatch artefacts."""
    invoke_command(cleanup.run, debug, "cleanup")


@config_app.callback(invoke_without_command=True)
def config_cb(ctx: typer.Context, debug: bool = DEBUG_OPTION) -> None:
    """Show merged config when called bare; subcommands edit individual keys."""
    if ctx.invoked_subcommand is None:
        invoke_command(config.run, debug, "config")


@config_app.command("set")
def config_set(key: str, value: str, debug: bool = DEBUG_OPTION) -> None:
    """Set a single config key (scope inferred from key)."""
    invoke_command(lambda: config.run_set(key, value), debug, "config set")
