"""`ensure_configured` reusable initializer for any command needing full config."""

import tomllib

from docspatch.ui import ScriptedPrompter
from docspatch.utils.config import ConfigStore
from docspatch.utils.selection import ensure_configured


def make_store(tmp_path):
    return ConfigStore(
        global_path=tmp_path / "global.toml",
        repo_path=tmp_path / "repo" / ".docspatch" / "config.toml",
    )


def accept_key(_provider: str, _key: str) -> bool:
    return True


def test_prompts_for_all_fields_when_config_empty(tmp_path):
    store = make_store(tmp_path)
    prompter = ScriptedPrompter(["anthropic", "sk-test", "balanced", "professional"])

    selections = ensure_configured(store, prompter, accept_key)

    assert selections.provider == "anthropic"
    assert selections.api_key == "sk-test"
    assert selections.generator_model == "claude-sonnet-4-6"
    assert selections.tone == "professional"
    assert prompter._index == 4


def test_persists_selections_to_disk(tmp_path):
    store = make_store(tmp_path)

    ensure_configured(
        store,
        ScriptedPrompter(["anthropic", "sk-test", "balanced", "professional"]),
        accept_key,
    )

    global_data = tomllib.loads((tmp_path / "global.toml").read_text())
    assert global_data["provider"] == "anthropic"
    assert global_data["api_key_anthropic"] == "sk-test"
    repo_data = tomllib.loads((tmp_path / "repo" / ".docspatch" / "config.toml").read_text())
    assert repo_data["generator_model"] == "claude-sonnet-4-6"
    assert repo_data["tone"] == "professional"


def test_no_prompts_when_fully_configured(tmp_path):
    store = make_store(tmp_path)
    store.global_path.parent.mkdir(parents=True, exist_ok=True)
    store.global_path.write_text('provider = "anthropic"\napi_key_anthropic = "sk-existing"\n')
    store.repo_path.parent.mkdir(parents=True, exist_ok=True)
    store.repo_path.write_text('generator_model = "claude-sonnet-4-6"\nscout_model = "claude-haiku-4-5-20251001"\ntone = "technical"\n')

    prompter = ScriptedPrompter([])
    selections = ensure_configured(store, prompter, accept_key)

    assert selections.provider == "anthropic"
    assert selections.tone == "technical"
    assert prompter._index == 0
