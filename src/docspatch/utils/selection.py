"""Interactive prompts for provider, API key, model tier, tone, and license."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docspatch.constants import TONES
from docspatch.llm import TIER_CATALOGUE, resolve_tier_model
from docspatch.schemas import as_provider
from docspatch.ui import Prompter, console, status
from docspatch.utils.config import ConfigStore
from docspatch.utils.errors import ConfigError
from docspatch.utils.fs import atomic_write
from docspatch.utils.git import GitReader
from docspatch.utils.licenses import available as available_licenses
from docspatch.utils.licenses import insert_copyright
from docspatch.utils.licenses import text as license_text
from docspatch.utils.project import get_pyproject_field
from docspatch.utils.secrets import display_value


@dataclass(frozen=True)
class Selections:
    provider: str
    api_key: str
    generator_model: str
    tone: str


# Provider + api_key → True iff the key is accepted. Injected by callers so
# selection.py stays free of LLM-client imports (adapter isolation).
ValidateKey = Callable[[str, str], bool]


def ensure_configured(
    store: ConfigStore,
    p: Prompter,
    validate_key: ValidateKey,
    *,
    reconfigure: bool = False,
) -> Selections:
    """Resolve all unset LLM and style selections, write them to disk, and return the selections.

    Args:
        store: Configuration storage instance to read from and write to.
        p: Prompt interface for terminal interactions.
        validate_key: Callback function to verify API key validity.
        reconfigure: Force prompt inputs even if existing configurations exist.

    Returns:
        A selections object containing the finalized configuration details.
    """
    selections = gather_selections(store, p, validate_key, reconfigure=reconfigure)
    persist(store, selections)
    return selections


def gather_selections(
    store: ConfigStore,
    p: Prompter,
    validate_key: ValidateKey,
    *,
    reconfigure: bool = False,
) -> Selections:
    """Collect interactive selections for provider, API key, model tier, and docstring tone.

    Args:
        store: Configuration storage instance containing existing settings.
        p: Prompt interface for terminal interactions.
        validate_key: Callback function to verify API key validity.
        reconfigure: Force user input even if a saved config exists.

    Returns:
        The populated configuration selections.
    """
    provider = select_provider(store, p, reconfigure=reconfigure)
    api_key = select_api_key(provider, store, p, validate_key, reconfigure=reconfigure)
    generator_model = select_tier(provider, store, p, reconfigure=reconfigure)
    tone = select_tone(store, p, reconfigure=reconfigure)
    return Selections(provider=provider, api_key=api_key, generator_model=generator_model, tone=tone)


def persist(store: ConfigStore, selections: Selections) -> None:
    """Save the provider and API key globally, and the generator model, tone, and analysis model to the local repository config.

    Args:
        store: Configuration storage instance to write to.
        selections: The chosen LLM and tone configurations to save.
    """
    analysis_model = resolve_tier_model(selections.provider, "fast")
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
            "analysis_model": analysis_model,
        }
    )


def select_provider(store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    """Retrieve the configured LLM provider or prompt the user if unset or reconfiguring.

    Args:
        store: Configuration storage instance.
        p: Prompt interface for terminal interactions.
        reconfigure: Force a prompt even if a provider is already configured.

    Returns:
        The resolved provider name.
    """
    existing = store.read().provider
    return select_or_skip("provider", existing.value, existing.scope, lambda: ask_provider(p), reconfigure)


def select_api_key(
    provider: str,
    store: ConfigStore,
    p: Prompter,
    validate_key: ValidateKey,
    *,
    reconfigure: bool = False,
) -> str:
    """Retrieve the saved API key for the provider or prompt the user for a new, validated key.

    Args:
        provider: Name of the target LLM provider.
        store: Configuration storage instance.
        p: Prompt interface for terminal interactions.
        validate_key: Callback function to verify key authenticity.
        reconfigure: Force a prompt even if an API key is already configured.

    Returns:
        The validated API key string.
    """
    stored = store.api_key_for(provider)
    return select_or_skip(
        f"api_key_{provider}",
        stored,
        "global" if stored else "default",
        lambda: ask_api_key(provider, p, validate_key),
        reconfigure,
    )


def select_tier(provider: str, store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    """Retrieve the saved generator model or prompt the user to choose a model tier.

    Args:
        provider: Name of the LLM provider.
        store: Configuration storage instance.
        p: Prompt interface for terminal interactions.
        reconfigure: Force a prompt even if a model tier is already configured.

    Returns:
        The resolved generator model name.
    """
    existing = store.read().generator_model
    return select_or_skip(
        "generator_model",
        existing.value,
        existing.scope,
        lambda: ask_tier(provider, p),
        reconfigure,
    )


def select_tone(store: ConfigStore, p: Prompter, *, reconfigure: bool = False) -> str:
    """Retrieve the saved docstring tone or prompt the user to choose a style.

    Args:
        store: Configuration storage instance.
        p: Prompt interface for terminal interactions.
        reconfigure: Force a prompt even if a tone is already configured.

    Returns:
        The chosen docstring tone name.
    """
    existing = store.read().tone
    return select_or_skip("tone", existing.value, existing.scope, lambda: ask_tone(p), reconfigure)


def select_license(repo_root: Path, p: Prompter, *, reconfigure: bool = False) -> None:
    """Prompt the user to select an open-source license and write the LICENSE file and pyproject.toml field if missing.

    Args:
        repo_root: Path to the local repository root.
        p: Prompt interface for terminal interactions.
        reconfigure: Force a prompt even if a license is already present.
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
        name, email = resolve_author(repo_root)
        if name:
            text = insert_copyright(text, name, datetime.now().year)
            console.print(f"[dim]author: {name}{f' · {email}' if email else ''}[/dim]")
        else:
            console.print("[dim]Tip: set `git config user.name` to embed your copyright.[/dim]")
        atomic_write(license_file, text)
        console.print(f"[green]✓[/green] LICENSE ({selected}) written")
    if pyproject.exists() and not has_field:
        update_pyproject_license(pyproject, selected)
        if get_pyproject_field(pyproject, "authors") is None:
            console.print("[dim]Tip: add an `authors` entry under [project] in pyproject.toml.[/dim]")


