"""Step 6.3 (price band) + Step 6.5 (cold-start fallback ladder).

The two are implemented together because the ladder decides *which rows*
the base rate is computed from before the band (floor/target/cap) is built
around it — a rung is not a separate price, it is a choice of evidence.

Ladder rungs (Step 6.5, ordered strongest evidence first; cohort membership
matches `docs/decisions/1.7_dq_register_and_coldstart.md` §4 exactly):

1. `screen_own_history`                    — this screen's own settled bookings.
2. `peer_screens_same_location_or_corridor` — other screens at the same location/corridor.
3. `cohort_zone_type_position_size`         — zone x screen_type x position x screen_size cohort.
4. `city_screen_type_baseline`              — city x screen_type baseline, market-tier adjusted.
5. `global_rate_card`                       — network-wide rule-based rate from physical attributes.

Each rung is tried in order; the first with enough rows (>= `MIN_ROWS_PER_RUNG`)
wins. This is what Step 1.7 §4 predicted would work: cold-start is a pure
commercial-history gap, so a screen with no history "looks like dozens of
other ... screens, not like an isolated anomaly."
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from agentiq.domain.enums import ColdStartRung
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation
from agentiq.domain.inventory import Screen
from agentiq.domain.pricing import DemandSignal, PriceQuote
from agentiq.pricing.base_rate import POSITION_NONE, TARGET_COLUMN, FittedBaseRateModel
from agentiq.pricing.win_probability import UNKNOWN_TIER, FittedWinModel, recommend_price

#: Below this row count, a rung's evidence is too thin to trust — fall
#: through to the next rung rather than fit on noise.
MIN_ROWS_PER_RUNG = 20


@dataclass(frozen=True)
class PriceBandConfig:
    """Guardrail parameters, loaded from `config/pricing.yaml` (never hardcoded)."""

    floor_percentile: float
    margin_floor_pct: float
    #: Cap gap when a real `client_target_price` is supplied — 1.5 §6.2's
    #: measured willingness-to-pay ceiling, applied to the reference point
    #: it was actually measured against.
    cap_gap_pct_vs_client_target: float
    #: Cap gap when no client target exists (today's default path) — fit
    #: from the base-rate model's own residual dispersion, a different and
    #: larger source of uncertainty than the client-negotiation gap above.
    cap_gap_pct_vs_base_rate: float
    max_uplift_pct: float
    max_discount_pct: float


def select_cold_start_rung(
    screen: Screen,
    settled_bookings: pd.DataFrame,
    cohort_screen_ids: dict[ColdStartRung, tuple[str, ...]],
) -> tuple[ColdStartRung, pd.DataFrame]:
    """Walk the ladder, returning the first rung with enough settled-booking rows.

    *cohort_screen_ids* maps the two screen-set rungs
    (`PEER_SCREENS_SAME_LOCATION_OR_CORRIDOR`, `COHORT_ZONE_TYPE_POSITION_SIZE`)
    to the screen IDs that belong to that cohort — computed once by the
    caller from `screens`/`locations`/`zone_demographics` (this module never
    reads those tables directly; it only consumes the resulting ID sets, per
    the repository-protocol boundary in CLAUDE.md).
    """
    own = settled_bookings.loc[settled_bookings["screen_id"] == screen.screen_id]
    if len(own) >= MIN_ROWS_PER_RUNG:
        return ColdStartRung.SCREEN_OWN_HISTORY, own

    peer_ids = cohort_screen_ids.get(ColdStartRung.PEER_SCREENS_SAME_LOCATION_OR_CORRIDOR, ())
    peers = settled_bookings.loc[settled_bookings["screen_id"].isin(peer_ids)]
    if len(peers) >= MIN_ROWS_PER_RUNG:
        return ColdStartRung.PEER_SCREENS_SAME_LOCATION_OR_CORRIDOR, peers

    cohort_ids = cohort_screen_ids.get(ColdStartRung.COHORT_ZONE_TYPE_POSITION_SIZE, ())
    cohort = settled_bookings.loc[settled_bookings["screen_id"].isin(cohort_ids)]
    if len(cohort) >= MIN_ROWS_PER_RUNG:
        return ColdStartRung.COHORT_ZONE_TYPE_POSITION_SIZE, cohort

    city_type = settled_bookings.loc[
        (settled_bookings["city_id"] == screen.city_id)
        & (settled_bookings["screen_type"] == screen.screen_type.value)
    ]
    if len(city_type) >= MIN_ROWS_PER_RUNG:
        return ColdStartRung.CITY_SCREEN_TYPE_BASELINE, city_type

    network_type = settled_bookings.loc[settled_bookings["screen_type"] == screen.screen_type.value]
    return ColdStartRung.GLOBAL_RATE_CARD, network_type


def compute_floor(comparable_rows: pd.DataFrame, config: PriceBandConfig) -> float:
    """Cost-and-dignity guard: a low percentile of comparable realised prices.

    Step 6.3: "never below a configured margin floor" — `margin_floor_pct`
    is applied as a multiplicative guard against the percentile collapsing
    to near-zero on a thin or unusually cheap cohort.
    """
    prices = comparable_rows[TARGET_COLUMN].dropna()
    if prices.empty:
        raise ValueError("compute_floor requires at least one comparable priced row")
    percentile_floor = float(prices.quantile(config.floor_percentile))
    margin_floor = float(prices.median()) * config.margin_floor_pct
    return max(percentile_floor, margin_floor)


def compute_cap(
    base_rate: float,
    config: PriceBandConfig,
    *,
    client_target_price: float | None = None,
) -> float:
    """Willingness-to-pay guard, calibrated against the lost-leads price-gap evidence.

    Two reference points, two constants (ADR-0003 decision 5, amended after
    the Phase 6 back-test quantified the gap between them):

    - *client_target_price* given -> apply `cap_gap_pct_vs_client_target`
      (0.15) to it directly. This is exactly the quantity 1.5 §6.2 measured
      (deals survive to verbal-agreement-or-later 38-48% of the time up to a
      15% gap over client target, collapsing above it), so the cap means
      what the evidence says it means.
    - *client_target_price* is None -> apply `cap_gap_pct_vs_base_rate`
      (0.35) to the base rate instead. This is a *different* uncertainty:
      the base-rate model's own residual dispersion ($22.59 std, R^2=0.62
      on held-out data), not client willingness-to-pay. Using the
      client-target figure (0.15) here back-tested at only 65.9% band
      coverage — the cap rejected 24.4% of realised prices as impossible.
      0.35 is the base rate's own train-fit p90 residual, validated
      out-of-sample. The substitution is surfaced in
      `Explanation.fallbacks_used` by `_band_explanation`, never silent.
    """
    if client_target_price is not None:
        return client_target_price * (1.0 + config.cap_gap_pct_vs_client_target)
    return base_rate * (1.0 + config.cap_gap_pct_vs_base_rate)


def compute_target(base_rate: float, demand_index: float, config: PriceBandConfig) -> float:
    """base x demand multiplier, clamped by the single-factor uplift/discount caps (Step 6.3).

    `demand_index` is centred at 1.0 (`DemandSignal.index`'s contract), so
    `(demand_index - 1.0)` is the raw uplift/discount fraction before
    clamping. Relevance premium and client-relationship adjustment are not
    yet inputs here (Step 6.4/6.6, deferred per ADR-0003) — `target` is
    base x demand only for this pass, and that narrowing is stated in the
    `Explanation.fallbacks_used`, not hidden.
    """
    raw_adjustment = demand_index - 1.0
    clamped_adjustment = max(-config.max_discount_pct, min(config.max_uplift_pct, raw_adjustment))
    return base_rate * (1.0 + clamped_adjustment)


def _band_explanation(
    *,
    rung: ColdStartRung,
    base_rate: float,
    demand_index: float,
    floor: float,
    target: float,
    cap: float,
    recommended: float,
    n_comparable_rows: int,
    base_rate_contributions: list[tuple[str, float]] | None,
    win_probability: float | None,
    win_model_rows: int | None,
    used_client_target: bool,
    competitor_mentioned: bool,
) -> Explanation:
    contributions = []
    if base_rate_contributions:
        total_abs = sum(abs(v) for _, v in base_rate_contributions) or 1.0
        for name, value in sorted(base_rate_contributions, key=lambda kv: abs(kv[1]), reverse=True)[
            :5
        ]:
            direction = "positive" if value > 0 else ("negative" if value < 0 else "neutral")
            contributions.append(
                Contribution(
                    signal=f"base_rate:{name}",
                    direction=direction,
                    weight=min(abs(value) / total_abs, 1.0),
                    magnitude=value,
                    detail="Coefficient x feature value from the Step 6.3 base-rate model.",
                )
            )

    demand_delta = target - base_rate
    if demand_delta > 0:
        demand_direction = "positive"
    elif demand_delta < 0:
        demand_direction = "negative"
    else:
        demand_direction = "neutral"
    contributions.append(
        Contribution(
            signal="demand_multiplier",
            direction=demand_direction,
            weight=0.5,
            magnitude=demand_delta,
            detail=f"demand_index={demand_index:.2f}, applied to base rate, clamped by config.",
        )
    )

    # Step 6.4: the recommended price is the expected-value optimum, which
    # may sit below target when the win curve falls faster than price rises.
    if win_probability is not None:
        recommendation_delta = recommended - target
        if recommendation_delta > 0:
            rec_direction = "positive"
        elif recommendation_delta < 0:
            rec_direction = "negative"
        else:
            rec_direction = "neutral"
        contributions.append(
            Contribution(
                signal="win_probability_optimum",
                direction=rec_direction,
                weight=0.5,
                magnitude=recommendation_delta,
                detail=(
                    f"argmax(price x P(win)) inside the band: P(win)={win_probability:.2f} "
                    f"at the recommended price. Moved {recommendation_delta:+.2f} off target."
                ),
            )
        )

    fallbacks: list[str] = []
    if rung is not ColdStartRung.SCREEN_OWN_HISTORY:
        fallbacks.append(f"cold_start_rung:{rung.value}")
    if win_probability is None:
        fallbacks.append("recommended_equals_target_no_win_model_available")
    elif abs(recommended - floor) < 1e-9:
        # Not a defect — see `recommend_price`'s docstring. Demand is elastic
        # enough across the band that expected value falls monotonically, so
        # the margin floor is the binding constraint on the recommendation.
        # A rep should see that the guardrail bound, not just the number.
        fallbacks.append("recommendation_pinned_to_margin_floor_demand_is_elastic")
    if not used_client_target:
        # ADR-0003 decision 5: 1.5 §6.2's gap is measured against the
        # client's target price. Absent one, we substitute the band target —
        # a different reference point, stated rather than silently equated.
        fallbacks.append("cap_relative_to_base_rate_not_client_target")

    evidence = [
        EvidenceRef(
            table="bookings",
            row_key={"cold_start_rung": rung.value},
            field=TARGET_COLUMN,
            value=round(base_rate, 2),
            note=f"Base rate fit on {n_comparable_rows} settled rows at this ladder rung.",
        )
    ]
    if win_probability is not None and win_model_rows is not None:
        evidence.append(
            EvidenceRef(
                table="lost_leads",
                row_key={"competitor_mentioned": str(competitor_mentioned)},
                field="price_gap_pct",
                value=round(win_probability, 3),
                note=(
                    f"P(win) from the Step 6.4 logistic fit on {win_model_rows} lost leads "
                    "with a non-null price gap (1.5 §6.2 survival curve, 1.5 §6.5 competitor term)."
                ),
            )
        )

    headline = (
        f"Priced from {rung.value} ({n_comparable_rows} comparable rows): "
        f"floor={floor:.2f}, target={target:.2f}, cap={cap:.2f}."
    )
    if win_probability is not None:
        headline += f" Recommended {recommended:.2f} at P(win)={win_probability:.0%}."

    return Explanation(
        headline=headline,
        contributions=tuple(contributions),
        evidence=tuple(evidence),
        confidence=rung.default_confidence,
        confidence_reason=(
            f"Cold-start ladder rung '{rung.value}' — "
            f"{rung.default_confidence.value} confidence is this rung's stated default (Step 6.5)."
        ),
        fallbacks_used=tuple(fallbacks),
    )


def build_price_quote(
    screen: Screen,
    time_block_id: int,
    slots: int,
    demand_signal: DemandSignal,
    rung: ColdStartRung,
    comparable_rows: pd.DataFrame,
    config: PriceBandConfig,
    *,
    fitted_model: FittedBaseRateModel | None = None,
    win_model: FittedWinModel | None = None,
    client_target_price: float | None = None,
    competitor_mentioned: bool = False,
    client_tier: str = UNKNOWN_TIER,
) -> PriceQuote:
    """Assemble the Step 6.3 floor/target/cap band into a `PriceQuote`.

    If *fitted_model* is given, the base rate is that model's prediction for
    this exact row (interpretable, attributable per-feature); otherwise the
    median of *comparable_rows* is used — the Step 6.5 rungs with too few
    rows to fit a stable regression on (`GLOBAL_RATE_CARD`, thin cohorts)
    fall back to a median, which is itself the "global rule-based rate card"
    the plan names for the last rung.

    If *win_model* is given, `recommended` is Step 6.4's expected-value
    optimum — `argmax(price x P(win))` searched inside `[floor, cap]`, so the
    band invariant holds by construction. Without one, `recommended` falls
    back to `target` and the explanation says so.

    *client_target_price* is **optional**, mirroring ADR-0003 decision 6's
    treatment of `segment_heat`: supplied, the price gap is computed against
    it exactly as `lost_leads.price_gap_pct` defines it, and the cap means
    what 1.5 §6.2 measured; absent, the band target stands in as the
    reference and the substitution is recorded in `fallbacks_used`.
    """
    contributions: list[tuple[str, float]] | None = None
    if fitted_model is not None:
        row = pd.Series(
            {
                "time_block_id": time_block_id,
                "screen_size": screen.screen_size.value,
                "screen_type": screen.screen_type.value,
                "city_id": screen.city_id,
                # `rotation_type` is no longer a model feature — it partitions
                # `slots_booked_per_day` exactly (1.4 §1.3). See base_rate.py.
                "position": screen.position.value if screen.position else POSITION_NONE,
                "slots_booked_per_day": slots,
            }
        )
        base_rate = fitted_model.predict_one(row)
        contributions = fitted_model.contributions(row)
    else:
        base_rate = float(comparable_rows[TARGET_COLUMN].median())

    # A regression can, in principle, extrapolate to an implausible or
    # non-positive rate on a thin/unusual cohort; guard with the same
    # comparable-rows median as a sanity floor before banding.
    median_comparable = float(comparable_rows[TARGET_COLUMN].median())
    if base_rate <= 0 or base_rate > median_comparable * 3:
        base_rate = median_comparable

    floor = compute_floor(comparable_rows, config)
    target = compute_target(base_rate, demand_signal.index, config)
    cap = compute_cap(base_rate, config, client_target_price=client_target_price)

    # Re-order defensively: config-driven percentiles/caps computed
    # independently of `target` could in principle straddle it on a thin
    # cohort — clamp rather than let the PriceQuote invariant raise.
    floor = min(floor, target)
    cap = max(cap, target)

    # Step 6.4 — expected-value optimum inside the band.
    win_probability: float | None = None
    win_model_rows: int | None = None
    recommended = target
    if win_model is not None:
        reference = client_target_price if client_target_price is not None else target
        recommended, win_probability, _curve = recommend_price(
            win_model,
            floor=floor,
            cap=cap,
            reference_price=reference,
            competitor_mentioned=competitor_mentioned,
            client_tier=client_tier,
        )
        win_model_rows = win_model.n_training_rows

    explanation = _band_explanation(
        rung=rung,
        base_rate=base_rate,
        demand_index=demand_signal.index,
        floor=floor,
        target=target,
        cap=cap,
        recommended=recommended,
        n_comparable_rows=len(comparable_rows),
        base_rate_contributions=contributions,
        win_probability=win_probability,
        win_model_rows=win_model_rows,
        used_client_target=client_target_price is not None,
        competitor_mentioned=competitor_mentioned,
    )

    return PriceQuote(
        screen_id=screen.screen_id,
        time_block_id=time_block_id,
        slots=slots,
        floor=floor,
        target=target,
        cap=cap,
        recommended=recommended,
        # 0.5 (neutral) only when no win model was supplied; otherwise the
        # fitted P(near-win) at the recommended price. See
        # `win_probability.py` on what "win" is calibrated against.
        win_probability_at_recommended=win_probability if win_probability is not None else 0.5,
        cold_start_rung=rung,
        confidence=rung.default_confidence,
        explanation=explanation,
    )
