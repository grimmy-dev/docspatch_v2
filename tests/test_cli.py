"""CLI behavior tests for Slice 1."""

from typer.testing import CliRunner

from docspatch.cli import app

runner = CliRunner()

SUBCOMMANDS = ["init", "docs", "readme", "clg", "config", "cleanup", "cache"]
STUB_SUBCOMMANDS = ["docs", "readme", "clg", "cache"]


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    for cmd in SUBCOMMANDS:
        assert cmd in result.output


def test_stubs_print_not_implemented_and_exit_zero():
    for cmd in STUB_SUBCOMMANDS:
        result = runner.invoke(app, [cmd])
        assert result.exit_code == 0, f"{cmd} exited {result.exit_code}"
        assert "not yet implemented" in result.output, f"{cmd} missing stub message"


def test_init_command_wired_not_stub(monkeypatch):
    called = []
    monkeypatch.setattr("docspatch.commands.init.run", lambda debug=False, **kw: called.append(True))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert called, "init.run was not called"
    assert "not yet implemented" not in result.output


def test_debug_flag_accepted_without_error():
    for cmd in ["docs", "readme", "clg"]:
        result = runner.invoke(app, [cmd, "--debug"])
        assert result.exit_code == 0, f"{cmd} --debug exited {result.exit_code}"


def test_docspatch_error_caught_by_cli_handler(monkeypatch):
    """CLI handler catches DocspatchError, prints message+hint, exits 1."""
    import docspatch.cli as cli_module
    from docspatch.errors import DocspatchError

    def raising_stub(debug: bool = False):
        raise DocspatchError("something broke", "try this fix")

    monkeypatch.setattr(cli_module, "stub_command", raising_stub)

    result = runner.invoke(app, ["docs"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "something broke" in result.output
    assert "try this fix" in result.output


def test_debug_flag_reraises_docspatch_error(monkeypatch):
    """--debug causes DocspatchError to propagate instead of clean exit."""
    import docspatch.cli as cli_module
    from docspatch.errors import DocspatchError

    def raising_stub(debug: bool = False):
        raise DocspatchError("boom", "hint")

    monkeypatch.setattr(cli_module, "stub_command", raising_stub)

    result = runner.invoke(app, ["docs", "--debug"])
    assert result.exit_code != 0
    assert isinstance(result.exception, DocspatchError)


def test_init_docspatch_error_shows_clean_message(monkeypatch):
    """DocspatchError in init.run() shows message+hint, exits 1."""
    from docspatch.errors import ConfigError
    monkeypatch.setattr("docspatch.commands.init.run", lambda **kw: (_ for _ in ()).throw(ConfigError("bad key", "check it")))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1
    assert "bad key" in result.output
    assert "check it" in result.output
