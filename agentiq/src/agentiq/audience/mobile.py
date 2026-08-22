"""Step 3.2 — Mobile exposure model (vehicle-mounted screens).

A moving screen's audience is a journey, not a point: the weighted union of
the stops/segments the vehicle's corridor traverses, scaled by trip
frequency by day type, with the dwell-time split the plan calls for —
"interior reaches captive riders, exterior reaches street pedestrians and
adjacent traffic" (`metro_rail_coach` panels have no `position`, i.e. no
mount face — Step 1.1 confirms this is always interior; `bus` screens are
always exterior-mounted, `left`/`right`/`top`/`back`).

Exit criteria (solution_plan.md Phase 3.2): mobile and static exposure land
on a comparable scale. Both models' raw units are "people reached per day"
built from the same primitives (resident/daytime population, POI footfall,
ridership) — no separate rescaling constant is introduced here; comparability
is a property of sharing those primitives, not a post-hoc normalisation.
"""

from __future__ import annotations

from agentiq.audience.config import AudienceConfig
from agentiq.audience.daypart import DEFAULT_DAYPART_SHARE
from agentiq.audience.poi import poi_pull_by_block
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.enums import Confidence, MarketTier
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation
from agentiq.domain.inventory import TIME_BLOCK_IDS, AudienceProfile, Screen

_DAY_TYPES: tuple[str, ...] = ("weekday", "weekend")
_WEEKDAY_WEIGHT = 5.0 / 7.0
_WEEKEND_WEIGHT = 2.0 / 7.0

#: `corridor_id -> {day_type -> {time_block_id -> avg per-stop external pull}}`,
#: shared across every vehicle/screen on that corridor. Building this is the
#: expensive part (a POI query per stop); every screen on the same corridor
#: reuses one entry instead of recomputing it.
CorridorExteriorCache = dict[str, dict[str, dict[int, float]]]


def _corridor_exterior_pull(
    corridor_id: str,
    repos: InMemoryRepositories,
    config: AudienceConfig,
    cache: CorridorExteriorCache,
) -> dict[str, dict[int, float]]:
    if corridor_id in cache:
        return cache[corridor_id]

    stops = repos.network.locations_for_corridor(corridor_id)
    per_day: dict[str, dict[int, float]] = {
        day: dict.fromkeys(TIME_BLOCK_IDS, 0.0) for day in _DAY_TYPES
    }
    if stops:
        per_stop_block: list[dict[int, float]] = []
        for location_id in stops:
            pois = repos.context.pois_near(location_id, config.poi_query_radius_km)
            per_stop_block.append(poi_pull_by_block(pois, config=config.poi))
        for day in _DAY_TYPES:
            for block in TIME_BLOCK_IDS:
                per_day[day][block] = sum(s[block] for s in per_stop_block) / len(per_stop_block)

    cache[corridor_id] = per_day
    return per_day


