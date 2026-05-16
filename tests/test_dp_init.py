"""Priority 4 tests — dp init interactive flow."""

import tomllib
from unittest.mock import AsyncMock, MagicMock

import docspatch.commands.init as init_cmd
from docspatch.commands.init import ScanResult
from docspatch.types.config import DocspatchConfig, ScopedValue

# provider → tier → tone → license
_DEFAULT_SELECTS = ["anthropic", "balanced", "professional", "MIT"]


def _patch_init(
    monkeypatch,
    *,
    selects: list[str] = _DEFAULT_SELECTS,
    password: str = "sk-ant-test",
    confirm: bool = False,
    validate_key: bool = True,
    context_up_to_date: bool = True,
):
    """Patch all external I/O for init.run(). Returns (mock_llm_cls, mock_client)."""
    sel_iter = iter(selects)

    def mock_select(*args, **kwargs):
        return MagicMock(ask=MagicMock(return_value=next(sel_iter)))

    monkeypatch.setattr("docspatch.commands.init.questionary.select", mock_select)
    monkeypatch.setattr(
        "docspatch.commands.init.questionary.password",
        lambda *a, **kw: MagicMock(ask=MagicMock(return_value=password)),
    )
    monkeypatch.setattr(
        "docspatch.commands.init.questionary.confirm",
        lambda *a, **kw: MagicMock(ask=MagicMock(return_value=confirm)),
    )

    mock_client = MagicMock()
    mock_client.validate_key.return_value = validate_key
    mock_llm_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr("docspatch.commands.init.LLMClient", mock_llm_cls)
    monkeypatch.setattr(
        "docspatch.commands.init._scan_tracked_files",
        lambda *a: ScanResult(all_current=context_up_to_date, token_estimate=0),
    )

    return mock_llm_cls, mock_client


# --- global config ---


def test_dp_init_writes_correct_global_config(monkeypatch, tmp_path):
    global_cfg = tmp_path / "global.toml"
    _patch_init(monkeypatch, selects=_DEFAULT_SELECTS, password="sk-ant-key123")

    init_cmd.run(repo_root=tmp_path, global_config_path=global_cfg)

    assert global_cfg.exists()
    data = tomllib.loads(global_cfg.read_text())
    assert data["provider"] == "anthropic"
    assert data["api_key_anthropic"] == "sk-ant-key123"


# --- repo config ---


def test_dp_init_writes_correct_repo_config(monkeypatch, tmp_path):
    global_cfg = tmp_path / "global.toml"
    _patch_init(monkeypatch, selects=_DEFAULT_SELECTS)

    init_cmd.run(repo_root=tmp_path, global_config_path=global_cfg)

    repo_cfg = tmp_path / ".docspatch" / "config.toml"
    assert repo_cfg.exists()
    data = tomllib.loads(repo_cfg.read_text())
    assert data["generator_model"] == "claude-sonnet-4-6"
    assert data["tone"] == "professional"
    assert data["scout_model"] == "claude-haiku-4-5-20251001"


# --- skip existing fields ---


def test_dp_init_skips_existing_fields(monkeypatch, tmp_path):
    pre_cfg = DocspatchConfig(
        provider=ScopedValue("anthropic", "global"),
        api_key=ScopedValue("sk-existing", "global"),
        generator_model=ScopedValue("claude-sonnet-4-6", "repo"),
        scout_model=ScopedValue("claude-haiku-4-5-20251001", "repo"),
        tone=ScopedValue("technical", "repo"),
        batch_token_limit=ScopedValue(6000, "default"),
    )
    monkeypatch.setattr("docspatch.commands.init.load_config", lambda **kw: pre_cfg)

    select_calls: list[str] = []

    def tracking_select(prompt="", *args, **kwargs):
        select_calls.append(str(prompt))
        return MagicMock(ask=MagicMock(return_value="MIT"))

    monkeypatch.setattr("docspatch.commands.init.questionary.select", tracking_select)
    monkeypatch.setattr(
        "docspatch.commands.init.questionary.password",
        lambda *a, **kw: MagicMock(ask=MagicMock(return_value="key")),
    )
    monkeypatch.setattr(
        "docspatch.commands.init.questionary.confirm",
        lambda *a, **kw: MagicMock(ask=MagicMock(return_value=False)),
    )
    monkeypatch.setattr(
        "docspatch.commands.init._scan_tracked_files",
        lambda *a: ScanResult(all_current=True, token_estimate=0),
    )
    mock_client = MagicMock()
    mock_client.validate_key.return_value = True
    monkeypatch.setattr("docspatch.commands.init.LLMClient", MagicMock(return_value=mock_client))

    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml")

    # Only license select fires; provider / tier / tone all skipped
    assert len(select_calls) == 1
    assert "license" in select_calls[0].lower()


# --- license generation ---


def test_dp_init_generates_license_when_absent(monkeypatch, tmp_path):
    _patch_init(monkeypatch, selects=["anthropic", "balanced", "professional", "MIT"])

    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml")

    license_file = tmp_path / "LICENSE"
    assert license_file.exists()
    assert "MIT License" in license_file.read_text()


# --- gitignore ---


def test_dp_init_adds_docspatch_to_gitignore(monkeypatch, tmp_path):
    _patch_init(monkeypatch, selects=_DEFAULT_SELECTS)

    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml")

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert ".docspatch" in gitignore.read_text()


# --- scout skipped when up to date ---


def test_dp_init_skips_scout_when_context_up_to_date(monkeypatch, tmp_path):
    mock_scout = AsyncMock()
    monkeypatch.setattr("docspatch.commands.init.scout_files", mock_scout)
    _patch_init(monkeypatch, selects=_DEFAULT_SELECTS, context_up_to_date=True)

    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml")

    mock_scout.assert_not_called()


# --- no LLM call when scout skipped ---


def test_dp_init_skip_choice_makes_no_llm_call(monkeypatch, tmp_path):
    mock_scout = AsyncMock()
    monkeypatch.setattr("docspatch.commands.init.scout_files", mock_scout)

    mock_reader = MagicMock()
    mock_reader.list_tracked_files.return_value = []
    monkeypatch.setattr("docspatch.commands.init.GitReader", lambda *a, **kw: mock_reader)

    _patch_init(monkeypatch, selects=_DEFAULT_SELECTS, confirm=False, context_up_to_date=False)

    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml")

    mock_scout.assert_not_called()
