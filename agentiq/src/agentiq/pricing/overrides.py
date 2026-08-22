"""Step 6.6 — Human-in-the-loop price overrides.

`PriceQuote.human_overrides` has existed since Phase 2 (a `dict[str, float |
str]` field), but ADR-0003 decision 7 explicitly deferred the *consumption*
logic — the pure function that actually adjusts the band given an
override — until this pass. `config/pricing.yaml`'s `human_overrides.
allowed_fields` names exactly three: `expected_footfall`,
`strategic_discount_intent`, `competitive_intel`. Any other key is rejected
rather than silently accepted, matching `PriceQuote.human_overrides`'s own
docstring: "never a silent edit, always visible here and in the trace."

Every adjustment here reuses an *already-established* guardrail rather than
introducing a new unbounded one:

- `expected_footfall` is clamped by the same `demand_multiplier.max_uplift_pct`
  / `max_discount_pct` Step 6.3's demand multiplier already uses — a rep's
  local knowledge can move the price no further than the model's own demand
  signal already can.
- `strategic_discount_intent` maps a closed vocabulary (not a free-form
  number) to a config-defined discount, still capped by `max_discount_pct`.
- `competitive_intel` shrinks the cap's margin above target by a measured
  ratio (Step 1.5 §6.5: competitor-named leads lose at a much thinner price
  gap), not an invented shrink factor.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from agentiq.data.paths import ProjectPaths
from agentiq.domain.explanation import Contribution, Explanation
from agentiq.domain.pricing import PriceQuote
from agentiq.pricing.bands import PriceBandConfig

ALLOWED_OVERRIDE_FIELDS: tuple[str, ...] = (
    "expected_footfall",
    "strategic_discount_intent",
    "competitive_intel",
)


@dataclass(frozen=True)
class HumanOverrideConfig:
    allowed_fields: tuple[str, ...]
    strategic_discount_pct: dict[str, float]
    competitive_intel_cap_shrink: float


def load_human_override_config(config_path: str | None = None) -> HumanOverrideConfig:
    path = ProjectPaths().config / "pricing.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)["human_overrides"]

    return HumanOverrideConfig(
        allowed_fields=tuple(raw["allowed_fields"]),
        strategic_discount_pct={k: float(v) for k, v in raw["strategic_discount_pct"].items()},
        competitive_intel_cap_shrink=float(raw["competitive_intel_cap_shrink"]),
    )


def _validate_overrides(overrides: dict[str, float | str], allowed_fields: tuple[str, ...]) -> None:
    unknown = set(overrides) - set(allowed_fields)
    if unknown:
        raise ValueError(
            f"Unknown human override field(s) {sorted(unknown)} — allowed fields are "
            f"{list(allowed_fields)} (config/pricing.yaml human_overrides.allowed_fields)."
        )


def apply_human_overrides(
    quote: PriceQuote,
    overrides: dict[str, float | str],
    *,
    config: HumanOverrideConfig,
    price_band_config: PriceBandConfig,
    model_expected_footfall: float | None = None,
) -> PriceQuote:
    """Return a new `PriceQuote` with *overrides* applied, logged, and explained.

    `quote` is not mutated (it is frozen) — this returns a fresh `PriceQuote`
    via `model_copy`, so the pre-override quote remains available to whoever
    called `PricingEngine.price()` for audit/comparison.
    """
    if not overrides:
        return quote
    _validate_overrides(overrides, config.allowed_fields)

    target = quote.target
    cap = quote.cap
    floor = quote.floor
    contributions: list[Contribution] = []
    fallbacks: list[str] = list(quote.explanation.fallbacks_used)

    if "expected_footfall" in overrides:
        rep_value = float(overrides["expected_footfall"])
        if model_expected_footfall is not None and model_expected_footfall > 0:
            raw_delta = (rep_value - model_expected_footfall) / model_expected_footfall
            clamped_delta = max(
                -price_band_config.max_discount_pct,
                min(price_band_config.max_uplift_pct, raw_delta),
            )
            target *= 1.0 + clamped_delta
            contributions.append(
                Contribution(
                    signal="human_override:expected_footfall",
                    direction=(
                        "positive"
                        if clamped_delta > 0
                        else ("negative" if clamped_delta < 0 else "neutral")
                    ),
                    weight=0.4,
                    magnitude=clamped_delta,
                    detail=(
                        f"Rep-supplied footfall {rep_value:,.0f} vs. model estimate "
                        f"{model_expected_footfall:,.0f}, clamped to "
                        f"[{-price_band_config.max_discount_pct:+.0%}, "
                        f"{price_band_config.max_uplift_pct:+.0%}]."
                    ),
                )
            )
            if raw_delta != clamped_delta:
                fallbacks.append("human_override_expected_footfall_clamped_by_demand_guardrail")
        else:
            fallbacks.append("human_override_expected_footfall_ignored_no_model_baseline")

    if "strategic_discount_intent" in overrides:
        intent = str(overrides["strategic_discount_intent"])
        if intent not in config.strategic_discount_pct:
            raise ValueError(
                f"strategic_discount_intent {intent!r} is not one of "
                f"{list(config.strategic_discount_pct)} (config/pricing.yaml)."
            )
        raw_discount = config.strategic_discount_pct[intent]
        clamped_discount = min(raw_discount, price_band_config.max_discount_pct)
        target *= 1.0 - clamped_discount
        contributions.append(
            Contribution(
                signal="human_override:strategic_discount_intent",
                direction="negative" if clamped_discount > 0 else "neutral",
                weight=0.3,
                magnitude=-clamped_discount,
                detail=f"Rep-stated intent {intent!r} -> {clamped_discount:.0%} discount.",
            )
        )

    if "competitive_intel" in overrides and str(overrides["competitive_intel"]).strip():
        note = str(overrides["competitive_intel"])
        margin = max(0.0, cap - target)
        shrunk_margin = margin * config.competitive_intel_cap_shrink
        cap = target + shrunk_margin
        margin_reduction = max(0.0, margin - shrunk_margin)
        contributions.append(
            Contribution(
                signal="human_override:competitive_intel",
                direction="negative" if margin_reduction > 0 else "neutral",
                weight=0.3,
                magnitude=-margin_reduction if margin_reduction > 0 else 0.0,
                detail=(
                    f"Cap margin shrunk to {config.competitive_intel_cap_shrink:.0%} of its "
                    f"prior width (Step 1.5 §6.5 measured competitor price-gap ratio) given: "
                    f"{note!r}."
                ),
            )
        )
        fallbacks.append("human_override_competitive_intel_cap_shrunk")

    # Re-clamp: floor <= target <= cap must hold regardless of which
    # overrides fired or in what order.
    target = max(floor, min(target, cap))
    recommended = max(floor, min(quote.recommended, cap))
    cap = max(cap, target)
    floor = min(floor, target)

    headline = (
        f"{quote.screen_id}/{quote.time_block_id}: human overrides applied "
        f"({', '.join(sorted(overrides))}) -> target={target:.2f}, cap={cap:.2f}."
    )
    new_explanation = Explanation(
        headline=headline,
        contributions=(*quote.explanation.contributions, *contributions),
        evidence=quote.explanation.evidence,
        confidence=quote.explanation.confidence,
        confidence_reason=(
            quote.explanation.confidence_reason
            + " Human overrides were applied on top of this band (Step 6.6)."
        ),
        fallbacks_used=tuple(fallbacks),
    )

    return quote.model_copy(
        update={
            "floor": floor,
            "target": target,
            "cap": cap,
            "recommended": recommended,
            "human_overrides": dict(overrides),
            "explanation": new_explanation,
        }
    )
