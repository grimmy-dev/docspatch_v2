"""dp config + dp cleanup behavior tests — no filesystem side effects on real home dir."""

from unittest.mock import MagicMock

from typer.testing import CliRunner

from docspatch.cli import app
from docspatch.types.config import DocspatchConfig, ScopedValue

runner = CliRunner()


def make_config(
    provider: str | None = None,
    api_key: str | None = None,
    generator_model: str | None = None,
    scope: str = "default",
) -> DocspatchConfig:
    return DocspatchConfig(
        provider=ScopedValue(provider, scope),
        api_key=ScopedValue(api_key, scope),
        generator_model=ScopedValue(generator_model, scope),
        scout_model=ScopedValue("claude-haiku-4-5-20251001", "default"),
        tone=ScopedValue("professional", "default"),
        batch_token_limit=ScopedValue(6000, "default"),
    )


# --- dp config ---


def test_config_shows_all_keys(monkeypatch, tmp_path):
    monkeypatch.setattr("docspatch.commands.config.load_config", lambda **_: make_config())
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    for key in ("provider", "api_key", "generator_model", "scout_model", "tone", "batch_token_limit"):
        assert key in result.output


def test_config_shows_scope_labels(monkeypatch):
    cfg = make_config(provider="anthropic", api_key="sk-ant-abc", scope="global")
    monkeypatch.setattr("docspatch.commands.config.load_config", lambda **_: cfg)
    result = runner.invoke(app, ["config"])
    assert "global" in result.output


def test_config_masks_api_key(monkeypatch):
    cfg = make_config(api_key="sk-ant-api03-supersecret")
    monkeypatch.setattr("docspatch.commands.config.load_config", lambda **_: cfg)
    result = runner.invoke(app, ["config"])
    assert "supersecret" not in result.output
    assert "••••" in result.output


def test_config_unconfigured_repo_shows_only_defaults(monkeypatch):
    monkeypatch.setattr("docspatch.commands.config.load_config", lambda **_: make_config())
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "default" in result.output
    assert "repo" not in result.output
    assert "global" not in result.output


def test_config_shows_repo_scope_when_set(monkeypatch):
    cfg = make_config(generator_model="claude-sonnet-4-6", scope="repo")
    monkeypatch.setattr("docspatch.commands.config.load_config", lambda **_: cfg)
    result = runner.invoke(app, ["config"])
    assert "repo" in result.output


# --- dp cleanup ---


def mock_questionary(monkeypatch, selected, confirmed=True):
    checkbox = MagicMock(return_value=MagicMock(ask=MagicMock(return_value=selected)))
    confirm = MagicMock(return_value=MagicMock(ask=MagicMock(return_value=confirmed)))
    monkeypatch.setattr("docspatch.commands.cleanup.questionary.checkbox", checkbox)
    monkeypatch.setattr("docspatch.commands.cleanup.questionary.confirm", confirm)
    return checkbox, confirm


def test_cleanup_no_selection_exits_cleanly(monkeypatch):
    mock_questionary(monkeypatch, selected=[])
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0


def test_cleanup_confirmation_required(monkeypatch):
    checkbox, confirm = mock_questionary(monkeypatch, selected=["something"], confirmed=False)
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0
    confirm.return_value.ask.assert_called_once()


def test_cleanup_deletes_selected_file(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem
    target = tmp_path / "config.toml"
    target.write_text("[config]\n")
    item = CleanupItem(label="Repo config", path=target)

    mock_questionary(monkeypatch, selected=[item], confirmed=True)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    runner.invoke(app, ["cleanup"])
    assert not target.exists()


def test_cleanup_deletes_selected_directory(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "entry.gz").write_bytes(b"data")
    item = CleanupItem(label="Scout cache", path=cache_dir)

    mock_questionary(monkeypatch, selected=[item], confirmed=True)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    runner.invoke(app, ["cleanup"])
    assert not cache_dir.exists()


def test_cleanup_no_deletion_when_confirm_false(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem
    target = tmp_path / "config.toml"
    target.write_text("[config]\n")
    item = CleanupItem(label="Repo config", path=target)

    mock_questionary(monkeypatch, selected=[item], confirmed=False)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    runner.invoke(app, ["cleanup"])
    assert target.exists()


def test_cleanup_skips_nonexistent_path_with_info(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem
    missing = tmp_path / "ghost.toml"  # never created
    item = CleanupItem(label="Ghost config", path=missing)

    mock_questionary(monkeypatch, selected=[item], confirmed=True)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0
    assert not missing.exists()
    assert "not found" in result.output.lower()
    assert "not found" in result.output.lower() or "Ghost config" in result.output
