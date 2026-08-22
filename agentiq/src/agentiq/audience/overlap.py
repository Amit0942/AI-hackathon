"""Step 3.4 — Audience-overlap graph (stop double-counting the same commuter).

Built from four real signals, each with a stated overlap coefficient:
same location (static screens sharing a stop/station — Step 1.4 §3 found up
to 50 screens at one metro station), same vehicle (mobile screens sharing
one bus/coach — `vehicles.screen_count` is 2-4), same corridor but different
vehicles (a stated assumption, since no direct measurement of cross-vehicle
audience overlap exists in this dataset), and shared POI catchment (two
different static locations whose 0.3-0.5km POI sets substantially overlap).
Stored sparse — only screen pairs with nonzero overlap are kept — since a
dense 11,163² matrix would be ~124M entries for a network where most pairs
share nothing.
"""

from __future__ import annotations

from itertools import combinations

from agentiq.audience.config import AudienceConfig
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.inventory import Screen

#: `(screen_id_a, screen_id_b)` with `screen_id_a < screen_id_b`, sparse.
OverlapGraph = dict[tuple[str, str], float]


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _add_overlap(graph: OverlapGraph, screen_ids: tuple[str, ...], coefficient: float) -> None:
    for a, b in combinations(sorted(screen_ids), 2):
        key = _pair_key(a, b)
        graph[key] = max(graph.get(key, 0.0), coefficient)


def build_overlap_graph(
    screens: tuple[Screen, ...],
    repos: InMemoryRepositories,
    config: AudienceConfig,
) -> OverlapGraph:
    graph: OverlapGraph = {}
    overlap_config = config.overlap

    by_location: dict[str, list[str]] = {}
    by_vehicle: dict[str, list[str]] = {}
    static_by_location: dict[str, Screen] = {}
    for screen in screens:
        if screen.is_static and screen.location_id is not None:
            by_location.setdefault(screen.location_id, []).append(screen.screen_id)
            static_by_location[screen.location_id] = screen
        elif screen.is_mobile and screen.vehicle_id is not None:
            by_vehicle.setdefault(screen.vehicle_id, []).append(screen.screen_id)

    for screen_ids in by_location.values():
        _add_overlap(graph, tuple(screen_ids), 1.0)
    for screen_ids in by_vehicle.values():
        _add_overlap(graph, tuple(screen_ids), 1.0)

    # Same corridor, different vehicles.
    by_corridor: dict[str, list[str]] = {}
    for vehicle_id, screen_ids in by_vehicle.items():
        corridor_id = repos.network.corridor_for_vehicle(vehicle_id)
        if corridor_id is not None:
            by_corridor.setdefault(corridor_id, []).extend(screen_ids)
    for screen_ids in by_corridor.values():
        _add_overlap(graph, tuple(screen_ids), overlap_config.cross_vehicle_same_corridor)

    # Shared POI catchment across different static locations.
    shared = _shared_poi_sets(repos, static_by_location, config.poi_query_radius_km)
    if shared is not None:
        poi_sets, poi_index = shared
        for locations_sharing in poi_index.values():
            for loc_a, loc_b in combinations(sorted(set(locations_sharing)), 2):
                jaccard = _jaccard(poi_sets[loc_a], poi_sets[loc_b])
                if jaccard >= overlap_config.poi_jaccard_threshold:
                    a_screen = static_by_location[loc_a].screen_id
                    b_screen = static_by_location[loc_b].screen_id
                    key = _pair_key(a_screen, b_screen)
                    graph[key] = max(graph.get(key, 0.0), jaccard)

    return graph


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _shared_poi_sets(
    repos: InMemoryRepositories,
    static_by_location: dict[str, Screen],
    poi_query_radius_km: float,
) -> tuple[dict[str, frozenset[str]], dict[str, list[str]]] | None:
    """One representative POI-set per location (0.3-0.5km midpoint radius),
    plus an inverted `poi_id -> [location_id, ...]` index so only locations
    that actually share at least one POI are ever compared."""
    poi_sets: dict[str, frozenset[str]] = {}
    poi_index: dict[str, list[str]] = {}
    for location_id in static_by_location:
        pois = repos.context.pois_near(location_id, poi_query_radius_km)
        poi_ids = frozenset(pois["poi_id"]) if not pois.empty else frozenset()
        poi_sets[location_id] = poi_ids
        for poi_id in poi_ids:
            poi_index.setdefault(poi_id, []).append(location_id)

    # Only keep index entries with >1 location (the only ones that can create an overlap pair).
    poi_index = {poi_id: locs for poi_id, locs in poi_index.items() if len(locs) > 1}
    if not poi_index:
        return None
    return poi_sets, poi_index


def overlap_for(graph: OverlapGraph, screen_a: str, screen_b: str) -> float:
    if screen_a == screen_b:
        return 1.0
    return graph.get(_pair_key(screen_a, screen_b), 0.0)


__all__ = ["OverlapGraph", "build_overlap_graph", "overlap_for"]
