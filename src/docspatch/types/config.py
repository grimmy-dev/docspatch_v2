"""Config types."""

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

T = TypeVar("T")


@dataclass
class GlobalConfig:
    provider: str | None = None
    api_key_anthropic: str | None = None
    api_key_openai: str | None = None
    api_key_gemini: str | None = None


@dataclass
class RepoConfig:
    generator_model: str | None = None
    scout_model: str | None = None
    tone: str | None = None


Scope = Literal["global", "repo", "default"]


@dataclass
class ScopedValue(Generic[T]):
    value: T
    scope: Scope


@dataclass
class DocspatchConfig:
    provider: ScopedValue[str | None] = field(default_factory=lambda: ScopedValue(None, "default"))
    api_key: ScopedValue[str | None] = field(default_factory=lambda: ScopedValue(None, "default"))
    generator_model: ScopedValue[str | None] = field(default_factory=lambda: ScopedValue(None, "default"))
    scout_model: ScopedValue[str | None] = field(default_factory=lambda: ScopedValue("claude-haiku-4-5-20251001", "default"))
    tone: ScopedValue[str | None] = field(default_factory=lambda: ScopedValue("professional", "default"))
    batch_token_limit: ScopedValue[int] = field(default_factory=lambda: ScopedValue(6000, "default"))
