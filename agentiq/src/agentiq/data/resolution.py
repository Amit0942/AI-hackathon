"""Phase 4 — Brief Intake & Resolution (Steps 4.1-4.3).

`agentiq.data.briefs` parses a `.docx` into `DerivedBriefFields` — a literal,
lossless extraction with no binding to any enum, zone, or POI type. This
module is the missing second half: `resolve_brief()` turns that into a real
`agentiq.domain.CampaignBrief` (Step 4.2), and records every judgment call it
had to make as a `ClarificationQuestion` (Step 4.3) rather than a silent
guess. See `docs/decisions/0005-phase4-brief-resolution-scope.md` for why
each rule below exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from agentiq.data.briefs import CampaignBriefDocument, DerivedBriefFields
from agentiq.data.paths import ProjectPaths
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.campaign import CampaignBrief, GeographyConstraint
from agentiq.domain.enums import CampaignObjective, IndustryVertical

__all__ = [
    "ClarificationQuestion",
    "ResolutionConfig",
    "ResolvedBrief",
    "load_resolution_config",
    "resolve_brief",
]


@dataclass(frozen=True)
class ClarificationQuestion:
    """One Step 4.3 "ask, don't guess" question — always paired with the
    default assumption the pipeline proceeds on, per solution_plan.md's own
    instruction that the agent "asks a targeted question and states the
    assumption it would otherwise use," never silently guesses and never
    blocks outright."""

    question: str
    default_assumption: str
    blocking: bool = False


@dataclass(frozen=True)
class ResolvedBrief:
    """A resolved `CampaignBrief` plus every clarification its resolution needed."""

    brief: CampaignBrief
    clarifications: tuple[ClarificationQuestion, ...]


@dataclass(frozen=True)
class ResolutionConfig:
    industry_vertical_keywords: tuple[tuple[str, str], ...]
    default_industry_vertical: str
    objective_keywords: tuple[tuple[str, str], ...]
    default_objective: str
    location_label_environment_types: dict[str, str]
    screen_exclusion_phrases: dict[str, str]
    value_tier_residential_trigger_phrases: tuple[str, ...]
    value_tier_residential_income_index_max: float
    value_tier_residential_density_min: float
    daypart_keywords: dict[str, tuple[int, ...]]
    weekend_weighting_strong_phrases: tuple[str, ...]
    weekend_weighting_strong_value: float
    weekend_weighting_soft_phrases: tuple[str, ...]
    weekend_weighting_soft_value: float
    hyperlocal_outlet_poi_types: tuple[str, ...]
    hyperlocal_radius_km_default: float


def load_resolution_config(config_path: str | None = None) -> ResolutionConfig:
    path = ProjectPaths().config / "taxonomy.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)["brief_resolution"]

    return ResolutionConfig(
        industry_vertical_keywords=tuple(
            (kw, value) for kw, value in raw["industry_vertical_keywords"]
        ),
        default_industry_vertical=raw["default_industry_vertical"],
        objective_keywords=tuple((kw, value) for kw, value in raw["objective_keywords"]),
        default_objective=raw["default_objective"],
        location_label_environment_types=dict(raw["location_label_environment_types"]),
        screen_exclusion_phrases=dict(raw["screen_exclusion_phrases"]),
        value_tier_residential_trigger_phrases=tuple(
            raw["value_tier_residential_trigger_phrases"]
        ),
        value_tier_residential_income_index_max=float(
            raw["value_tier_residential_income_index_max"]
        ),
        value_tier_residential_density_min=float(raw["value_tier_residential_density_min"]),
        daypart_keywords={k: tuple(v) for k, v in raw["daypart_keywords"].items()},
        weekend_weighting_strong_phrases=tuple(raw["weekend_weighting_strong_phrases"]),
        weekend_weighting_strong_value=float(raw["weekend_weighting_strong_value"]),
        weekend_weighting_soft_phrases=tuple(raw["weekend_weighting_soft_phrases"]),
        weekend_weighting_soft_value=float(raw["weekend_weighting_soft_value"]),
        hyperlocal_outlet_poi_types=tuple(raw["hyperlocal_outlet_poi_types"]),
        hyperlocal_radius_km_default=float(raw["hyperlocal_radius_km_default"]),
    )


# --------------------------------------------------------------------- industry / objective
def _earliest_keyword_match(
    text: str, keywords: tuple[tuple[str, str], ...], default: str
) -> tuple[str, bool]:
    """Return `(value, matched)` — the value of whichever keyword occurs at
    the EARLIEST position in *text*, or *default* with `matched=False` if
    none occur at all. Earliest-position, not first-in-list, is what
    reproduces the hand-read primary objective across all six real briefs
    (ADR-0005 decision 2)."""
    lowered = text.lower()
    best_index = len(lowered) + 1
    best_value: str | None = None
    for keyword, value in keywords:
        index = lowered.find(keyword.lower())
        if index != -1 and index < best_index:
            best_index = index
            best_value = value
    return (best_value, True) if best_value is not None else (default, False)


def _resolve_industry_vertical(
    derived: DerivedBriefFields, config: ResolutionConfig
) -> tuple[IndustryVertical, bool]:
    value, matched = _earliest_keyword_match(
        derived.industry_vertical,
        config.industry_vertical_keywords,
        config.default_industry_vertical,
    )
    return IndustryVertical(value), matched


def _resolve_objective(
    derived: DerivedBriefFields, config: ResolutionConfig
) -> tuple[CampaignObjective, bool]:
    value, matched = _earliest_keyword_match(
        derived.objective, config.objective_keywords, config.default_objective
    )
    return CampaignObjective(value), matched


# ------------------------------------------------------------------------------- city
def _resolve_city(
    document: CampaignBriefDocument, repos: InMemoryRepositories
) -> tuple[str | None, tuple[str, ...]]:
    """Search the whole document for a mention of a known city name.
    Returns `(city_id_or_None, matched_city_ids)` — the second element lets
    the caller distinguish "zero mentions" from "multiple, ambiguous
    mentions" for the clarification message."""
    cities = repos.lake["cities"]
    haystack = document.raw_text.lower()
    matched = tuple(
        str(row["city_id"])
        for _, row in cities.iterrows()
        if str(row["city_name"]).lower() in haystack
    )
    return (matched[0], matched) if len(matched) == 1 else (None, matched)


