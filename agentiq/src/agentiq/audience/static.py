"""Step 3.1 — Static exposure model (fixed screens: `metro_station`, `bus_stop`).

Composes, per Step 1.6's carry-forward table: resident/zone base (adjusted by
the daytime-population multiplier), transit throughput at the stop, POI pull
within the validated 0.3-0.5km radius, and a visibility modifier from mount
position and screen size. Every input traces to a real repository row —
never a bare CSV read (CLAUDE.md: "repositories, not file paths").
"""

from __future__ import annotations

from agentiq.audience.config import AudienceConfig
from agentiq.audience.daypart import DEFAULT_DAYPART_SHARE, TIME_BLOCK_DAYPART
from agentiq.audience.poi import dominant_poi_types, poi_pull_by_block
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.enums import Confidence, MarketTier
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation
from agentiq.domain.inventory import TIME_BLOCK_IDS, AudienceProfile, Screen

_DAY_TYPES: tuple[str, ...] = ("weekday", "weekend")
#: Weekly-average daily exposure blends the two day types 5:2, matching the
#: real weekday:weekend split of a calendar week — not a plain 50/50 average.
_WEEKDAY_WEIGHT = 5.0 / 7.0
_WEEKEND_WEIGHT = 2.0 / 7.0


def _daypart_share(
    repos: InMemoryRepositories, location_id: str, day_type: str
) -> dict[int, float]:
    """Real per-location ridership shares, falling back to the Step 1.6 network
    default only when this location has no ridership rows of its own at all."""
    shares = {
        block: repos.network.ridership_share_for_location(location_id, block, day_type)
        for block in TIME_BLOCK_IDS
    }
    if sum(shares.values()) > 0:
        return shares
    return DEFAULT_DAYPART_SHARE[day_type]


