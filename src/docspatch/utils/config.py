"""Loads, resolves, and persists local and global configuration parameters using TOML storage."""

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
        """Retrieve combined local and global settings into a single configuration object.

        Returns:
            The resolved configuration settings object.
        """
        return load_config(global_path=self.global_path, repo_path=self.repo_path)

    def api_key_for(self, provider: str) -> str | None:
        """Look up the API credential key for an LLM provider within local or global TOML configs.

        Args:
            provider: Name of the provider whose API key to lookup.

        Returns:
            The API key string, or None if not configured in local or global settings.
        """
        field = f"api_key_{provider}"
        for path in (self.repo_path, self.global_path):
            value = read_toml(path).get(field)
            if value:
                return value if isinstance(value, str) else str(value)
        return None

    # ── writes ───────────────────────────────────────────────────────────

    def write_global(self, patch: ConfigPatch) -> None:
        """Save a partial configuration update to the global user settings file.

        Args:
            patch: Partial configuration update dictionary.
        """
        merge_write(self.global_path, patch)

    def write_repo(self, patch: ConfigPatch) -> None:
        """Save a partial configuration update to the local workspace settings file.

        Args:
            patch: Partial configuration update dictionary.
        """
        merge_write(self.repo_path, patch)

    def set(self, key: str, raw_value: str) -> WrittenKey:
        """Convert, write, and persist a single configuration value to its designated global or local file.

        Args:
            key: Configuration option name to set.
            raw_value: Raw string value representing the new setting.

        Returns:
            A WrittenKey tuple capturing the name, coerced value, and resolved scope.
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
        """Resolve whether a configuration parameter belongs in global or repo-local storage.

        Args:
            key: Configuration option name to classify.

        Returns:
            The resolved Scope string ('global' or 'repo').

        Raises:
            ConfigError: The key is unrecognized.
        """
        if key in GLOBAL_CONFIG_KEYS or key.startswith("api_key"):
            return "global"
        if key in REPO_CONFIG_KEYS:
            return "repo"
        valid = sorted(GLOBAL_CONFIG_KEYS | REPO_CONFIG_KEYS) + ["api_key_<provider>"]
        raise ConfigError.unknown_key(key, valid)

    @staticmethod
    def coerce(key: str, value: str) -> ConfigValue:
        """Convert a configuration string value into its required integer or string data type.

        Args:
            key: Configuration key guiding the conversion type.
            value: Raw string value to transform.

        Returns:
            The type-coerced configuration value.

        Raises:
            ConfigError: The configuration value cannot be parsed as the target type.
        """
        if key in INT_CONFIG_KEYS:
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigError.must_be_int(key, value, exc) from exc
        return value


def default_store(repo_root: Path | None = None) -> ConfigStore:
    """Instantiate a ConfigStore using default user-home and local directory settings paths.

    Args:
        repo_root: Custom base directory path for local repository configurations.

    Returns:
        A ConfigStore initialized with global and local configuration paths.
    """
    root = repo_root or Path.cwd()
    return ConfigStore(
        global_path=Path.home() / ".docspatch" / "config.toml",
        repo_path=root / ".docspatch" / "config.toml",
    )


def load_config(global_path: Path | None = None, repo_path: Path | None = None) -> DocspatchConfig:
    """Load, merge, and resolve configurations from multiple scopes into a single settings container.

    Args:
        global_path: Path to the global TOML settings file.
        repo_path: Path to the repository-local TOML settings file.

    Returns:
        A compiled DocspatchConfig containing scoped values for all configuration properties.
    """
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
        analysis_model=resolve("analysis_model"),
        tone=resolve("tone"),
        batch_token_limit=resolve("batch_token_limit"),
        concurrency_limit=resolve("concurrency_limit"),
        call_timeout=resolve("call_timeout"),
    )


def read_toml(path: Path | None) -> dict[str, Any]:
    """Read and parse a TOML file, returning an empty dictionary on error or absence.

    Args:
        path: File system path pointing to the TOML file.

    Returns:
        A dictionary containing parsed TOML keys, or an empty dictionary if missing or malformed.
    """
    if path is None:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError, OSError:
        return {}


def merge_write(path: Path, patch: ConfigPatch) -> None:
    """Merge updates with existing settings and write them atomically to the TOML configuration file.

    Args:
        path: Destination file path for writing the merged config.
        patch: Dictionary containing setting updates.
    """
    existing = read_toml(path)
    merged: dict[str, Any] = {**existing, **{k: v for k, v in patch.items() if v is not None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, tomli_w.dumps(merged))
