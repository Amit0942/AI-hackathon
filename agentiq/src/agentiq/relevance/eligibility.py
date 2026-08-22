"""Step 5.1 — Hard-constraint filter.

Cheap, exact eligibility checks applied before any scoring, so the expensive
Step 5.2 signals only ever run on a candidate a brief could actually book.
Every screen gets a reason, eligible or not — "the UI shows 'excluded:
bus-rear, brief excludes bus-rear' and that is a trust win" (solution_plan.md
Phase 5.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from agentiq.data.occupancy import committed_occupancy_share, occupancy_events
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.campaign import CampaignBrief, GeographyConstraint
from agentiq.domain.inventory import MAX_ROTATION_SLOTS, TIME_BLOCK_IDS, Screen


@dataclass(frozen=True)
class EligibilityResult:
    """One screen's eligibility verdict for one brief, with a stated reason either way."""

    screen_id: str
    eligible: bool
    reasons: tuple[str, ...]


def _screen_zone_name(screen: Screen, repos: InMemoryRepositories) -> str | None:
    if not screen.is_static or screen.location_id is None:
        return None
    zone = repos.geography.zone_for_location(screen.location_id)
    return zone["zone_name"] if zone is not None else None


def _screen_matches_geography(
    screen: Screen,
    constraint: GeographyConstraint,
    repos: InMemoryRepositories,
) -> bool:
    if screen.city_id != constraint.city_id:
        return False
    if constraint.zone_name is not None:
        if _screen_zone_name(screen, repos) != constraint.zone_name:
            return False
    if constraint.poi_type is not None and constraint.radius_km is not None:
        if not screen.is_static or screen.location_id is None:
            return False
        pois = repos.context.pois_near(screen.location_id, constraint.radius_km)
        if pois.empty or not (pois["poi_type"].astype(str) == constraint.poi_type).any():
            return False
    return True


def _parse_type_exclusion(rule: str) -> tuple[str, str | None]:
    """`'bus'` -> `('bus', None)`; `'bus:back'` -> `('bus', 'back')` — see
    `domain/campaign.py`'s `screen_type_exclusions` convention."""
    if ":" in rule:
        screen_type, position = rule.split(":", 1)
        return screen_type.strip(), position.strip()
    return rule.strip(), None


def _has_capacity(
    screen: Screen,
    brief: CampaignBrief,
    occupancy: pd.DataFrame,
    on_date: date,
) -> bool:
    blocks = brief.time_block_ids or TIME_BLOCK_IDS
    return any(
        committed_occupancy_share(occupancy, screen.screen_id, block, on_date) < 1.0
        for block in blocks
    )


def eligible_screens(
    brief: CampaignBrief,
    screens: tuple[Screen, ...],
    repos: InMemoryRepositories,
    *,
    check_availability: bool = True,
) -> tuple[EligibilityResult, ...]:
    """Evaluate every screen in *screens* against *brief*'s hard constraints.

    Availability is a **coarse, single-date gate** (checked at `brief.start_date`
    only, across the brief's requested time blocks or all six if none stated) —
    a stated simplification. Exact slot-by-slot, day-by-day allocation across
    the full flight is Phase 7's (D4) job, not Phase 5's; this only removes a
    screen already fully committed on day one of the flight, which no
    optimizer could ever legally allocate anyway.
    """
    required = tuple(c for c in brief.geography_constraints if not c.is_exclusion)
    excluded_geo = tuple(c for c in brief.geography_constraints if c.is_exclusion)
    type_exclusions = tuple(_parse_type_exclusion(r) for r in brief.screen_type_exclusions)

    occupancy = None
    if check_availability and brief.start_date is not None:
        occupancy = occupancy_events(repos.bookings.committed())

    results: list[EligibilityResult] = []
    for screen in screens:
        reasons: list[str] = []
        eligible = True

        if required and not any(_screen_matches_geography(screen, c, repos) for c in required):
            eligible = False
            reasons.append(
                f"outside every stated geography requirement "
                f"({', '.join(c.city_id for c in required)})"
            )

        for exclusion in excluded_geo:
            if _screen_matches_geography(screen, exclusion, repos):
                eligible = False
                label = exclusion.zone_name or exclusion.poi_type or exclusion.city_id
                reasons.append(f"excluded geography: {label}")

        for screen_type, position in type_exclusions:
            position_matches = position is None or (
                screen.position is not None and screen.position.value == position
            )
            if screen.screen_type.value == screen_type and position_matches:
                rule = screen_type if position is None else f"{screen_type}:{position}"
                eligible = False
                reasons.append(f"excluded screen type/position: {rule}")

        if eligible and occupancy is not None and brief.start_date is not None:
            if not _has_capacity(screen, brief, occupancy, brief.start_date):
                eligible = False
                reasons.append(
                    f"no capacity in any requested time block on {brief.start_date} "
                    f"(all {MAX_ROTATION_SLOTS} slots committed)"
                )

        if eligible and not reasons:
            reasons.append("meets all stated geography, exclusion, and availability constraints")

        results.append(EligibilityResult(screen.screen_id, eligible, tuple(reasons)))

    return tuple(results)


__all__ = ["EligibilityResult", "eligible_screens"]