def build_static_profile(
    screen: Screen,
    repos: InMemoryRepositories,
    config: AudienceConfig,
) -> AudienceProfile:
    """Build the D1 `AudienceProfile` for one static screen."""
    if not screen.is_static or screen.location_id is None:
        raise ValueError(f"build_static_profile requires a static screen, got {screen.screen_id!r}")

    location_id = screen.location_id
    location = repos.geography.location(location_id)
    if location is None:
        raise ValueError(f"Unknown location_id {location_id!r} for screen {screen.screen_id!r}")
    zone = repos.geography.zone_for_location(location_id)
    if zone is None:
        raise ValueError(f"Location {location_id!r} has no zone (data integrity gap)")
    city = repos.geography.city(screen.city_id)
    if city is None:
        raise ValueError(f"Unknown city_id {screen.city_id!r} for screen {screen.screen_id!r}")

    daytime_population = float(zone["resident_population"]) * float(
        zone["daytime_population_multiplier"]
    )

    pois = repos.context.pois_near(location_id, config.poi_query_radius_km)
    poi_by_block = poi_pull_by_block(pois, config=config.poi)

    visibility = 1.0
    if screen.position is not None:
        visibility *= config.visibility.position_weight.get(screen.position.value, 1.0)
    visibility *= config.visibility.screen_size_weight.get(screen.screen_size.value, 1.0)

    per_day_blocks: dict[str, dict[int, float]] = {}
    transit_totals: dict[str, float] = {}
    for day_type in _DAY_TYPES:
        share = _daypart_share(repos, location_id, day_type)
        daily_ridership = repos.network.daily_ridership_for_location(location_id, day_type)
        transit_totals[day_type] = daily_ridership
        blocks: dict[int, float] = {}
        for block in TIME_BLOCK_IDS:
            resident_component = daytime_population * share[block]
            transit_component = daily_ridership * share[block]
            poi_component = poi_by_block[block]
            blocks[block] = (resident_component + transit_component + poi_component) * visibility
        per_day_blocks[day_type] = blocks

    weekday_total = sum(per_day_blocks["weekday"].values()) or 1.0
    weekend_total = sum(per_day_blocks["weekend"].values()) or 1.0
    daypart_weight_weekday = {b: v / weekday_total for b, v in per_day_blocks["weekday"].items()}
    daypart_weight_weekend = {b: v / weekend_total for b, v in per_day_blocks["weekend"].items()}

    est_daily_exposure = (
        _WEEKDAY_WEIGHT * sum(per_day_blocks["weekday"].values())
        + _WEEKEND_WEIGHT * sum(per_day_blocks["weekend"].values())
    )

    top_poi_types = dominant_poi_types(pois)
    poi_footfall_total = float(pois["est_daily_footfall"].sum()) if not pois.empty else 0.0
    has_history = weekday_total > 1.0 or not pois.empty or transit_totals["weekday"] > 0

    contributions = (
        Contribution(
            signal="resident_daytime_population",
            direction="positive" if daytime_population > 0 else "neutral",
            weight=0.35,
            magnitude=daytime_population,
            detail=(
                f"Zone {zone['zone_id']} resident population {zone['resident_population']:,} x "
                f"daytime multiplier {zone['daytime_population_multiplier']:.2f}."
            ),
            evidence=(
                EvidenceRef(
                    table="zone_demographics",
                    row_key={"zone_id": zone["zone_id"]},
                    field="daytime_population_multiplier",
                    value=zone["daytime_population_multiplier"],
                ),
            ),
        ),
        Contribution(
            signal="transit_throughput",
            direction="positive" if transit_totals["weekday"] > 0 else "neutral",
            weight=0.35,
            magnitude=transit_totals["weekday"],
            detail=(
                f"Average weekday riders passing location {location_id} "
                "(Step 1.6 §6 ridership curve)."
            ),
            evidence=(
                EvidenceRef(
                    table="ridership_actuals",
                    row_key={"location_id": location_id},
                    field="actual_ridership",
                    value=transit_totals["weekday"],
                    note="Aggregated via route_stops -> route_schedules; see NetworkRepository.",
                ),
            ),
        ),
        Contribution(
            signal="poi_pull",
            direction="positive" if poi_footfall_total > 0 else "neutral",
            weight=0.20,
            magnitude=poi_footfall_total,
            detail=(
                f"{len(pois)} POIs within {config.poi_query_radius_km:.2f}km "
                f"(dominant types: {', '.join(top_poi_types) or 'none'})."
            ),
            evidence=(
                EvidenceRef(
                    table="points_of_interest",
                    row_key={"anchor_location_id": location_id},
                    field="est_daily_footfall",
                    value=poi_footfall_total,
                    note=(
                        f"Step 1.6 §3 validated radius "
                        f"{config.poi.radius_km_min}-{config.poi.radius_km_max}km."
                    ),
                ),
            ),
        ),
        Contribution(
            signal="visibility_modifier",
            direction="positive" if visibility >= 1.0 else "negative",
            weight=0.10,
            magnitude=visibility - 1.0 if visibility != 1.0 else 0.0,
            detail=f"Mount position {screen.position}, screen size {screen.screen_size.value}.",
        ),
    )

    explanation = Explanation(
        headline=(
            f"{screen.screen_id}: est. {est_daily_exposure:,.0f} daily exposure from resident, "
            "transit and POI signals."
        ),
        contributions=contributions,
        confidence=Confidence.HIGH if has_history else Confidence.MEDIUM,
        confidence_reason=(
            "Zone demographics and POI coverage are complete for every static screen "
            "(Step 1.7 §4); confidence is high when transit or POI signal is present, "
            "medium when the location has neither and the estimate rests on the "
            "resident/daytime-population base alone."
            if has_history
            else "No transit or POI signal at this location — resident base only."
        ),
        fallbacks_used=() if has_history else ("resident_base_only_no_transit_or_poi",),
    )

    return AudienceProfile(
        screen_id=screen.screen_id,
        market_tier=MarketTier(city["market_tier"]),
        dominant_occupation=str(zone["dominant_occupation"]),
        daypart_weight_weekday=daypart_weight_weekday,
        daypart_weight_weekend=daypart_weight_weekend,
        environment_labels=(),
        est_daily_exposure=est_daily_exposure,
        has_history=has_history,
        explanation=explanation,
    )


__all__ = ["build_static_profile", "TIME_BLOCK_DAYPART"]
