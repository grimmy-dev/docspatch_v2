"""Interactive selection of provider, key, tier, tone, license + persistence.

Every selector follows the same skip-or-prompt contract: if the value is
already set and ``reconfigure`` is False, the selector echoes the existing
value (masked when secret) and returns it. Otherwise it prompts.

All selectors are synchronous — questionary spins its own event loop, so
selectors must never be called from inside an already-running loop.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docspatch.constants import TONES
from docspatch.llm import TIER_CATALOGUE, LLMClient, resolve_tier_model
from docspatch.types.llm import as_provider
from docspatch.ui import Prompter, console, status
from docspatch.utils.config import ConfigStore
from docspatch.utils.errors import ConfigError
from docspatch.utils.fs import atomic_write
from docspatch.utils.licenses import available as available_licenses
from docspatch.utils.licenses import text as license_text
from docspatch.utils.project import get_pyproject_field
from docspatch.utils.secrets import display_value


@dataclass(frozen=True)
class Selections:
    provider: str
    api_key: str
    generator_model: str
    tone: str


def gather_selections(store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> Selections:
    """Collect every config field needed by ``dp init`` in deterministic order."""
    provider = select_provider(store, p, reconfigure=reconfigure)
    api_key = select_api_key(provider, store, p, reconfigure=reconfigure)
    generator_model = select_tier(provider, store, p, reconfigure=reconfigure)
    tone = select_tone(store, p, reconfigure=reconfigure)
    return Selections(provider=provider, api_key=api_key, generator_model=generator_model, tone=tone)


def persist(store: ConfigStore, selections: Selections) -> None:
    """Write ``selections`` to the appropriate scopes (global vs repo)."""
    scout_model = resolve_tier_model(selections.provider, "fast")
    store.write_global(
        {
            "provider": selections.provider,
            f"api_key_{selections.provider}": selections.api_key,
        }
    )
    store.write_repo(
        {
            "generator_model": selections.generator_model,
            "tone": selections.tone,
            "scout_model": scout_model,
        }
    )


def select_provider(store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    existing = store.read().provider
    return select_or_skip("provider", existing.value, existing.scope, lambda: ask_provider(p), reconfigure)


def select_api_key(provider: str, store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    stored = store.api_key_for(provider)
    return select_or_skip(
        f"api_key_{provider}",
        stored,
        "global" if stored else "default",
        lambda: ask_api_key(provider, p),
        reconfigure,
    )


def select_tier(provider: str, store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    existing = store.read().generator_model
    return select_or_skip(
        "generator_model",
        existing.value,
        existing.scope,
        lambda: ask_tier(provider, p),
        reconfigure,
    )


def select_tone(store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    existing = store.read().tone
    return select_or_skip("tone", existing.value, existing.scope, lambda: ask_tone(p), reconfigure)


def select_license(repo_root: Path, p: Prompter, *, reconfigure: bool = False) -> None:
    """Prompt for license, write LICENSE file + pyproject field if absent.

    No-op when both already present unless ``reconfigure`` forces a re-prompt.
    """
    license_file = repo_root / "LICENSE"
    pyproject = repo_root / "pyproject.toml"
    has_field = pyproject.exists() and get_pyproject_field(pyproject, "license") is not None

    if not reconfigure and license_file.exists() and has_field:
        console.print("[dim]license: already set (LICENSE file present)[/dim]")
        return

    choices = [*available_licenses(), "Skip"]
    selected = str(p.select("Select license:", choices))
    console.print(f"[green]✓[/green] license: {selected}")
    if selected == "Skip":
        return

    text = license_text(selected)
    if text and not license_file.exists():
        atomic_write(license_file, text)
        console.print(f"[green]✓[/green] LICENSE ({selected}) written")
    if pyproject.exists() and not has_field:
        update_pyproject_license(pyproject, selected)


def select_or_skip(
    field: str,
    existing_value: str | None,
    scope: str,
    prompt_fn: Callable[[], str],
    reconfigure: bool,
) -> str:
    """Echo + return existing value when set, else prompt."""
    if not reconfigure and existing_value is not None and scope != "default":
        console.print(f"[dim]{field}: already set ({display_value(field, existing_value)})[/dim]")
        return existing_value
    return prompt_fn()


def ask_provider(p: Prompter) -> str:
    choice = str(p.select("Select LLM provider:", ["anthropic", "openai", "gemini"]))
    console.print(f"[green]✓[/green] provider: {choice}")
    return choice


def ask_api_key(provider: str, p: Prompter) -> str:
    api_key = p.password(f"Enter {provider} API key:")
    try:
        with status(f"Validating {provider} API key..."):
            client = LLMClient(provider=provider, api_key=api_key)
            valid = client.validate_key()
    except Exception as exc:
        raise ConfigError.key_validation_failed(exc) from exc
    if not valid:
        raise ConfigError.invalid_api_key(provider)
    console.print(f"[green]✓[/green] api_key_{provider}: {display_value(f'api_key_{provider}', api_key)} (validated)")
    return api_key


def ask_tier(provider: str, p: Prompter) -> str:
    tiers = TIER_CATALOGUE[as_provider(provider)]
    fast_model = resolve_tier_model(provider, "fast")
    console.print(f"[dim]Scout model (fixed): {fast_model} (Fast tier)[/dim]")

    name_width = max(len(t.tier) for t in tiers)
    model_width = max(len(t.model) for t in tiers)

    choices: dict[str, str] = {}
    for t in tiers:
        suffix = "  (recommended)" if t.tier == "balanced" else ""
        label = (
            f"{t.icon}  {t.tier.ljust(name_width)}  ·  "
            f"{t.model.ljust(model_width)}  ·  "
            f"${t.price_input_per_1m:>5} in / ${t.price_output_per_1m:>5} out{suffix}"
        )
        choices[label] = t.tier

    tier = str(p.select("Select generator tier:", choices, default="balanced"))
    model = resolve_tier_model(provider, tier)
    console.print(f"[green]✓[/green] generator: {model} ({tier})")
    return model


def ask_tone(p: Prompter) -> str:
    choices = {f"{k} — {v}": k for k, v in TONES.items()}
    tone = str(p.select("Select documentation tone:", choices))
    console.print(f"[green]✓[/green] tone: {tone}")
    return tone


def update_pyproject_license(pyproject: Path, license_name: str) -> None:
    content = pyproject.read_text()
    if "[project]" in content and "license" not in content:
        new_lines: list[str] = []
        for line in content.splitlines(keepends=True):
            new_lines.append(line)
            if line.strip() == "[project]":
                new_lines.append(f'license = {{text = "{license_name}"}}\n')
        atomic_write(pyproject, "".join(new_lines))
