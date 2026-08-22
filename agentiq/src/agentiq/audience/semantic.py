"""Step 3.3 — Semantic audience/environment labelling.

The solution plan specifies an LLM agent here, constrained to a controlled
vocabulary (`config/taxonomy.yaml`'s `environment_types`) with mandatory
per-label evidence citation. No LLM endpoint is configured in this
environment, so this module is the **deterministic rule-based fallback**
CLAUDE.md requires every agent step to have — every label it assigns is
grounded in a real `points_of_interest.poi_type` or `zone_demographics`
signal actually present near the screen, and a `poi_type`/context with no
clean vocabulary match is dropped, never force-matched to the nearest label
(the same "record as unresolved, don't invent" rule Step 1.8's brief parser
already follows). Swapping in a real LLM call means replacing
`label_environment` internally; the function signature and guardrail
(controlled vocabulary only, evidence required) stay the same.
"""

from __future__ import annotations

import pandas as pd

#: poi_type -> environment_type(s) it grounds, restricted to `config/taxonomy.yaml`'s
#: vocabulary. Deliberately partial: `airport_transit_corridor`,
#: `auto_retail_arterial_corridor` and `mall_beauty_retail_entry` have no
#: corresponding `poi_type` in this dataset's 13-value vocabulary, so they are
#: never assigned here — a real LLM agent with brief/street-level context may
#: still resolve them; this fallback does not guess.
_POI_TYPE_TO_ENVIRONMENT: dict[str, tuple[str, ...]] = {
    "shopping_mall": ("premium_mall_entry", "high_street_retail_corridor"),
    "grocery_anchor": ("high_street_retail_corridor",),
    "office_park": ("business_district_platform", "premium_business_core"),
    "corporate_campus": ("premium_business_core", "business_district_platform"),
    "residential_tower": ("hyperlocal_walking_radius",),
    "entertainment_district": ("nightlife_entertainment_corridor", "event_venue_precinct"),
    "government_building": ("business_district_platform",),
    "hospital": ("hyperlocal_walking_radius",),
    "university": ("campus_edge_transit_node",),
    "hotel_convention": ("premium_business_core",),
    "stadium_arena": ("event_venue_precinct",),
    # museum, tourist_landmark: no clean environment_type match — dropped, not guessed.
}

#: Environment vocabulary allowed (mirrors config/taxonomy.yaml — kept as a
#: literal set here too so a bad poi_type mapping above fails loudly in tests
#: rather than silently emitting an off-vocabulary label).
ALLOWED_ENVIRONMENT_TYPES: frozenset[str] = frozenset(
    {
        "business_district_platform",
        "auto_retail_arterial_corridor",
        "nightlife_entertainment_corridor",
        "campus_edge_transit_node",
        "event_venue_precinct",
        "premium_mall_entry",
        "high_street_retail_corridor",
        "hyperlocal_walking_radius",
        "airport_transit_corridor",
        "premium_business_core",
        "financial_district_node",
        "mall_beauty_retail_entry",
        "central_metro_entry",
    }
)

assert set().union(*_POI_TYPE_TO_ENVIRONMENT.values()) <= ALLOWED_ENVIRONMENT_TYPES


def label_environment(
    pois: pd.DataFrame,
    *,
    zone_name: str | None = None,
    is_network_hub_nearby: bool = False,
    max_labels: int = 3,
) -> tuple[str, ...]:
    """Grounded environment labels for one screen, ranked by cumulative footfall.

    *pois* is the same radius-filtered frame the static/mobile models use.
    `financial_district_node` and `central_metro_entry` are the two labels
    grounded in signals other than `poi_type` (the real `zone_name` field,
    and network-hub adjacency respectively) — still real data, never a guess.
    """
    if pois.empty and not is_network_hub_nearby and not (zone_name and "Financial" in zone_name):
        return ()

    scores: dict[str, float] = {}
    if not pois.empty:
        by_type = pois.groupby("poi_type", observed=True)["est_daily_footfall"].sum()
        for poi_type, footfall in by_type.items():
            for label in _POI_TYPE_TO_ENVIRONMENT.get(str(poi_type), ()):
                scores[label] = scores.get(label, 0.0) + float(footfall)

    if zone_name and "Financial" in zone_name:
        scores["financial_district_node"] = scores.get("financial_district_node", 0.0) + 1.0
    if is_network_hub_nearby:
        scores["central_metro_entry"] = scores.get("central_metro_entry", 0.0) + 1.0

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    labels = tuple(label for label, _ in ranked[:max_labels])
    assert set(labels) <= ALLOWED_ENVIRONMENT_TYPES
    return labels
