"""Manage mid-process model switching when rate limits or exhaustion occur."""

from dataclasses import dataclass

from docspatch.llm import TIER_CATALOGUE, LLMClient, resolve_tier_model, validate_api_key
from docspatch.schemas import Tier, as_provider, as_tier
from docspatch.ui import Prompter, aprompt, console
from docspatch.utils.config import ConfigStore
from docspatch.utils.retry import OnRetry
from docspatch.utils.selection import select_api_key

_PROVIDERS = ["anthropic", "openai", "gemini"]


@dataclass(frozen=True)
class SwitchResult:
    client: LLMClient
    tier: Tier


async def offer_switch(
    store: ConfigStore,
    p: Prompter,
    *,
    current_provider: str,
    current_model: str,
    retry_cb: OnRetry | None = None,
) -> SwitchResult | None:
    """Prompt user to switch provider or tier after exhaustion.

    Args:
        store: Config storage.
        p: Prompter instance.
        current_provider: The provider that failed.
        current_model: The model that failed.
        retry_cb: Optional retry callback.

    Returns:
        A new client and tier, or null if the user aborts.
    """
    console.print(f"[yellow]⚠[/yellow] Model {current_model} on {current_provider} exhausted its retry budget.")

    action = str(
        await aprompt(
            p.select,
            "Continue with a different provider/model?",
            {"Switch and resume": "switch", "Abort run": "abort"},
            default="switch",
        )
    )
    if action != "switch":
        return None

    new_provider = str(await aprompt(p.select, "New provider:", _PROVIDERS, default=current_provider))
    new_tier = str(await aprompt(p.select, "New tier:", _tier_choices(new_provider), default="balanced"))
    new_key = str(await aprompt(select_api_key, new_provider, store, p, validate_api_key, reconfigure=False))

    store.write_global({"provider": new_provider, f"api_key_{new_provider}": new_key})
    store.write_repo(
        {
            "generator_model": resolve_tier_model(new_provider, new_tier),
            "scout_model": resolve_tier_model(new_provider, "fast"),
        }
    )

    client = LLMClient(provider=new_provider, api_key=new_key, generator_tier=new_tier, retry_cb=retry_cb)
    console.print(f"[green]✓[/green] Switched to {new_provider} / {new_tier}")
    return SwitchResult(client=client, tier=as_tier(new_tier))


def _tier_choices(provider: str) -> dict[str, str]:
    """Build a label-to-tier mapping for the tier picker.

    Args:
        provider: Provider name to get tiers for.

    Returns:
        Dictionary mapping displayed labels to internal tier names.
    """
    tiers = TIER_CATALOGUE[as_provider(provider)]
    name_width = max(len(t.tier) for t in tiers)
    model_width = max(len(t.model) for t in tiers)
    out: dict[str, str] = {}
    for t in tiers:
        suffix = "  (recommended)" if t.tier == "balanced" else ""
        label = (
            f"{t.icon}  {t.tier.ljust(name_width)}  ·  "
            f"{t.model.ljust(model_width)}  ·  "
            f"${t.price_input_per_1m:>5} in / ${t.price_output_per_1m:>5} out{suffix}"
        )
        out[label] = t.tier
    return out
