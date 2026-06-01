"""Manage hierarchical configuration storage for docspatch."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

from docspatch.constants import CONFIG_DEFAULTS, GLOBAL_CONFIG_KEYS, INT_CONFIG_KEYS, REPO_CONFIG_KEYS
from docspatch.schemas import ConfigPatch, ConfigValue, DocspatchConfig, Scope, ScopedValue
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
        """Load the combined documentation configuration from storage."""
        return load_config(global_path=self.global_path, repo_path=self.repo_path)

    def api_key_for(self, provider: str) -> str | None:
        """Retrieve the API key for a provider from either the repo or global config.

        Args:
            provider: Name of the LLM provider.

        Returns:
            The stored API key, or null if unset.
        """
        field = f"api_key_{provider}"
        for path in (self.repo_path, self.global_path):
            value = read_toml(path).get(field)
            if value:
                return value if isinstance(value, str) else str(value)
        return None

    # ── writes ───────────────────────────────────────────────────────────

    def write_global(self, patch: ConfigPatch) -> None:
        """Save a configuration patch to the global settings file.

        Args:
            patch: Dictionary of key-value pairs to merge.
        """
        merge_write(self.global_path, patch)

    def write_repo(self, patch: ConfigPatch) -> None:
        """Save a configuration patch to the local repository settings file.

        Args:
            patch: Dictionary of key-value pairs to merge.
        """
        merge_write(self.repo_path, patch)

    def set(self, key: str, raw_value: str) -> WrittenKey:
        """Validate, coerce, and persist a single configuration value.

        Args:
            key: Configuration setting name.
            raw_value: Value provided by the user.

        Returns:
            The written key-value pair and its scope.
        """
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
        """Determine whether a key belongs in the global or repository configuration.

        Args:
            key: Configuration setting name.

        Raises:
            ConfigError: The provided key is not a recognized configuration field.
        """
        if key in GLOBAL_CONFIG_KEYS or key.startswith("api_key"):
            return "global"
        if key in REPO_CONFIG_KEYS:
            return "repo"
        valid = sorted(GLOBAL_CONFIG_KEYS | REPO_CONFIG_KEYS) + ["api_key_<provider>"]
        raise ConfigError.unknown_key(key, valid)

    @staticmethod
    def coerce(key: str, value: str) -> ConfigValue:
        """Convert a raw string value into the required type for a given key.

        Args:
            key: Configuration setting name.
            value: Value to transform.

        Raises:
            ConfigError: The value fails to convert to the expected type.
        """
        if key in INT_CONFIG_KEYS:
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigError.must_be_int(key, value, exc) from exc
        return value


def default_store(repo_root: Path | None = None) -> ConfigStore:
    """Construct a ConfigStore pointing to standard local and global file paths.

    Args:
        repo_root: The base directory of the repository.
    """
    root = repo_root or Path.cwd()
    return ConfigStore(
        global_path=Path.home() / ".docspatch" / "config.toml",
        repo_path=root / ".docspatch" / "config.toml",
    )


def load_config(global_path: Path | None = None, repo_path: Path | None = None) -> DocspatchConfig:
    """Merge global and repository configurations into a final settings object."""
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
        call_timeout=resolve("call_timeout"),
    )


def read_toml(path: Path | None) -> dict[str, Any]:
    """Read and parse a TOML file.

    Args:
        path: File system path to the configuration file.

    Returns:
        Parsed configuration data, or an empty dictionary if the file is missing or invalid.
    """
    if path is None:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError, OSError:
        return {}


def merge_write(path: Path, patch: ConfigPatch) -> None:
    """Apply a partial patch to a configuration file and write the result.

    Args:
        path: Target configuration file path.
        patch: Values to update.
    """
    existing = read_toml(path)
    merged: dict[str, Any] = {**existing, **{k: v for k, v in patch.items() if v is not None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, tomli_w.dumps(merged))
