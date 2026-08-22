"""Step 3.5 — Impression & reach model, honestly (concavity + sub-additivity).

Two pure, property-tested functions carry the whole nuance the plan calls
out:

* `impressions` — exposure x slot share x an attention factor with
  **diminishing returns**: `slots ** alpha` (0 < alpha < 1) is strictly
  concave, so doubling the slot count on one screen never doubles
  impressions. This is the Step 3.5 exit criterion, proven directly by the
  functional form rather than checked empirically after the fact.
* `unique_reach` — a saturating curve, `scale * (1 - exp(-x / scale))`,
  which is concave and passes through the origin, so it is *automatically*
  sub-additive: `reach(a + b) <= reach(a) + reach(b)` for any `a, b >= 0`.
  The overlap graph (Step 3.4) feeds in as a *further* discount on the raw
  impressions total before the curve is applied — de-duplicating shared
  audience on top of the curve's own saturation, never instead of it.

Both engines reusable by D4's optimizer (Phase 7) without modification —
the reach math does not belong exclusively to either phase.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from agentiq.audience.overlap import OverlapGraph, overlap_for
from agentiq.domain.enums import Confidence
from agentiq.domain.explanation import Contribution, Explanation
from agentiq.domain.optimizer import ReachEstimate


def attention_factor(slots: int, *, alpha: float) -> float:
    """`slots ** alpha`, 0 < alpha < 1 — concave, `attention_factor(1) == 1.0`."""
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if slots < 1:
        raise ValueError(f"slots must be >= 1, got {slots}")
    return float(slots) ** alpha


def impressions(exposure_for_block: float, slots: int, *, alpha: float) -> float:
    """Gross impressions for one screen x time-block x slot-count.

    Concavity (Step 3.5 exit criterion): `impressions(2*slots) < 2 *
    impressions(slots)` for any `slots >= 1`, because `attention_factor` is
    strictly concave and `exposure_for_block` does not itself depend on
    `slots`.
    """
    if exposure_for_block < 0:
        raise ValueError("exposure_for_block must be non-negative")
    return exposure_for_block * attention_factor(slots, alpha=alpha)


def effective_exposure(
    screen_impressions: Mapping[str, float],
    overlap_graph: OverlapGraph,
) -> float:
    """Total impressions after discounting the portion double-counted by
    screens known to share audience (Step 3.4's overlap graph).

    For each overlapping pair, the smaller of the two screens' impressions
    is treated as (partially) redundant with the larger — `overlap * min(a,
    b)` is removed from the naive sum. This can only reduce the total, so
    `effective_exposure(...) <= sum(screen_impressions.values())` always,
    which is what carries sub-additivity through to `unique_reach` below.
    """
    ids = list(screen_impressions)
    total = sum(screen_impressions.values())
    discount = 0.0
    for i, screen_a in enumerate(ids):
        for screen_b in ids[i + 1 :]:
            coefficient = overlap_for(overlap_graph, screen_a, screen_b)
            if coefficient > 0:
                discount += coefficient * min(
                    screen_impressions[screen_a], screen_impressions[screen_b]
                )
    return max(total - discount, 0.0)


def unique_reach(effective_exposure_value: float, *, scale: float) -> float:
    """Saturating de-duplication curve, concave and zero at zero.

    Sub-additivity (Step 3.5 exit criterion): for any `a, b >= 0`,
    `unique_reach(a + b) <= unique_reach(a) + unique_reach(b)` — a standard
    property of a concave function vanishing at the origin, verified
    directly by property test rather than assumed.
    """
    if effective_exposure_value < 0:
        raise ValueError("effective_exposure_value must be non-negative")
    if scale <= 0:
        raise ValueError("scale must be positive")
    return scale * (1.0 - math.exp(-effective_exposure_value / scale))


def reach_estimate_for_group(
    screen_impressions: Mapping[str, float],
    overlap_graph: OverlapGraph,
    *,
    reach_saturation_scale: float,
) -> ReachEstimate:
    """Assemble one `ReachEstimate` for a group of screens (e.g. a package line
    set, or all screens in one corridor/station cluster)."""
    gross = sum(screen_impressions.values())
    effective = effective_exposure(screen_impressions, overlap_graph)
    reach = unique_reach(effective, scale=reach_saturation_scale)
    frequency = gross / reach if reach > 0 else 0.0

    overlap_discount_pct = 1.0 - (effective / gross) if gross > 0 else 0.0
    contributions = (
        Contribution(
            signal="gross_impressions",
            direction="positive" if gross > 0 else "neutral",
            weight=0.6,
            magnitude=gross,
            detail=f"Sum of per-screen impressions across {len(screen_impressions)} screen(s).",
        ),
        Contribution(
            signal="overlap_deduplication",
            direction="negative" if overlap_discount_pct > 0 else "neutral",
            weight=0.4,
            magnitude=-overlap_discount_pct * gross if overlap_discount_pct > 0 else 0.0,
            detail=(
                f"{overlap_discount_pct:.1%} of gross impressions discounted as shared "
                "audience (Step 3.4 overlap graph) before the saturation curve."
            ),
        ),
    )
    explanation = Explanation(
        headline=(
            f"{reach:,.0f} unique reach from {gross:,.0f} gross impressions "
            f"({frequency:.2f}x average frequency)."
        ),
        contributions=contributions,
        confidence=Confidence.MEDIUM,
        confidence_reason=(
            "Reach uses a saturating de-duplication curve calibrated to a stated scale "
            "constant, not a directly measured unique-visitor count (none exists in the "
            "raw data) — medium confidence by construction."
        ),
    )
    return ReachEstimate(
        gross_impressions=gross,
        unique_reach=reach,
        frequency=frequency,
        explanation=explanation,
    )


__all__ = [
    "attention_factor",
    "effective_exposure",
    "impressions",
    "reach_estimate_for_group",
    "unique_reach",
]
