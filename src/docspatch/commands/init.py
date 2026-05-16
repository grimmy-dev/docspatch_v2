"""dp init command — interactive setup flow."""

import asyncio
import contextlib
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import questionary
from rich.table import Table

from docspatch.constants import LICENSE_TEXTS, TONES
from docspatch.context_store import ContextStore
from docspatch.errors import ConfigError, GitError
from docspatch.git_reader import GitReader
from docspatch.llm_client import TIER_CATALOGUE, LLMClient, resolve_tier_model
from docspatch.scout import scout_files
from docspatch.sourcer import Sourcer
from docspatch.types.config import DocspatchConfig
from docspatch.ui.console import console
from docspatch.utils.config import load_config
from docspatch.utils.fs import atomic_write
from docspatch.utils.project import get_pyproject_field


@dataclass
class Selections:
    provider: str
    api_key: str
    generator_model: str
    tone: str


@dataclass
class ScanResult:
    all_current: bool
    token_estimate: int


def run(
    repo_root: Path | None = None,
    global_config_path: Path | None = None,
) -> None:
    """Full dp init interactive flow."""
    repo_root = repo_root or Path.cwd()
    global_config_path = global_config_path or Path.home() / ".docspatch" / "config.toml"
    repo_config_path = repo_root / ".docspatch" / "config.toml"

    existing = load_config(global_path=global_config_path, repo_path=repo_config_path)
    selections = _gather_selections(existing)

    _handle_license(repo_root)
    _write_configs(global_config_path, repo_config_path, selections)

    ctx_store = _init_store(repo_root)
    _maybe_scout(repo_root, ctx_store, selections.provider, selections.api_key)


def _gather_selections(existing: DocspatchConfig) -> Selections:
    provider = _select_or_skip("provider", existing.provider.value, existing.provider.scope, _ask_provider)
    api_key = _select_or_skip(
        f"api_key_{provider}",
        existing.api_key.value,
        existing.api_key.scope,
        lambda: _ask_api_key(provider),
    )
    generator_model = _select_or_skip(
        "generator_model",
        existing.generator_model.value,
        existing.generator_model.scope,
        lambda: _ask_tier(provider),
    )
    tone = _select_or_skip("tone", existing.tone.value, existing.tone.scope, _ask_tone)
    return Selections(provider=provider, api_key=api_key, generator_model=generator_model, tone=tone)


def _write_configs(global_path: Path, repo_path: Path, selections: Selections) -> None:
    scout_model = resolve_tier_model(selections.provider, "fast")
    _write_toml(global_path, {"provider": selections.provider, f"api_key_{selections.provider}": selections.api_key})
    _write_toml(repo_path, {"generator_model": selections.generator_model, "tone": selections.tone, "scout_model": scout_model})


def _init_store(repo_root: Path) -> ContextStore:
    ctx_store = ContextStore(repo_root)
    ctx_store.ensure_gitignore()
    console.print("[green]✓[/green] .docspatch added to .gitignore")
    return ctx_store


def _select_or_skip(field: str, existing_value: str | None, scope: str, prompt_fn: Callable[[], str]) -> str:
    if existing_value is not None and scope != "default":
        console.print(f"[dim]{field}: already set ({existing_value})[/dim]")
        return existing_value
    return prompt_fn()


def _ask_provider() -> str:
    return questionary.select(
        "Select LLM provider:", choices=["anthropic", "openai", "gemini"]
    ).ask()


def _ask_api_key(provider: str) -> str:
    api_key = questionary.password(f"Enter {provider} API key:").ask()
    console.print("[dim]Validating key...[/dim]")
    try:
        client = LLMClient(provider=provider, api_key=api_key)
        valid = client.validate_key()
    except Exception as exc:
        raise ConfigError(f"Key validation failed: {exc}", hint="Check your key.") from exc
    if not valid:
        raise ConfigError(f"Invalid {provider} API key.", hint="Check your key and try again.")
    console.print("[green]✓[/green] Key valid")
    return api_key


