"""Pure scoring functions for one rep's sales — no repository/engine dependency,
independently unit-testable (mirrors `pricing/demand.py`'s pattern).
"""

from __future__ import annotations

from agentiq.domain.rep import RepSale


def margin_score(sale: RepSale) -> float:
    """1.0 = sold at/above the D3 `target`; 0.0 = sold at the `floor`.

    A sale below the floor or above the cap is a real anomaly (a rep
    overriding D3's own guardrail) — clamped into `[0, 1]` here so the
    blend stays well-defined, but the caller is responsible for surfacing
    the anomaly in the `Explanation` rather than this function silently
    hiding it.
    """
    quote = sale.price_quote
    span = quote.target - quote.floor
    if span <= 0:
        # floor == target on a razor-thin band (Step 6's own documented
        # possibility) — any price at or above it is a full-margin sale.
        return 1.0 if sale.sold_price >= quote.target else 0.0
    return max(0.0, min((sale.sold_price - quote.floor) / span, 1.0))


def is_price_anomaly(sale: RepSale) -> bool:
    """True when the rep sold outside D3's own [floor, cap] band entirely."""
    return sale.sold_price < sale.price_quote.floor or sale.sold_price > sale.price_quote.cap


def target_attainment_ratio(total_revenue: float, target_revenue: float) -> float:
    """Uncapped revenue/target ratio — capping happens only in the blend, so
    `RepPerformance.target_attainment_pct` always reports the true number."""
    if target_revenue <= 0:
        return 0.0
    return total_revenue / target_revenue


def blend_rep_score(
    average_margin_score: float,
    attainment_ratio: float,
    *,
    attainment_cap: float,
    margin_weight: float,
    attainment_weight: float,
) -> float:
    """`margin_weight * average_margin_score + attainment_weight * capped_attainment`.

    `capped_attainment = min(attainment_ratio, attainment_cap) / attainment_cap`,
    itself in `[0, 1]`, so the blend is always in `[0, 1]` whenever the two
    weights sum to 1.0 (`config/rep_scoring.yaml`'s convention, not enforced
    here — a caller changing the weights is responsible for keeping them
    normalised).
    """
    if attainment_cap <= 0:
        raise ValueError("attainment_cap must be positive")
    capped_attainment = min(attainment_ratio, attainment_cap) / attainment_cap
    return margin_weight * average_margin_score + attainment_weight * capped_attainment


__all__ = [
    "blend_rep_score",
    "is_price_anomaly",
    "margin_score",
    "target_attainment_ratio",
]
