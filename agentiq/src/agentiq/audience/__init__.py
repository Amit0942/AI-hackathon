"""D1 — Audience Profile Engine (Phase 3).

Public entrypoint: `AudienceProfileEngine`. Wraps every Step 3.1-3.5 piece —
static/mobile exposure, semantic labelling (deterministic fallback pending a
real LLM call), the overlap graph, and impressions/reach — behind one object
built once per `InMemoryRepositories` instance (offline precompute, per
design principle 5). `InMemoryAudienceProfileRepository` is the
`AudienceProfileRepository` implementation `data/repositories.py` left
unbuilt (§7 of `HANDOFF.md`) — D2/D4 depend on this, not on the engine
internals directly.
"""

from __future__ import annotations

import pandas as pd

from agentiq.audience.config import AudienceConfig, load_audience_config
from agentiq.audience.mobile import CorridorExteriorCache, build_mobile_profile
from agentiq.audience.overlap import OverlapGraph, build_overlap_graph
from agentiq.audience.reach import (
    attention_factor,
    effective_exposure,
    impressions,
    reach_estimate_for_group,
    unique_reach,
)
from agentiq.audience.semantic import label_environment
from agentiq.audience.static import build_static_profile
from agentiq.data.repositories import AudienceProfileRepository, InMemoryRepositories
from agentiq.domain.inventory import AudienceProfile, Screen
from agentiq.domain.optimizer import ReachEstimate

__all__ = [
    "AudienceConfig",
    "AudienceProfileEngine",
    "InMemoryAudienceProfileRepository",
    "attention_factor",
    "effective_exposure",
    "impressions",
    "load_audience_config",
    "reach_estimate_for_group",
    "unique_reach",
]

#: Cap on how many corridor stops are sampled for mobile-screen environment
#: labelling — enough for a representative POI mix without querying every
#: stop on a long corridor (some carry 20+ stops).
_MAX_STOPS_SAMPLED_FOR_LABELLING = 6


class AudienceProfileEngine:
    """Builds and caches `AudienceProfile`s, the overlap graph, and reach
    estimates for one `InMemoryRepositories` instance.

    Profiles are built lazily and cached per screen — a demo or test that
    only touches a handful of screens does not pay for all 11,163. Call
    `build_all()` to force full precompute (what `InMemoryAudienceProfileRepository`
    does the first time `.all()` is read).
    """

    def __init__(self, repos: InMemoryRepositories, config: AudienceConfig | None = None) -> None:
        self.repos = repos
        self.config = config or load_audience_config()
        self._corridor_cache: CorridorExteriorCache = {}
        self._profiles: dict[str, AudienceProfile] = {}
        self._overlap_graph: OverlapGraph | None = None

    def profile(self, screen: Screen) -> AudienceProfile:
        cached = self._profiles.get(screen.screen_id)
        if cached is not None:
            return cached

        if screen.is_static:
            base = build_static_profile(screen, self.repos, self.config)
            labels = self._labels_for_static(screen)
        else:
            base = build_mobile_profile(screen, self.repos, self.config, self._corridor_cache)
            labels = self._labels_for_mobile(screen)

        profile = base.model_copy(update={"environment_labels": labels}) if labels else base
        self._profiles[screen.screen_id] = profile
        return profile

    def get(self, screen_id: str) -> AudienceProfile | None:
        screen = self.repos.screens.get(screen_id)
        return self.profile(screen) if screen is not None else None

    def build_all(self) -> tuple[AudienceProfile, ...]:
        return tuple(self.profile(screen) for screen in self.repos.screens.all())

    def overlap_graph(self) -> OverlapGraph:
        if self._overlap_graph is None:
            self._overlap_graph = build_overlap_graph(
                self.repos.screens.all(), self.repos, self.config
            )
        return self._overlap_graph

    def impressions_for(
        self,
        screen_id: str,
        time_block_id: int,
        slots: int,
        *,
        day_type: str = "weekday",
    ) -> float:
        profile = self.get(screen_id)
        if profile is None:
            raise ValueError(f"Unknown screen_id {screen_id!r}")
        weights = (
            profile.daypart_weight_weekday
            if day_type == "weekday"
            else profile.daypart_weight_weekend
        )
        exposure_for_block = profile.est_daily_exposure * weights.get(time_block_id, 0.0)
        return impressions(
            exposure_for_block, slots, alpha=self.config.reach.attention_growth_rate
        )

    def reach_for(
        self,
        slots_by_screen: dict[str, int],
        time_block_id: int,
        *,
        day_type: str = "weekday",
    ) -> ReachEstimate:
        """`ReachEstimate` for a group of screen-slot decisions in one time block
        (e.g. a candidate package line set) — reusable by D4's optimizer."""
        impressions_map = {
            screen_id: self.impressions_for(screen_id, time_block_id, slots, day_type=day_type)
            for screen_id, slots in slots_by_screen.items()
        }
        return reach_estimate_for_group(
            impressions_map,
            self.overlap_graph(),
            reach_saturation_scale=self.config.reach.reach_saturation_scale,
        )

    def _labels_for_static(self, screen: Screen) -> tuple[str, ...]:
        assert screen.location_id is not None
        zone = self.repos.geography.zone_for_location(screen.location_id)
        pois = self.repos.context.pois_near(screen.location_id, self.config.poi_query_radius_km)
        is_hub_nearby = bool(pois["is_network_hub"].any()) if not pois.empty else False
        return label_environment(
            pois,
            zone_name=zone.get("zone_name") if zone else None,
            is_network_hub_nearby=is_hub_nearby,
        )

    def _labels_for_mobile(self, screen: Screen) -> tuple[str, ...]:
        assert screen.vehicle_id is not None
        corridor_id = self.repos.network.corridor_for_vehicle(screen.vehicle_id)
        if corridor_id is None:
            return ()
        stops = self.repos.network.locations_for_corridor(corridor_id)[
            :_MAX_STOPS_SAMPLED_FOR_LABELLING
        ]
        frames = [
            self.repos.context.pois_near(location_id, self.config.poi_query_radius_km)
            for location_id in stops
        ]
        pois = pd.concat(frames) if frames else pd.DataFrame()
        is_hub_nearby = bool(pois["is_network_hub"].any()) if not pois.empty else False
        return label_environment(pois, zone_name=None, is_network_hub_nearby=is_hub_nearby)


class InMemoryAudienceProfileRepository(AudienceProfileRepository):
    """`AudienceProfileRepository` backed by `AudienceProfileEngine` — the
    piece `data/repositories.py` explicitly left unimplemented pending D1.
    """

    def __init__(self, engine: AudienceProfileEngine) -> None:
        self._engine = engine
        self._all: tuple[AudienceProfile, ...] | None = None

    def get(self, screen_id: str) -> AudienceProfile | None:
        return self._engine.get(screen_id)

    def all(self) -> tuple[AudienceProfile, ...]:
        if self._all is None:
            self._all = self._engine.build_all()
        return self._all