def _ask_tier(provider: str) -> str:
    tiers = TIER_CATALOGUE[provider]
    fast_model = resolve_tier_model(provider, "fast")
    console.print(f"[dim]Scout model (fixed): {fast_model} (Fast tier)[/dim]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Icon")
    table.add_column("Tier")
    table.add_column("Model")
    table.add_column("Input $/1M")
    table.add_column("Output $/1M")
    for t in tiers:
        rec = " (recommended)" if t.tier == "balanced" else ""
        table.add_row(t.icon, t.tier + rec, t.model, f"${t.price_input_per_1m}", f"${t.price_output_per_1m}")
    console.print(table)

    tier = questionary.select(
        "Select generator tier:",
        choices=[t.tier for t in tiers],
        default="balanced",
    ).ask()
    return resolve_tier_model(provider, tier)


def _ask_tone() -> str:
    choices = [questionary.Choice(f"{k} — {v}", value=k) for k, v in TONES.items()]
    return questionary.select("Select documentation tone:", choices=choices).ask()


def _handle_license(repo_root: Path) -> None:
    license_file = repo_root / "LICENSE"
    pyproject = repo_root / "pyproject.toml"
    choices = [*LICENSE_TEXTS.keys(), "Skip"]
    selected = questionary.select("Select license:", choices=choices).ask()
    if selected == "Skip":
        return
    text = LICENSE_TEXTS.get(selected)
    if text and not license_file.exists():
        atomic_write(license_file, text)
        console.print(f"[green]✓[/green] LICENSE ({selected}) written")
    if pyproject.exists() and get_pyproject_field(pyproject, "license") is None:
        _update_pyproject_license(pyproject, selected)


def _update_pyproject_license(pyproject: Path, license_name: str) -> None:
    content = pyproject.read_text()
    if "[project]" in content and "license" not in content:
        lines = content.splitlines(keepends=True)
        new_lines: list[str] = []
        for line in lines:
            new_lines.append(line)
            if line.strip() == "[project]":
                new_lines.append(f'license = {{text = "{license_name}"}}\n')
        atomic_write(pyproject, "".join(new_lines))


def _maybe_scout(repo_root: Path, ctx_store: ContextStore, provider: str, api_key: str) -> None:
    try:
        paths = GitReader(cwd=repo_root).list_tracked_files()
    except GitError:
        paths = []

    if not paths:
        return

    scan = _scan_tracked_files(paths, ctx_store)

    if scan.all_current:
        console.print("[dim]Context already up to date — skipping scout.[/dim]")
        return

    fast_info = next(t for t in TIER_CATALOGUE[provider] if t.tier == "fast")
    scout_model = fast_info.model
    cost_est = (scan.token_estimate / 1_000_000) * (fast_info.price_input_per_1m + fast_info.price_output_per_1m)

    console.print(
        f"\nScout pre-build estimate:\n"
        f"  Files : {len(paths)}\n  Tokens: ~{scan.token_estimate:,}\n"
        f"  Model : {scout_model}\n  Cost  : ~${cost_est:.4f}\n"
    )

    if not questionary.confirm("Run scout pre-build now?").ask():
        console.print("[dim]Scout skipped.[/dim]")
        return

    llm = LLMClient(provider=provider, api_key=api_key, generator_tier="fast")
    result = asyncio.run(
        scout_files([str(p) for p in paths], ctx_store, llm, lambda p: console.print(f"  ✓ {p}"))
    )
    console.print(f"[green]Scout complete:[/green] {result.scouted} scouted, {result.skipped} cached")


def _scan_tracked_files(paths: list[Path], ctx_store: ContextStore) -> ScanResult:
    """Single pass over all tracked files: check cache staleness and estimate tokens."""
    all_current = True
    token_estimate = 0
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        token_estimate += Sourcer.estimate_tokens(source)
        cached = ctx_store.get_summary(str(path))
        if not cached or cached.content_hash != Sourcer.hash(source):
            all_current = False
    return ScanResult(all_current=all_current, token_estimate=token_estimate)


def _write_toml(path: Path, data: dict) -> None:
    existing: dict = {}
    if path.exists():
        with contextlib.suppress(tomllib.TOMLDecodeError, OSError):
            existing = tomllib.loads(path.read_text())
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, _dict_to_toml(merged))


def _dict_to_toml(data: dict) -> str:
    lines = []
    for k, v in data.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
    return ("\n".join(lines) + "\n") if lines else ""
