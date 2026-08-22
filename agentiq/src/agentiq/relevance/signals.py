"""Step 5.2 — Multi-signal relevance score, one function per named signal.

Every function returns a plain `float` in `[0, 1]`; `agentiq.relevance`
composes them into the weighted score and the `Explanation`'s
`Contribution`s. Kept this way (mirroring `pricing/demand.py`'s pattern) so
each signal is independently unit-testable and the blend formula lives in
exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from agentiq.domain.campaign import CampaignBrief
from agentiq.domain.enums import CampaignObjective, IndustryVertical, MountPosition
from agentiq.domain.inventory import AudienceProfile, Screen

#: `zone_demographics` age-band columns and the [min, max) age range each covers.
#: `55_plus` is treated as capped at 100 for overlap arithmetic — no real
#: campaign states an upper bound above that.
AGE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("pct_age_under_18", 0.0, 18.0),
    ("pct_age_18_34", 18.0, 35.0),
    ("pct_age_35_54", 35.0, 55.0),
    ("pct_age_55_plus", 55.0, 100.0),
)

#: Dwell-oriented mount positions — a waiting audience, not a passer-by glimpse
#: (Step 3.1's visibility modifier already treats these as higher-attention).
DWELL_POSITIONS: frozenset[str] = frozenset(
    {MountPosition.PLATFORM.value, MountPosition.ENTRANCE_EXIT.value}
)


def _age_overlap_fraction(
    band_min: float, band_max: float, target_min: float, target_max: float
) -> float:
    overlap = max(0.0, min(band_max, target_max) - max(band_min, target_min))
    band_width = band_max - band_min
    return overlap / band_width if band_width > 0 else 0.0


def audience_affinity(
    brief: CampaignBrief,
    age_band_pct: dict[str, float] | None,
) -> float:
    """Fraction of the local population inside `[target_age_min, target_age_max]`.

    *age_band_pct* is the zone's (or, for mobile screens with no zone, the
    city-average) `pct_age_*` columns as a `{column: percent}` dict. `None`
    means no demographic reference at all — returns a neutral 0.5 rather
    than guessing a direction.
    """
    if brief.target_age_min is None or brief.target_age_max is None or age_band_pct is None:
        return 0.5

    total = 0.0
    for column, band_min, band_max in AGE_BANDS:
        pct = age_band_pct.get(column, 0.0) / 100.0
        overlap = _age_overlap_fraction(
            band_min, band_max, float(brief.target_age_min), float(brief.target_age_max)
        )
        total += pct * overlap
    return max(0.0, min(total, 1.0))


def daypart_alignment(brief: CampaignBrief, profile: AudienceProfile) -> float:
    """Share of the screen's exposure falling in the brief's requested time blocks.

    No requested blocks means no stated preference — returns neutral 1.0
    (this signal does not penalise a brief that never asked for a daypart).
    `weekend_weighting`, if stated, blends the weekday/weekend curves rather
    than picking one exclusively.
    """
    if not brief.time_block_ids:
        return 1.0

    weekday_share = sum(profile.daypart_weight_weekday.get(b, 0.0) for b in brief.time_block_ids)
    weekend_share = sum(profile.daypart_weight_weekend.get(b, 0.0) for b in brief.time_block_ids)
    if brief.weekend_weighting is None:
        return max(0.0, min((weekday_share + weekend_share) / 2.0, 1.0))
    w = brief.weekend_weighting
    return max(0.0, min(w * weekend_share + (1.0 - w) * weekday_share, 1.0))


def environment_poi_fit(brief: CampaignBrief, profile: AudienceProfile) -> float:
    """Fraction of the brief's requested environment types this screen actually carries.

    No requested environment types means no stated preference — neutral 1.0.
    """
    if not brief.requested_environment_types:
        return 1.0
    requested = set(brief.requested_environment_types)
    matched = requested & set(profile.environment_labels)
    return len(matched) / len(requested)


def objective_fit(
    brief: CampaignBrief,
    screen: Screen,
    profile: AudienceProfile,
    *,
    industry_environment_affinity: dict[str, tuple[str, ...]],
    normalised_exposure: float,
) -> float:
    """Objective-specific fit, blending industry-preferred environments with an
    objective-shaped bonus (solution_plan.md Step 5.2):

    - awareness/reach favour breadth/high-exposure nodes -> rewards raw exposure.
    - conversion favours proximity to the point of purchase -> weights the
      environment-affinity match itself more heavily (retail/mall environments
      already carry that signal).
    - frequency favours captive, repeat-exposure inventory -> rewards dwell
      positions and interior mobile placements.
    """
    preferred = set(industry_environment_affinity.get(brief.industry_vertical.value, ()))
    affinity = (
        len(preferred & set(profile.environment_labels)) / len(preferred) if preferred else 0.5
    )

    if brief.objective in (CampaignObjective.AWARENESS, CampaignObjective.REACH):
        bonus = normalised_exposure
    elif brief.objective is CampaignObjective.CONVERSION:
        bonus = affinity
    else:  # FREQUENCY
        is_captive = screen.is_mobile and screen.position is None
        is_dwell = screen.position is not None and screen.position.value in DWELL_POSITIONS
        bonus = 1.0 if (is_captive or is_dwell) else 0.4

    return max(0.0, min(0.6 * affinity + 0.4 * bonus, 1.0))


def historical_performance_prior(
    screen_id: str,
    industry_vertical: IndustryVertical,
    settled_by_screen_and_vertical: dict[tuple[str, str], int],
    *,
    min_bookings_for_full_weight: int,
) -> float:
    """Ramps 0 -> 1 as this screen's settled-booking count in this vertical rises
    to `min_bookings_for_full_weight`, never above — deliberately down-weighted
    (small config weight, not this function) so a screen with zero history
    scores 0 here rather than being penalised further; Step 5.2's rule is that
    this signal must never bury a cold-start screen.
    """
    count = settled_by_screen_and_vertical.get((screen_id, industry_vertical.value), 0)
    if min_bookings_for_full_weight <= 0:
        return 0.0
    return max(0.0, min(count / min_bookings_for_full_weight, 1.0))


@dataclass(frozen=True)
class SignalPrecompute:
    """Repository-derived lookups built once per `RelevanceEngine` (offline),
    so per-screen scoring stays a cheap dict lookup (design principle 5)."""

    zone_age_bands: dict[str, dict[str, float]]
    city_age_bands: dict[str, dict[str, float]]
    settled_by_screen_and_vertical: dict[tuple[str, str], int]
    exposure_reference_p95: float


def build_signal_precompute(
    zone_demographics: pd.DataFrame,
    locations: pd.DataFrame,
    settled_bookings: pd.DataFrame,
    exposure_by_screen: dict[str, float],
) -> SignalPrecompute:
    age_columns = [c for c, _, _ in AGE_BANDS]
    zone_age_bands = {
        row["zone_id"]: {c: float(row[c]) for c in age_columns}
        for _, row in zone_demographics.iterrows()
    }

    zone_by_city: dict[str, list[str]] = {}
    for _, row in zone_demographics.iterrows():
        zone_by_city.setdefault(row["city_id"], []).append(row["zone_id"])
    city_age_bands: dict[str, dict[str, float]] = {}
    for city_id, zone_ids in zone_by_city.items():
        rows = zone_demographics.loc[zone_demographics["zone_id"].isin(zone_ids)]
        city_age_bands[city_id] = {c: float(rows[c].mean()) for c in age_columns}

    counts = (
        settled_bookings.groupby(["screen_id", "industry_vertical"], observed=True)
        .size()
        .to_dict()
    )
    settled_by_screen_and_vertical = {(k[0], str(k[1])): int(v) for k, v in counts.items()}

    exposures = sorted(exposure_by_screen.values())
    exposure_reference_p95 = (
        exposures[int(len(exposures) * 0.95)] if exposures else 1.0
    ) or 1.0

    return SignalPrecompute(
        zone_age_bands=zone_age_bands,
        city_age_bands=city_age_bands,
        settled_by_screen_and_vertical=settled_by_screen_and_vertical,
        exposure_reference_p95=exposure_reference_p95,
    )


__all__ = [
    "AGE_BANDS",
    "DWELL_POSITIONS",
    "SignalPrecompute",
    "audience_affinity",
    "build_signal_precompute",
    "daypart_alignment",
    "environment_poi_fit",
    "historical_performance_prior",
    "objective_fit",
]