# --------------------------------------------------------------------- environment types
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalise_label(label: str) -> str:
    return _NON_ALNUM_RE.sub("_", label.lower()).strip("_")


def _resolve_environment_types(
    derived: DerivedBriefFields, config: ResolutionConfig, known_environment_types: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Returns `(resolved_environment_types, unresolved_labels)`."""
    resolved: list[str] = []
    unresolved: list[str] = []
    for requirement in derived.location_requirements:
        label = requirement.split(":", 1)[0].strip()
        mapped = config.location_label_environment_types.get(label)
        if mapped is None:
            normalised = _normalise_label(label)
            mapped = normalised if normalised in known_environment_types else None
        if mapped is not None:
            resolved.append(mapped)
        else:
            unresolved.append(label)
    # dict.fromkeys de-duplicates while preserving first-seen order.
    return tuple(dict.fromkeys(resolved)), tuple(unresolved)


# ------------------------------------------------------------------------- exclusions
def _resolve_screen_type_exclusions(
    derived: DerivedBriefFields, config: ResolutionConfig
) -> tuple[str, ...]:
    haystack = " ".join(derived.exclusions).lower()
    return tuple(
        rule
        for phrase, rule in config.screen_exclusion_phrases.items()
        if phrase.lower() in haystack
    )


def _resolve_value_tier_residential_exclusion(
    derived: DerivedBriefFields,
    config: ResolutionConfig,
    city_id: str | None,
    repos: InMemoryRepositories,
) -> tuple[GeographyConstraint, ...]:
    haystack = " ".join(derived.exclusions).lower()
    if city_id is None or not any(
        phrase.lower() in haystack for phrase in config.value_tier_residential_trigger_phrases
    ):
        return ()

    zones = repos.lake["zone_demographics"]
    matches = zones.loc[
        (zones["city_id"] == city_id)
        & (zones["income_index"] < config.value_tier_residential_income_index_max)
        & (zones["population_density_per_sqkm"] > config.value_tier_residential_density_min)
    ]
    return tuple(
        GeographyConstraint(city_id=city_id, zone_name=str(row["zone_name"]), is_exclusion=True)
        for _, row in matches.iterrows()
    )


# --------------------------------------------------------------------------- daypart
def _resolve_daypart(
    document: CampaignBriefDocument, config: ResolutionConfig
) -> tuple[tuple[int, ...], float | None]:
    haystack = document.raw_text.lower()

    blocks: set[int] = set()
    for phrase, block_ids in config.daypart_keywords.items():
        if phrase in haystack:
            blocks.update(block_ids)

    weekend_weighting: float | None = None
    if any(phrase in haystack for phrase in config.weekend_weighting_strong_phrases):
        weekend_weighting = config.weekend_weighting_strong_value
    elif any(phrase in haystack for phrase in config.weekend_weighting_soft_phrases):
        weekend_weighting = config.weekend_weighting_soft_value

    return tuple(sorted(blocks)), weekend_weighting


# ------------------------------------------------------------------------ hyperlocal outlet
def _resolve_hyperlocal_outlet(
    derived: DerivedBriefFields,
    config: ResolutionConfig,
    city_id: str | None,
    repos: InMemoryRepositories,
) -> tuple[GeographyConstraint | None, ClarificationQuestion | None]:
    unresolved_text = " ".join(derived.unresolved_requirements).lower()
    if "walking" not in unresolved_text and "radius" not in unresolved_text:
        return None, None
    if city_id is None:
        return None, ClarificationQuestion(
            question=(
                "This brief asks for a hyper-local walking radius around a single outlet, "
                "but no city was resolved either — which city and which outlet POI?"
            ),
            default_assumption="No city resolved; cannot apply even the zone-level default.",
            blocking=True,
        )

    pois = repos.lake["points_of_interest"]
    candidates = pois.loc[
        (pois["city_id"] == city_id) & (pois["poi_type"].isin(config.hyperlocal_outlet_poi_types))
    ]
    if candidates.empty:
        return None, ClarificationQuestion(
            question="Which office park / corporate campus is the new outlet located in?",
            default_assumption=f"No {config.hyperlocal_outlet_poi_types} POI found in {city_id}.",
            blocking=True,
        )

    top = candidates.loc[candidates["est_daily_footfall"].idxmax()]
    zone_name = str(top["city_zone"])
    constraint = GeographyConstraint(city_id=city_id, zone_name=zone_name, is_exclusion=False)
    question = ClarificationQuestion(
        question="Which office park / corporate campus is the new outlet located in?",
        default_assumption=(
            f"Defaulted to {top['name']!r} ({top['poi_id']}), the highest-footfall "
            f"{top['poi_type']} in {city_id}, narrowed to its zone {zone_name!r}. "
            "This is a zone-level approximation, not a true walking radius — "
            "GeographyConstraint has no location-level field (ADR-0005 decision 7)."
        ),
        blocking=True,
    )
    return constraint, question


# --------------------------------------------------------------------------- entrypoint
def resolve_brief(
    document: CampaignBriefDocument,
    derived: DerivedBriefFields,
    repos: InMemoryRepositories,
    *,
    brief_id: str | None = None,
    known_environment_types: set[str] | None = None,
    config: ResolutionConfig | None = None,
) -> ResolvedBrief:
    """Step 4.2 + 4.3 — turn a literal brief parse into a resolved `CampaignBrief`.

    Every judgment call (ambiguous city, defaulted vertical/objective,
    applied value-tier proxy, hyperlocal outlet guess) is recorded as a
    `ClarificationQuestion` on the returned `ResolvedBrief`, never silently
    applied with no trace (ADR-0005 decision 9).
    """
    config = config or load_resolution_config()
    if known_environment_types is None:
        with open(ProjectPaths().config / "taxonomy.yaml", encoding="utf-8") as fh:
            known_environment_types = set(yaml.safe_load(fh)["environment_types"])

    clarifications: list[ClarificationQuestion] = []
    unresolved: list[str] = list(derived.unresolved_requirements)

    industry_vertical, industry_matched = _resolve_industry_vertical(derived, config)
    if not industry_matched:
        clarifications.append(
            ClarificationQuestion(
                question=f"Which industry vertical best fits {derived.industry_vertical!r}?",
                default_assumption=(
                    f"Defaulted to {industry_vertical.value!r} (no keyword matched)."
                ),
            )
        )
        unresolved.append(
            f"industry vertical {derived.industry_vertical!r} did not match any keyword"
        )

    objective, objective_matched = _resolve_objective(derived, config)
    if not objective_matched:
        clarifications.append(
            ClarificationQuestion(
                question=f"Which campaign objective best fits {derived.objective!r}?",
                default_assumption=f"Defaulted to {objective.value!r} (no keyword matched).",
            )
        )
        unresolved.append(f"objective {derived.objective!r} did not match any keyword")

    city_id, matched_cities = _resolve_city(document, repos)
    if city_id is None:
        if not matched_cities:
            clarifications.append(
                ClarificationQuestion(
                    question="Which city is this campaign for?",
                    default_assumption="No city stated; searching all cities network-wide.",
                    blocking=True,
                )
            )
        else:
            clarifications.append(
                ClarificationQuestion(
                    question=f"This brief mentions multiple cities {matched_cities} — which one?",
                    default_assumption="Ambiguous; searching all cities network-wide.",
                    blocking=True,
                )
            )

    # Order matters: `eligibility.py`'s `required` filter ORs every
    # non-exclusion GeographyConstraint together ("eligible if it matches
    # AT LEAST ONE"), not ANDs them — so a broad city-only constraint
    # alongside a tighter zone-scoped one would silently let screens from
    # the whole city back in, defeating the tighter one. Resolve the
    # tighter (hyperlocal outlet) constraint FIRST and only add the plain
    # city-wide constraint when nothing more specific was found — found and
    # fixed while running D5 end-to-end against brief 4 (ADR-0006).
    outlet_constraint, outlet_question = _resolve_hyperlocal_outlet(
        derived, config, city_id, repos
    )

    geography_constraints: list[GeographyConstraint] = []
    if outlet_constraint is not None:
        geography_constraints.append(outlet_constraint)
    elif city_id is not None:
        geography_constraints.append(GeographyConstraint(city_id=city_id, is_exclusion=False))
    if outlet_question is not None:
        clarifications.append(outlet_question)

    value_tier_exclusions = _resolve_value_tier_residential_exclusion(
        derived, config, city_id, repos
    )
    geography_constraints.extend(value_tier_exclusions)
    if value_tier_exclusions:
        excluded_zones = [c.zone_name for c in value_tier_exclusions]
        clarifications.append(
            ClarificationQuestion(
                question=(
                    "This brief excludes 'value-tier inventory in high-density residential "
                    "areas' — market_tier is city-grain only, so this was derived from a "
                    "zone-level proxy. Confirm the zones this should exclude."
                ),
                default_assumption=(
                    f"Excluded zones (income_index < "
                    f"{config.value_tier_residential_income_index_max:.0f}, density > "
                    f"{config.value_tier_residential_density_min:.0f}/km2): {excluded_zones}"
                ),
            )
        )

    screen_type_exclusions = _resolve_screen_type_exclusions(derived, config)

    requested_environment_types, unresolved_labels = _resolve_environment_types(
        derived, config, known_environment_types
    )
    for label in unresolved_labels:
        unresolved.append(
            f"location requirement {label!r} did not resolve onto any environment_type"
        )

    time_block_ids, weekend_weighting = _resolve_daypart(document, config)

    budget = derived.budget_amount
    if budget is None or budget <= 0:
        clarifications.append(
            ClarificationQuestion(
                question="What is the campaign budget? None was stated (or parsed) in the brief.",
                default_assumption="Defaulted to 1.0 as a placeholder — this brief cannot be "
                "priced or optimized meaningfully until a real budget is supplied.",
                blocking=True,
            )
        )
        unresolved.append("budget_amount missing or non-positive")
        budget = 1.0

    duration_days = derived.duration_days
    if duration_days is None or duration_days <= 0:
        clarifications.append(
            ClarificationQuestion(
                question="What is the campaign duration in days? None was stated in the brief.",
                default_assumption="Defaulted to 1 day as a placeholder.",
                blocking=True,
            )
        )
        unresolved.append("duration_days missing or non-positive")
        duration_days = 1

    brief = CampaignBrief(
        brief_id=brief_id or f"BRIEF-{document.brief_number or 0}",
        source_file=document.source_file,
        company=derived.company,
        industry_vertical=industry_vertical,
        objective=objective,
        target_age_min=derived.age_min,
        target_age_max=derived.age_max,
        budget=budget,
        start_date=None,
        duration_days=duration_days,
        slots_requested=derived.slots_requested,
        time_block_ids=time_block_ids,
        weekend_weighting=weekend_weighting,
        geography_constraints=tuple(geography_constraints),
        screen_type_exclusions=screen_type_exclusions,
        requested_environment_types=requested_environment_types,
        unresolved_requirements=tuple(dict.fromkeys(unresolved)),
    )
    return ResolvedBrief(brief=brief, clarifications=tuple(clarifications))
