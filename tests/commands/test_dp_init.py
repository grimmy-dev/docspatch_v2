"""dp init interactive flow.

All tests drive the flow through a `ScriptedPrompter` instead of monkeypatching
the global `questionary` module. That is the contract the Prompter seam exists
to make easy. init configures, picks a license, and writes .gitignore — no
code pre-analysis runs.
"""

import tomllib
from unittest.mock import MagicMock

import docspatch.commands.init as init_cmd
from docspatch.schemas import DocspatchConfig, ScopedValue
from docspatch.ui import ScriptedPrompter

# Default scripted answers: provider → password → tier → tone → license
_DEFAULT_ANSWERS = ["anthropic", "sk-ant-test", "balanced", "professional", "MIT"]


def _patch_env(monkeypatch, *, validate_key: bool = True) -> None:
    """Patch out the key validator so no network call fires."""
    monkeypatch.setattr("docspatch.llm.client.validate_api_key", lambda _provider, _key: validate_key)


# --- global config ---


def test_dp_init_writes_correct_global_config(monkeypatch, tmp_path):
    _patch_env(monkeypatch)
    global_cfg = tmp_path / "global.toml"

    answers = ["anthropic", "sk-ant-key123", "balanced", "professional", "MIT"]
    init_cmd.run(repo_root=tmp_path, global_config_path=global_cfg, prompter=ScriptedPrompter(answers))

    data = tomllib.loads(global_cfg.read_text())
    assert data["provider"] == "anthropic"
    assert data["api_key_anthropic"] == "sk-ant-key123"


# --- repo config ---


def test_dp_init_writes_correct_repo_config(monkeypatch, tmp_path):
    _patch_env(monkeypatch)
    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml", prompter=ScriptedPrompter(_DEFAULT_ANSWERS))

    data = tomllib.loads((tmp_path / ".docspatch" / "config.toml").read_text())
    assert data["generator_model"] == "claude-sonnet-4-6"
    assert data["tone"] == "professional"
    assert data["analysis_model"] == "claude-haiku-4-5-20251001"


# --- skip existing fields ---


def test_dp_init_skips_existing_fields(monkeypatch, tmp_path):
    pre_cfg = DocspatchConfig(
        provider=ScopedValue("anthropic", "global"),
        api_key=ScopedValue("sk-existing", "global"),
        generator_model=ScopedValue("claude-sonnet-4-6", "repo"),
        analysis_model=ScopedValue("claude-haiku-4-5-20251001", "repo"),
        tone=ScopedValue("technical", "repo"),
        batch_token_limit=ScopedValue(6000, "default"),
    )
    global_cfg = tmp_path / "global.toml"
    global_cfg.write_text('provider = "anthropic"\napi_key_anthropic = "sk-existing"\n')
    monkeypatch.setattr(
        "docspatch.commands.init.ConfigStore",
        lambda **kw: MagicMock(
            read=lambda: pre_cfg,
            write_global=lambda *a, **kw: None,
            write_repo=lambda *a, **kw: None,
            global_path=global_cfg,
            repo_path=tmp_path / ".docspatch" / "config.toml",
        ),
    )
    _patch_env(monkeypatch)

    # Only the license prompt should fire; provider/key/tier/tone are cached.
    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml", prompter=ScriptedPrompter(["MIT"]))


# --- license generation ---


def test_dp_init_generates_license_when_absent(monkeypatch, tmp_path):
    _patch_env(monkeypatch)
    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml", prompter=ScriptedPrompter(_DEFAULT_ANSWERS))

    license_file = tmp_path / "LICENSE"
    assert license_file.exists()
    assert "MIT License" in license_file.read_text()


def test_dp_init_skips_license_prompt_when_present(monkeypatch, tmp_path):
    (tmp_path / "LICENSE").write_text("MIT License\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nlicense = "MIT"\n')
    _patch_env(monkeypatch)

    # provider, password, tier, tone — license prompt skipped.
    init_cmd.run(
        repo_root=tmp_path,
        global_config_path=tmp_path / "global.toml",
        prompter=ScriptedPrompter(["anthropic", "sk-ant-test", "balanced", "professional"]),
    )

    assert (tmp_path / "LICENSE").read_text() == "MIT License\n"


def test_dp_init_reconfigure_re_prompts_every_field(monkeypatch, tmp_path):
    pre_cfg = DocspatchConfig(
        provider=ScopedValue("anthropic", "global"),
        api_key=ScopedValue("sk-existing", "global"),
        generator_model=ScopedValue("claude-sonnet-4-6", "repo"),
        analysis_model=ScopedValue("claude-haiku-4-5-20251001", "repo"),
        tone=ScopedValue("technical", "repo"),
        batch_token_limit=ScopedValue(6000, "default"),
    )
    monkeypatch.setattr(
        "docspatch.commands.init.ConfigStore",
        lambda **kw: MagicMock(
            read=lambda: pre_cfg,
            write_global=lambda *a, **kw: None,
            write_repo=lambda *a, **kw: None,
            global_path=tmp_path / "g.toml",
            repo_path=tmp_path / "r.toml",
        ),
    )
    _patch_env(monkeypatch)

    # Reconfigure forces every prompt: provider, password, tier, tone, license.
    prompter = ScriptedPrompter(["openai", "sk-new", "balanced", "casual", "MIT"])
    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml", reconfigure=True, prompter=prompter)

    assert prompter._index == 5  # all five answers consumed


def test_dp_init_masks_api_key_on_rerun(monkeypatch, tmp_path, capsys):
    pre_cfg = DocspatchConfig(
        provider=ScopedValue("anthropic", "global"),
        api_key=ScopedValue("sk-ant-supersecretvalue", "global"),
        generator_model=ScopedValue("claude-sonnet-4-6", "repo"),
        analysis_model=ScopedValue("claude-haiku-4-5-20251001", "repo"),
        tone=ScopedValue("technical", "repo"),
        batch_token_limit=ScopedValue(6000, "default"),
    )
    global_cfg = tmp_path / "global.toml"
    global_cfg.write_text('provider = "anthropic"\napi_key_anthropic = "sk-ant-supersecretvalue"\n')
    monkeypatch.setattr(
        "docspatch.commands.init.ConfigStore",
        lambda **kw: MagicMock(
            read=lambda: pre_cfg,
            write_global=lambda *a, **kw: None,
            write_repo=lambda *a, **kw: None,
            global_path=global_cfg,
            repo_path=tmp_path / ".docspatch" / "config.toml",
        ),
    )
    (tmp_path / "LICENSE").write_text("x")
    (tmp_path / "pyproject.toml").write_text('[project]\nlicense = "MIT"\n')
    _patch_env(monkeypatch)

    # All fields cached and license present — no prompts fire.
    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml", prompter=ScriptedPrompter([]))

    out = capsys.readouterr().out
    assert "supersecretvalue" not in out
    assert "••••" in out


# --- gitignore ---


def test_dp_init_adds_docspatch_to_gitignore(monkeypatch, tmp_path):
    _patch_env(monkeypatch)
    init_cmd.run(repo_root=tmp_path, global_config_path=tmp_path / "global.toml", prompter=ScriptedPrompter(_DEFAULT_ANSWERS))

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert ".docspatch" in gitignore.read_text()
