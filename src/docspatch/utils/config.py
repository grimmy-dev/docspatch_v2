"""Two-layer config: global ``~/.docspatch/config.toml`` + per-repo ``.docspatch/config.toml``.

All reads + writes go through :class:`ConfigStore`. Writes use ``tomli_w`` (round-trip
safe; correct quote/backslash escaping) instead of a handwritten serialiser.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

from docspatch.constants import CONFIG_DEFAULTS, GLOBAL_CONFIG_KEYS, INT_CONFIG_KEYS, REPO_CONFIG_KEYS
from docspatch.types.config import ConfigPatch, ConfigValue, DocspatchConfig, Scope, ScopedValue
from docspatch.utils.errors import ConfigError
from docspatch.utils.fs import atomic_write


@dataclass(frozen=True)
class WrittenKey:
    """Result of :meth:`ConfigStore.set`. Carries everything needed to render success UX."""

    key: str
    value: ConfigValue
    scope: Scope


@dataclass
class ConfigStore:
    """Single seam for reading and writing docspatch config files.

    Two-layer model:
    - ``global_path`` (``~/.docspatch/config.toml``) holds provider + api keys.
    - ``repo_path`` (``.docspatch/config.toml``) holds per-repo overrides.

    Per-repo always wins on read. Writes merge over existing content so fields
    outside the supplied patch are preserved.
    """

    global_path: Path
    repo_path: Path

    # ── reads ────────────────────────────────────────────────────────────

    def read(self) -> DocspatchConfig:
        return load_config(global_path=self.global_path, repo_path=self.repo_path)

    def api_key_for(self, provider: str) -> str | None:
        """Return ``api_key_<provider>`` from repo or global config, or None if absent.

        Repo wins. Looked up directly so switching providers reuses a previously
        stored key without re-prompting.
        """
        field = f"api_key_{provider}"
        for path in (self.repo_path, self.global_path):
            value = read_toml(path).get(field)
            if value:
                return value if isinstance(value, str) else str(value)
        return None

    # ── writes ───────────────────────────────────────────────────────────

    def write_global(self, patch: ConfigPatch) -> None:
        merge_write(self.global_path, patch)

    def write_repo(self, patch: ConfigPatch) -> None:
        merge_write(self.repo_path, patch)

    def set(self, key: str, raw_value: str) -> WrittenKey:
        """Coerce and persist a single key. Scope is inferred from the key."""
        coerced = self.coerce(key, raw_value)
        scope = self.scope_for(key)
        if scope == "global":
            self.write_global({key: coerced})
        else:
            self.write_repo({key: coerced})
        return WrittenKey(key=key, value=coerced, scope=scope)

    # ── policy ───────────────────────────────────────────────────────────

    @staticmethod
    def scope_for(key: str) -> Scope:
        """Return the scope (``global``/``repo``) where ``key`` lives.

        Raises:
            ConfigError: When ``key`` is not a recognised config field.
        """
        if key in GLOBAL_CONFIG_KEYS or key.startswith("api_key"):
            return "global"
        if key in REPO_CONFIG_KEYS:
            return "repo"
        valid = sorted(GLOBAL_CONFIG_KEYS | REPO_CONFIG_KEYS) + ["api_key_<provider>"]
        raise ConfigError.unknown_key(key, valid)

    @staticmethod
    def coerce(key: str, value: str) -> ConfigValue:
        """Coerce a raw string value to the type expected by ``key``."""
        if key in INT_CONFIG_KEYS:
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigError.must_be_int(key, value, exc) from exc
        return value


def default_store(repo_root: Path | None = None) -> ConfigStore:
    """Canonical :class:`ConfigStore` rooted at ``~/.docspatch`` + ``<repo_root>/.docspatch``."""
    root = repo_root or Path.cwd()
    return ConfigStore(
        global_path=Path.home() / ".docspatch" / "config.toml",
        repo_path=root / ".docspatch" / "config.toml",
    )


def load_config(global_path: Path | None = None, repo_path: Path | None = None) -> DocspatchConfig:
    """Merge global and repo configs. Per-repo wins. Missing keys fall back to defaults."""
    global_data = read_toml(global_path)
    repo_data = read_toml(repo_path)

    def resolve(key: str) -> ScopedValue[Any]:
        if key in repo_data:
            return ScopedValue(repo_data[key], "repo")
        if key in global_data:
            return ScopedValue(global_data[key], "global")
        return ScopedValue(CONFIG_DEFAULTS.get(key), "default")

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
        concurrency_limit=resolve("concurrency_limit"),
    )


def read_toml(path: Path | None) -> dict[str, Any]:
    """Parse a TOML file. Returns ``{}`` on any error or missing file."""
    if path is None:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError, OSError:
        return {}


def merge_write(path: Path, patch: ConfigPatch) -> None:
    """Merge ``patch`` over existing file content and write atomically.

    ``None`` values in ``patch`` are dropped so a partial update never wipes
    fields the caller did not intend to touch.
    """
    existing = read_toml(path)
    merged: dict[str, Any] = {**existing, **{k: v for k, v in patch.items() if v is not None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, tomli_w.dumps(merged))
