"""ASCII welcome banner shown at the top of ``dp init`` and embedded in the README."""

from importlib.metadata import PackageNotFoundError, version

from docspatch.ui.console import console

# ANSI Shadow rendering of "docspatch"; kept as a literal so no figlet dependency.
ART = r"""
██████╗  ██████╗  ██████╗███████╗██████╗  █████╗ ████████╗ ██████╗██╗  ██╗
██╔══██╗██╔═══██╗██╔════╝██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██║  ██║
██║  ██║██║   ██║██║     ███████╗██████╔╝███████║   ██║   ██║     ███████║
██║  ██║██║   ██║██║     ╚════██║██╔═══╝ ██╔══██║   ██║   ██║     ██╔══██║
██████╔╝╚██████╔╝╚██████╗███████║██║     ██║  ██║   ██║   ╚██████╗██║  ██║
╚═════╝  ╚═════╝  ╚═════╝╚══════╝╚═╝     ╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝"""

TAGLINE = "AI-powered documentation for Python"
ISSUES_URL = "https://github.com/grimmy-dev/docspatch_v2/issues"
AUTHOR = "grimmy_dev"


def _version() -> str:
    """Return the installed package version, or a placeholder when not installed."""
    try:
        return version("docspatch")
    except PackageNotFoundError:
        return "0.0.0"


def render_banner() -> None:
    """Print the docspatch ASCII banner with version, author, and a clickable issue link."""
    console.print(f"[bold cyan]{ART}[/bold cyan]")
    console.print(f"  [dim]{TAGLINE}  ·  v{_version()}  ·  by {AUTHOR}[/dim]")
    console.print(f"  [dim]Report an issue:[/dim] [link={ISSUES_URL}]{ISSUES_URL}[/link]\n")
