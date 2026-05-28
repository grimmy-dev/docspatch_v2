"""dp config + dp cleanup behavior tests — no filesystem side effects on real home dir."""

from typer.testing import CliRunner

from docspatch.cli import app
from docspatch.schemas import DocspatchConfig, Scope, ScopedValue

runner = CliRunner()


def make_config(
    provider: str | None = None,
    api_key: str | None = None,
    generator_model: str | None = None,
    scope: Scope = "default",
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


# --- dp config set ---


def test_config_set_writes_global_key(monkeypatch, tmp_path):
    g = tmp_path / "g.toml"
    r = tmp_path / "r.toml"
    monkeypatch.setattr(
        "docspatch.commands.config.current_store",
        lambda: __import__("docspatch.utils.config", fromlist=["ConfigStore"]).ConfigStore(global_path=g, repo_path=r),
    )

    result = runner.invoke(app, ["config", "set", "provider", "anthropic"])
    assert result.exit_code == 0
    import tomllib

    assert tomllib.loads(g.read_text())["provider"] == "anthropic"


def test_config_set_writes_repo_key(monkeypatch, tmp_path):
    g = tmp_path / "g.toml"
    r = tmp_path / "r.toml"
    monkeypatch.setattr(
        "docspatch.commands.config.current_store",
        lambda: __import__("docspatch.utils.config", fromlist=["ConfigStore"]).ConfigStore(global_path=g, repo_path=r),
    )

    result = runner.invoke(app, ["config", "set", "tone", "technical"])
    assert result.exit_code == 0
    import tomllib

    assert tomllib.loads(r.read_text())["tone"] == "technical"


def test_config_set_coerces_int_key(monkeypatch, tmp_path):
    g = tmp_path / "g.toml"
    r = tmp_path / "r.toml"
    monkeypatch.setattr(
        "docspatch.commands.config.current_store",
        lambda: __import__("docspatch.utils.config", fromlist=["ConfigStore"]).ConfigStore(global_path=g, repo_path=r),
    )

    result = runner.invoke(app, ["config", "set", "batch_token_limit", "12000"])
    assert result.exit_code == 0
    import tomllib

    assert tomllib.loads(r.read_text())["batch_token_limit"] == 12000


def test_config_set_unknown_key_fails_with_hint(monkeypatch, tmp_path):
    g = tmp_path / "g.toml"
    r = tmp_path / "r.toml"
    monkeypatch.setattr(
        "docspatch.commands.config.current_store",
        lambda: __import__("docspatch.utils.config", fromlist=["ConfigStore"]).ConfigStore(global_path=g, repo_path=r),
    )

    result = runner.invoke(app, ["config", "set", "bogus_key", "x"])
    assert result.exit_code == 1
    assert "Unknown config key" in result.output


def test_config_set_masks_api_key_in_output(monkeypatch, tmp_path):
    g = tmp_path / "g.toml"
    r = tmp_path / "r.toml"
    monkeypatch.setattr(
        "docspatch.commands.config.current_store",
        lambda: __import__("docspatch.utils.config", fromlist=["ConfigStore"]).ConfigStore(global_path=g, repo_path=r),
    )

    result = runner.invoke(app, ["config", "set", "api_key_anthropic", "sk-ant-supersecret"])
    assert result.exit_code == 0
    assert "supersecret" not in result.output


# --- dp cleanup ---


def use_scripted(monkeypatch, *answers):
    """Replace the default QuestionaryPrompter inside cleanup with a ScriptedPrompter."""
    from docspatch.ui import ScriptedPrompter

    monkeypatch.setattr(
        "docspatch.commands.cleanup.QuestionaryPrompter",
        lambda: ScriptedPrompter(answers),
    )


def test_cleanup_no_selection_exits_cleanly(monkeypatch):
    use_scripted(monkeypatch, [])  # checkbox returns []
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0


def test_cleanup_confirmation_required(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem

    item = CleanupItem(label="Repo config", path=tmp_path / "x.toml")
    use_scripted(monkeypatch, [item], False)  # selected, then confirm=False
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0
    assert "Cancelled" in result.output


def test_cleanup_deletes_selected_file(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem

    target = tmp_path / "config.toml"
    target.write_text("[config]\n")
    item = CleanupItem(label="Repo config", path=target)

    use_scripted(monkeypatch, [item], True)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    runner.invoke(app, ["cleanup"])
    assert not target.exists()


def test_cleanup_deletes_selected_directory(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "entry.gz").write_bytes(b"data")
    item = CleanupItem(label="Scout cache", path=cache_dir)

    use_scripted(monkeypatch, [item], True)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    runner.invoke(app, ["cleanup"])
    assert not cache_dir.exists()


def test_cleanup_no_deletion_when_confirm_false(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem

    target = tmp_path / "config.toml"
    target.write_text("[config]\n")
    item = CleanupItem(label="Repo config", path=target)

    use_scripted(monkeypatch, [item], False)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    runner.invoke(app, ["cleanup"])
    assert target.exists()


def test_cleanup_skips_nonexistent_path_with_info(monkeypatch, tmp_path):
    from docspatch.commands.cleanup import CleanupItem

    missing = tmp_path / "ghost.toml"  # never created
    item = CleanupItem(label="Ghost config", path=missing)

    use_scripted(monkeypatch, [item], True)
    monkeypatch.setattr("docspatch.commands.cleanup.cleanup_items", lambda root: [item])

    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0
    assert not missing.exists()
    assert "not found" in result.output.lower()
