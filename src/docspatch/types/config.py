"""Config types. Defaults are sourced from :mod:`docspatch.constants`."""

from dataclasses import dataclass, field
from typing import Any, Literal

from docspatch.constants import CONFIG_DEFAULTS

Scope = Literal["global", "repo", "default"]
ConfigValue = str | int | None
ConfigPatch = dict[str, ConfigValue]


@dataclass(frozen=True)
class ScopedValue[T]:
    value: T
    scope: Scope


def _default(key: str) -> ScopedValue[Any]:
    return ScopedValue(CONFIG_DEFAULTS[key], "default")


@dataclass
class DocspatchConfig:
    provider: ScopedValue[str | None] = field(default_factory=lambda: _default("provider"))
    api_key: ScopedValue[str | None] = field(default_factory=lambda: _default("api_key"))
    generator_model: ScopedValue[str | None] = field(default_factory=lambda: _default("generator_model"))
    scout_model: ScopedValue[str | None] = field(default_factory=lambda: _default("scout_model"))
    tone: ScopedValue[str | None] = field(default_factory=lambda: _default("tone"))
    batch_token_limit: ScopedValue[int] = field(default_factory=lambda: _default("batch_token_limit"))
    concurrency_limit: ScopedValue[int] = field(default_factory=lambda: _default("concurrency_limit"))
    call_timeout: ScopedValue[int] = field(default_factory=lambda: _default("call_timeout"))
