"""Utils behavior tests (Priority 1)."""

import tomllib

from docspatch.utils.config import ConfigStore, load_config
from docspatch.utils.licenses import insert_copyright
from docspatch.utils.project import get_dir_tree, get_pyproject_field


def test_insert_copyright_adds_line_after_title():
    out = insert_copyright("MIT License\n\nPermission is hereby...\n", "Ada Lovelace", 2026)
    assert out.splitlines()[0] == "MIT License"
    assert "Copyright (c) 2026 Ada Lovelace" in out


def test_insert_copyright_skips_when_already_present():
    body = "MIT License\n\nCopyright (c) 1999 Bob\n\nPermission...\n"
    assert insert_copyright(body, "Ada", 2026) == body

# ── config ─────────────────────────────────────────────────────────────────


def test_config_per_repo_wins_over_global(tmp_path):
    global_cfg = tmp_path / "global" / "config.toml"
    global_cfg.parent.mkdir()
    global_cfg.write_text('provider = "openai"\ntone = "casual"\n')

    repo_cfg = tmp_path / "repo" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('tone = "technical"\n')

    cfg = load_config(global_path=global_cfg, repo_path=repo_cfg)
    assert cfg.tone.value == "technical"
    assert cfg.provider.value == "openai"


def test_config_scope_labels_correct(tmp_path):
    global_cfg = tmp_path / "global" / "config.toml"
    global_cfg.parent.mkdir()
    global_cfg.write_text('provider = "anthropic"\n')

    repo_cfg = tmp_path / "repo" / "config.toml"
    repo_cfg.parent.mkdir()
    repo_cfg.write_text('tone = "technical"\n')

    cfg = load_config(global_path=global_cfg, repo_path=repo_cfg)
    assert cfg.provider.scope == "global"
    assert cfg.tone.scope == "repo"
    assert cfg.batch_token_limit.scope == "default"


def test_config_missing_files_use_defaults(tmp_path):
    cfg = load_config(global_path=tmp_path / "no.toml", repo_path=tmp_path / "no2.toml")
    assert cfg.batch_token_limit.value == 10000
    assert cfg.batch_token_limit.scope == "default"
    assert cfg.tone.value == "professional"


# ── project ────────────────────────────────────────────────────────────────


def test_project_missing_fields_return_none(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "myapp"\n')

    assert get_pyproject_field(pyproject, "version") is None
    assert get_pyproject_field(pyproject, "description") is None


def test_project_existing_field_returned(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "myapp"\nversion = "1.0"\n')

    assert get_pyproject_field(pyproject, "name") == "myapp"
    assert get_pyproject_field(pyproject, "version") == "1.0"


def test_project_missing_file_returns_none(tmp_path):
    assert get_pyproject_field(tmp_path / "pyproject.toml", "name") is None


def test_configstore_writes_escapes_quotes_safely(tmp_path):
    """Handwritten TOML serialiser corrupted quoted values; tomli_w must not."""
    store = ConfigStore(global_path=tmp_path / "g.toml", repo_path=tmp_path / "r.toml")
    nasty = 'key-with-"quotes"-and-\\backslash'
    store.write_global({"provider": "anthropic", "api_key_anthropic": nasty})

    data = tomllib.loads((tmp_path / "g.toml").read_text())
    assert data["api_key_anthropic"] == nasty
    assert data["provider"] == "anthropic"


def test_configstore_merges_over_existing_fields(tmp_path):
    g = tmp_path / "g.toml"
    g.write_text('provider = "openai"\napi_key_openai = "sk-existing"\n')

    store = ConfigStore(global_path=g, repo_path=tmp_path / "r.toml")
    store.write_global({"provider": "anthropic", "api_key_anthropic": "sk-new"})

    data = tomllib.loads(g.read_text())
    # New provider takes effect, but pre-existing openai key is preserved.
    assert data["provider"] == "anthropic"
    assert data["api_key_anthropic"] == "sk-new"
    assert data["api_key_openai"] == "sk-existing"


def test_configstore_none_values_dropped_from_patch(tmp_path):
    g = tmp_path / "g.toml"
    g.write_text('provider = "openai"\n')

    store = ConfigStore(global_path=g, repo_path=tmp_path / "r.toml")
    store.write_global({"provider": None, "api_key_openai": "sk-x"})

    data = tomllib.loads(g.read_text())
    # None must not wipe the existing provider entry.
    assert data["provider"] == "openai"
    assert data["api_key_openai"] == "sk-x"


def test_project_dir_tree_correct_depth(tmp_path):
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c" / "deep.py").write_text("")
    (tmp_path / "a" / "shallow.py").write_text("")

    tree = get_dir_tree(tmp_path, max_depth=2)
    assert "shallow.py" in tree
    assert "deep.py" not in tree  # depth 3, excluded


def test_retry_policy_delay_grows_exponentially():
    from docspatch.utils.retry import RetryPolicy

    policy = RetryPolicy(max_attempts=5, base_delay=60.0, max_delay=300.0)
    assert policy.delay_for(0) == 60.0
    assert policy.delay_for(1) == 120.0
    assert policy.delay_for(2) == 240.0


def test_retry_policy_delay_capped_at_max_delay():
    from docspatch.utils.retry import RetryPolicy

    policy = RetryPolicy(max_attempts=5, base_delay=60.0, max_delay=300.0)
    assert policy.delay_for(3) == 300.0
    assert policy.delay_for(10) == 300.0


def test_llm_retry_defaults_match_policy():
    from docspatch.llm.client import LLM_RETRY

    assert LLM_RETRY.max_attempts == 5
    assert LLM_RETRY.base_delay == 60.0
    assert LLM_RETRY.max_delay == 300.0


def test_retry_display_routes_to_bound_sink():
    from docspatch.ui.retry_display import RetryDisplay

    captured: list[str] = []
    display = RetryDisplay()
    display.bind(captured.append)
    display(2, 120.0)
    assert captured and "120" in captured[-1] and "2" in captured[-1]


def test_retry_display_unbound_falls_back_to_console(capsys):
    from docspatch.ui.retry_display import RetryDisplay

    display = RetryDisplay()
    display(1, 60.0)
    out = capsys.readouterr().out
    assert "60" in out


def test_retry_display_unbind_restores_fallback(capsys):
    from docspatch.ui.retry_display import RetryDisplay

    captured: list[str] = []
    display = RetryDisplay()
    display.bind(captured.append)
    display.unbind()
    display(1, 60.0)
    assert captured == []
    assert "60" in capsys.readouterr().out


def test_progress_bar_exposes_set_status():
    from docspatch.ui.progress import progress_bar

    with progress_bar(total=2, description="Working") as bar:
        bar("first")
        bar.set_status("retry hint")
        bar("second")
