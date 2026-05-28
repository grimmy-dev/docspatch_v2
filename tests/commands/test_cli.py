"""CLI behavior tests: command registration, error handling, --debug."""

from typer.testing import CliRunner

from docspatch.cli import app

runner = CliRunner()

SUBCOMMANDS = ["init", "docs", "config", "cleanup"]


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    for cmd in SUBCOMMANDS:
        assert cmd in result.output


def test_help_hides_unimplemented_commands():
    """README/changelog/cache are not built yet — they must not appear in help."""
    result = runner.invoke(app, ["--help"])
    for cmd in ("readme", "clg", "cache"):
        assert cmd not in result.output


def test_init_command_wired(monkeypatch):
    called = []
    monkeypatch.setattr("docspatch.commands.init.run", lambda debug=False, **kw: called.append(True))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert called, "init.run was not called"


def test_debug_flag_accepted_without_error(monkeypatch):
    monkeypatch.setattr("docspatch.commands.cleanup.run", lambda *a, **kw: None)
    result = runner.invoke(app, ["cleanup", "--debug"])
    assert result.exit_code == 0


def test_docspatch_error_shows_code_and_hint(monkeypatch):
    """CLI handler renders `[code] message` + hint and exits with the mapped code."""
    from docspatch.utils.errors import ConfigError

    def boom(*a, **kw):
        raise ConfigError("something broke", "try this fix")

    monkeypatch.setattr("docspatch.commands.cleanup.run", boom)
    result = runner.invoke(app, ["cleanup"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "docspatch.config" in result.output
    assert "something broke" in result.output
    assert "try this fix" in result.output


def test_exit_code_reflects_error_class(monkeypatch):
    """A transient LLM error exits 2; an internal cache error exits 3."""
    from docspatch.utils.errors import CacheError, LLMError

    monkeypatch.setattr("docspatch.commands.cleanup.run", lambda *a, **kw: (_ for _ in ()).throw(LLMError("down")))
    assert runner.invoke(app, ["cleanup"]).exit_code == 2

    monkeypatch.setattr("docspatch.commands.cleanup.run", lambda *a, **kw: (_ for _ in ()).throw(CacheError("corrupt")))
    assert runner.invoke(app, ["cleanup"]).exit_code == 3


def test_unexpected_error_exits_three(monkeypatch):
    """A non-DocspatchError is an internal bug — exit 3."""
    monkeypatch.setattr("docspatch.commands.cleanup.run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("oops")))
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 3
    assert "Unexpected error" in result.output


def test_debug_flag_reraises_docspatch_error(monkeypatch):
    """--debug propagates the exception so the full traceback shows."""
    from docspatch.utils.errors import DocspatchError

    monkeypatch.setattr("docspatch.commands.cleanup.run", lambda *a, **kw: (_ for _ in ()).throw(DocspatchError("boom")))
    result = runner.invoke(app, ["cleanup", "--debug"])
    assert result.exit_code != 0
    assert isinstance(result.exception, DocspatchError)


def test_debug_flag_shows_error_context(monkeypatch):
    """--debug expands the context dict; without it the context stays hidden."""
    from docspatch.utils.errors import ConfigError

    def boom(*a, **kw):
        raise ConfigError("bad", "fix it", context={"path": "src/app.py"})

    monkeypatch.setattr("docspatch.commands.cleanup.run", boom)
    assert "src/app.py" not in runner.invoke(app, ["cleanup"]).output
    assert "src/app.py" in runner.invoke(app, ["cleanup", "--debug"]).output