def build_mobile_profile(
    screen: Screen,
    repos: InMemoryRepositories,
    config: AudienceConfig,
    corridor_cache: CorridorExteriorCache,
) -> AudienceProfile:
    """Build the D1 `AudienceProfile` for one vehicle-mounted screen."""
    if not screen.is_mobile or screen.vehicle_id is None:
        raise ValueError(f"build_mobile_profile requires a mobile screen, got {screen.screen_id!r}")

    corridor_id = repos.network.corridor_for_vehicle(screen.vehicle_id)
    if corridor_id is None:
        raise ValueError(f"Vehicle {screen.vehicle_id!r} has no assigned corridor")

    is_interior = screen.position is None  # metro_rail_coach panels only (Step 1.1)
    exterior_pull = _corridor_exterior_pull(corridor_id, repos, config, corridor_cache)

    per_day_blocks: dict[str, dict[int, float]] = {}
    ridership_totals: dict[str, float] = {}
    for day_type in _DAY_TYPES:
        daily_ridership = repos.network.daily_ridership_for_corridor(corridor_id, day_type)
        ridership_totals[day_type] = daily_ridership
        blocks: dict[int, float] = {}
        for block in TIME_BLOCK_IDS:
            share = repos.network.ridership_share_for_corridor(corridor_id, block, day_type)
            if share == 0.0 and daily_ridership == 0.0:
                share = DEFAULT_DAYPART_SHARE[day_type][block]
            if is_interior:
                blocks[block] = daily_ridership * share * config.mobile.interior_capture_rate
            else:
                blocks[block] = (
                    exterior_pull[day_type][block] * config.mobile.exterior_glimpse_discount
                )
        per_day_blocks[day_type] = blocks

    weekday_total = sum(per_day_blocks["weekday"].values()) or 1.0
    weekend_total = sum(per_day_blocks["weekend"].values()) or 1.0
    daypart_weight_weekday = {b: v / weekday_total for b, v in per_day_blocks["weekday"].items()}
    daypart_weight_weekend = {b: v / weekend_total for b, v in per_day_blocks["weekend"].items()}

    est_daily_exposure = (
        _WEEKDAY_WEIGHT * sum(per_day_blocks["weekday"].values())
        + _WEEKEND_WEIGHT * sum(per_day_blocks["weekend"].values())
    )

    city = repos.geography.city(screen.city_id)
    if city is None:
        raise ValueError(f"Unknown city_id {screen.city_id!r} for screen {screen.screen_id!r}")

    has_history = ridership_totals["weekday"] > 0 or exterior_pull["weekday"][3] > 0
    trip_freq = repos.network.trip_frequency(corridor_id, "weekday")
    stops_for_detail = repos.network.locations_for_corridor(corridor_id)

    contributions = (
        Contribution(
            signal="captive_ridership" if is_interior else "trip_frequency",
            direction="positive" if ridership_totals["weekday"] > 0 else "neutral",
            weight=0.55 if is_interior else 0.25,
            magnitude=ridership_totals["weekday"] if is_interior else float(trip_freq),
            detail=(
                f"Corridor {corridor_id} weekday ridership {ridership_totals['weekday']:,.0f}."
                if is_interior
                else f"Corridor {corridor_id}: {trip_freq} scheduled weekday trips."
            ),
            evidence=(
                EvidenceRef(
                    table="route_schedules",
                    row_key={"corridor_id": corridor_id},
                    field="schedule_id",
                    value=trip_freq,
                ),
            ),
        ),
        Contribution(
            signal="street_glimpse_pull" if not is_interior else "interior_capture_rate",
            direction="positive",
            weight=0.55 if not is_interior else 0.25,
            magnitude=(
                sum(exterior_pull["weekday"].values())
                if not is_interior
                else config.mobile.interior_capture_rate
            ),
            detail=(
                (
                    f"Average POI/resident pull across {len(stops_for_detail)} stops on "
                    f"corridor {corridor_id}, discounted "
                    f"{config.mobile.exterior_glimpse_discount:.0%} for a passer-by glimpse "
                    "vs. captive dwell."
                )
                if not is_interior
                else "Interior coach panel — full ridership counted as captive dwell audience."
            ),
        ),
    )

    explanation = Explanation(
        headline=(
            f"{screen.screen_id}: est. {est_daily_exposure:,.0f} daily exposure "
            f"({'captive interior riders' if is_interior else 'exterior street glimpse'})."
        ),
        contributions=contributions,
        confidence=Confidence.HIGH if has_history else Confidence.MEDIUM,
        confidence_reason=(
            "Corridor ridership and stop-level POI coverage are both present."
            if has_history
            else (
                "No ridership rows for this corridor — using the Step 1.6 "
                "network-default daypart curve."
            )
        ),
        fallbacks_used=() if has_history else ("network_default_daypart_curve",),
    )

    return AudienceProfile(
        screen_id=screen.screen_id,
        market_tier=MarketTier(city["market_tier"]),
        dominant_occupation="mixed",  # a moving vehicle has no single resident zone
        daypart_weight_weekday=daypart_weight_weekday,
        daypart_weight_weekend=daypart_weight_weekend,
        environment_labels=(),
        est_daily_exposure=est_daily_exposure,
        has_history=has_history,
        explanation=explanation,
    )


__all__ = ["build_mobile_profile", "CorridorExteriorCache"]