def resolve_author(repo_root: Path) -> tuple[str | None, str | None]:
    """Extract the user name and email from local git configuration.

    Args:
        repo_root: Path to the local repository root.

    Returns:
        A tuple containing the git user name and email, which may be None.
    """
    git = GitReader(repo_root)
    return git.config("user.name"), git.config("user.email")


def select_or_skip(
    field: str,
    existing_value: str | None,
    scope: str,
    prompt_fn: Callable[[], str],
    reconfigure: bool,
) -> str:
    """Return the existing configuration value if valid, otherwise execute the provided prompt function.

    Args:
        field: Name of the configuration field.
        existing_value: Currently saved value, if any.
        scope: Configuration scope, such as global, repo, or default.
        prompt_fn: Callback that executes terminal input prompts.
        reconfigure: Force executing the prompt function even if a value exists.

    Returns:
        The resolved configuration value.
    """
    if not reconfigure and existing_value is not None and scope != "default":
        console.print(f"[dim]{field}: already set ({display_value(field, existing_value)})[/dim]")
        return existing_value
    return prompt_fn()


def ask_provider(p: Prompter) -> str:
    """Prompt the user to select an LLM provider from supported platforms.

    Args:
        p: Prompt interface for terminal interactions.

    Returns:
        The selected provider name.
    """
    choice = str(p.select("Select LLM provider:", ["anthropic", "openai", "gemini"]))
    console.print(f"[green]✓[/green] provider: {choice}")
    return choice


def ask_api_key(provider: str, p: Prompter, validate_key: ValidateKey) -> str:
    """Prompt the user for an API key and validate it against the provider's API.

    Args:
        provider: The target LLM provider.
        p: Prompt interface for terminal interactions.
        validate_key: Callback function to verify key authenticity.

    Returns:
        The validated API key.

    Raises:
        ConfigError: Key validation fails or the provider returns an invalid status.
    """
    api_key = p.password(f"Enter {provider} API key:")
    try:
        with status(f"Validating {provider} API key..."):
            valid = validate_key(provider, api_key)
    except Exception as exc:
        raise ConfigError.key_validation_failed(exc) from exc
    if not valid:
        raise ConfigError.invalid_api_key(provider)
    console.print(f"[green]✓[/green] api_key_{provider}: {display_value(f'api_key_{provider}', api_key)} (validated)")
    return api_key


def ask_tier(provider: str, p: Prompter) -> str:
    """Prompt the user to select an LLM generation model tier based on price and model details.

    Args:
        provider: Name of the LLM provider.
        p: Prompt interface for terminal interactions.

    Returns:
        The model name corresponding to the selected tier.
    """
    tiers = TIER_CATALOGUE[as_provider(provider)]
    fast_model = resolve_tier_model(provider, "fast")
    console.print(f"[dim]Analysis model (fixed): {fast_model} (Fast tier)[/dim]")

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

    tier = str(p.select("Select generator tier:", choices))
    model = resolve_tier_model(provider, tier)
    console.print(f"[green]✓[/green] generator: {model} ({tier})")
    return model


def ask_tone(p: Prompter) -> str:
    """Prompt the user to choose a documentation tone from available presets.

    Args:
        p: Prompt interface for terminal interactions.

    Returns:
        The identifier of the selected tone.
    """
    choices = {f"{k} — {v}": k for k, v in TONES.items()}
    tone = str(p.select("Select documentation tone:", choices))
    console.print(f"[green]✓[/green] tone: {tone}")
    return tone


def update_pyproject_license(pyproject: Path, license_name: str) -> None:
    """Insert the license metadata field directly under the `[project]` section of a pyproject.toml file.

    Args:
        pyproject: Path to the pyproject.toml file.
        license_name: Standard name of the selected license.
    """
    content = pyproject.read_text()
    if "[project]" in content and "license" not in content:
        new_lines: list[str] = []
        for line in content.splitlines(keepends=True):
            new_lines.append(line)
            if line.strip() == "[project]":
                new_lines.append(f'license = {{text = "{license_name}"}}\n')
        atomic_write(pyproject, "".join(new_lines))
