"""Mid-run provider/model switch when a pipeline exhausts its retry budget.

The switcher is provider-agnostic and pipeline-agnostic: any pipeline that
catches :class:`TransientExhausted` can await :func:`offer_switch` to give
the user a chance to swap providers/tiers without restarting the run.
"""

from dataclasses import dataclass

from docspatch.llm import TIER_CATALOGUE, LLMClient, resolve_tier_model
from docspatch.types.llm import Tier, as_provider, as_tier
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
    """Prompt the user to switch provider/tier after exhaustion.

    Returns the newly-built :class:`LLMClient` (already validated, persisted to
    config) or ``None`` if the user chose to abort.
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
    new_key = str(await aprompt(select_api_key, new_provider, store, p, reconfigure=False))

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
    """Build a label→tier mapping for the tier picker (mirrors selection.ask_tier)."""
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
