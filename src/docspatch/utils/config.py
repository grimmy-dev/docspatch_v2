"""Two-layer config merge: global ~/.docspatch/config.toml + per-repo .docspatch/config.toml."""

import tomllib
from pathlib import Path

from docspatch.types.config import DocspatchConfig, Scope, ScopedValue

_DEFAULTS: dict[str, object] = {
    "provider": None,
    "api_key": None,
    "generator_model": None,
    "scout_model": "claude-haiku-4-5-20251001",
    "tone": "professional",
    "batch_token_limit": 6000,
}


def load_config(
    global_path: Path | None = None,
    repo_path: Path | None = None,
) -> DocspatchConfig:
    """Merge global and repo configs. Per-repo wins. Missing keys fall back to defaults."""
    global_data = _read_toml(global_path)
    repo_data = _read_toml(repo_path)

    def resolve(key: str) -> ScopedValue:
        if key in repo_data:
            return ScopedValue(repo_data[key], "repo")
        if key in global_data:
            return ScopedValue(global_data[key], "global")
        return ScopedValue(_DEFAULTS.get(key), "default")

    # api_key: use the key matching whichever provider is configured
    provider = resolve("provider").value
    api_key_field = f"api_key_{provider}" if provider else "api_key"
    api_key_val = repo_data.get(api_key_field) or global_data.get(api_key_field)
    api_key_scope: Scope = "repo" if api_key_field in repo_data else "global" if api_key_field in global_data else "default"

    return DocspatchConfig(
        provider=resolve("provider"),
        api_key=ScopedValue(api_key_val, api_key_scope),
        generator_model=resolve("generator_model"),
        scout_model=resolve("scout_model"),
        tone=resolve("tone"),
        batch_token_limit=resolve("batch_token_limit"),
    )


def _read_toml(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return {}
