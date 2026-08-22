"""Step 2.5 acceptance scenarios — the six supplied briefs, hand-checked.

Structural tests run today, against the deterministic `.docx` parser
(`agentiq.data.briefs`) and `config/taxonomy.yaml`. End-to-end tests are
collected `xfail(strict=True)` until Phase 8's orchestrator exists — see
`tests/acceptance/__init__.py` for why that is the intended state, not an
oversight.
"""

from __future__ import annotations

import pytest
import yaml

from agentiq.data.briefs import (
    CampaignBriefDocument,
    DerivedBriefFields,
    derive_fields,
    extract_docx_paragraphs,
    parse_brief,
)
from agentiq.data.paths import ProjectPaths
from agentiq.data.repositories import InMemoryRepositories
from tests.acceptance.fixtures import SCENARIOS, AcceptanceScenario

paths = ProjectPaths()


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def engines(repos: InMemoryRepositories):
    """One shared set of D1-D4 engines for the whole module.

    `run_brief_to_recommendation` default-constructs fresh engines when none
    are supplied (the right default for a single ad hoc call), but the six
    scenarios here would otherwise each re-fit D3's base-rate/win-probability
    models and re-cache D1's ~11k `AudienceProfile`s from scratch — sharing
    one set across the module is what keeps this test file's runtime sane.
    """
    from agentiq.audience import AudienceProfileEngine
    from agentiq.optimizer import OptimizerEngine
    from agentiq.pricing import PricingEngine
    from agentiq.relevance import RelevanceEngine

    audience_engine = AudienceProfileEngine(repos)
    pricing_engine = PricingEngine(repos, audience_engine=audience_engine)
    relevance_engine = RelevanceEngine(repos, audience_engine=audience_engine)
    optimizer_engine = OptimizerEngine(repos, audience_engine, pricing_engine)
    return {
        "repos": repos,
        "audience_engine": audience_engine,
        "pricing_engine": pricing_engine,
        "relevance_engine": relevance_engine,
        "optimizer_engine": optimizer_engine,
    }


def _load(scenario: AcceptanceScenario) -> tuple[CampaignBriefDocument, DerivedBriefFields]:
    path = paths.campaigns / scenario.source_file
    paragraphs = extract_docx_paragraphs(path)
    document = parse_brief(paragraphs, source_file=scenario.source_file)
    return document, derive_fields(document)


@pytest.fixture(scope="module")
def taxonomy() -> dict:
    with open(paths.root / "config" / "taxonomy.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# --------------------------------------------------------------------- structural
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_brief_file_exists(scenario: AcceptanceScenario) -> None:
    assert (paths.campaigns / scenario.source_file).is_file()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_header_fields_match_hand_read_values(scenario: AcceptanceScenario) -> None:
    document, fields = _load(scenario)

    assert document.brief_number == scenario.brief_number
    assert scenario.campaign_title_contains.upper() in document.title.upper()
    assert scenario.company.split(".")[0].split(" ")[0] in fields.company
    assert fields.budget_amount == scenario.budget_amount
    assert fields.duration_days == scenario.duration_days
    assert fields.age_min == scenario.age_min
    assert fields.age_max == scenario.age_max


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_hard_exclusion_detected_correctly(scenario: AcceptanceScenario) -> None:
    _, fields = _load(scenario)

    if scenario.has_hard_exclusion:
        assert len(fields.exclusions) >= 1, (
            f"brief {scenario.brief_number} states a hard exclusion but the parser found none"
        )
        exclusion_text = " ".join(fields.exclusions).lower()
        assert any(hint.lower() in exclusion_text for hint in scenario.excluded_inventory_hints), (
            f"brief {scenario.brief_number}'s exclusion text does not mention any of "
            f"{scenario.excluded_inventory_hints}: {exclusion_text!r}"
        )
    else:
        assert fields.exclusions == (), (
            f"brief {scenario.brief_number} was hand-read as having no hard exclusion, "
            f"but the parser found: {fields.exclusions}"
        )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_location_requirements_resolve_onto_taxonomy(
    scenario: AcceptanceScenario, taxonomy: dict
) -> None:
    """Every expected environment type for this brief must exist in
    config/taxonomy.yaml — a brief asking for an environment the taxonomy
    doesn't know about is a real capability gap, not a passing test.
    """
    known_environments = set(taxonomy["environment_types"])
    missing = scenario.expected_environment_types - known_environments
    assert not missing, (
        f"brief {scenario.brief_number} expects environment types not in "
        f"config/taxonomy.yaml: {missing}"
    )
    assert len(scenario.expected_environment_types) >= scenario.min_required_environments


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_capability_gaps_are_surfaced_not_dropped(scenario: AcceptanceScenario) -> None:
    """Anything the brief needs that the raw data doesn't directly support
    (Step 1.4 §5) must show up in `unresolved_requirements` — silently
    dropping a stated requirement is the failure mode Step 1.8 exists to catch.
    """
    _, fields = _load(scenario)
    unresolved_text = " ".join(fields.unresolved_requirements).lower()

    for keyword in scenario.unresolved_capability_keywords:
        assert keyword in unresolved_text, (
            f"brief {scenario.brief_number} should surface an unresolved capability "
            f"mentioning {keyword!r}, but got: {fields.unresolved_requirements}"
        )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_rfp_requirements_were_extracted(scenario: AcceptanceScenario) -> None:
    """Every brief's RFP section asks for exactly three deliverables: a
    ranked shortlist, a pricing rationale, and a reach projection. Losing
    this list silently would mean Phase 8's response is missing a
    deliverable the brief explicitly asked for.
    """
    document, _ = _load(scenario)
    assert len(document.requirements) == 3, (
        f"brief {scenario.brief_number}: expected 3 RFP requirements, "
        f"found {len(document.requirements)}: {document.requirements}"
    )


def test_all_six_briefs_are_covered() -> None:
    assert {s.brief_number for s in SCENARIOS} == {1, 2, 3, 4, 5, 6}


# ---------------------------------------------------------------- end-to-end (Phase 8)
# Phase 8's orchestrator (agentiq.agents.run_brief_to_recommendation) is now built —
# see docs/decisions/0006-d5-orchestrator-scope.md. The five tests below were
# collected as xfail(strict=True) placeholders per Step 2.5 so the definition of
# done was visible before the code existed; their bodies are now the real
# assertions, and the xfail marker is removed per this repo's own convention
# (HANDOFF.md: "strict=True means these fail the suite the moment they start
# passing without the marker being removed").


def _run(engines: dict, filename: str):
    from agentiq.agents import run_brief_to_recommendation

    return run_brief_to_recommendation(paths.campaigns / filename, **engines)


def _resolved(engines: dict, filename: str):
    from agentiq.agents import resolve_entities

    return resolve_entities(paths.campaigns / filename, engines["repos"])


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_recommendation_only_uses_required_environments(
    scenario: AcceptanceScenario, engines: dict
) -> None:
    """Every recommended screen's audience profile must carry at least one of
    this brief's expected environment labels — a premium brief must not be
    padded with unrelated inventory just to hit a budget.
    """
    recommendation = _run(engines, scenario.source_file)
    audience_engine = engines["audience_engine"]
    requested = set(recommendation.brief.requested_environment_types)
    if not requested:
        pytest.skip(f"brief {scenario.brief_number} resolved no requested_environment_types")

    for package in recommendation.packages:
        for line in package.lines:
            profile = audience_engine.get(line.screen_id)
            assert profile is not None
            assert set(profile.environment_labels) & requested, (
                f"brief {scenario.brief_number}: screen {line.screen_id} carries none of "
                f"the requested environment types {requested} "
                f"(has {profile.environment_labels})"
            )


def test_zephyr_ev_excludes_bus_rear_and_value_tier_residential(engines: dict) -> None:
    """Brief 1's hard exclusion: no bus-rear screens, no value-tier inventory
    in high-density residential areas, anywhere in the returned package.
    """
    repos = engines["repos"]
    recommendation = _run(engines, "campaign_1.docx")
    resolved = _resolved(engines, "campaign_1.docx")
    excluded_zones = {
        c.zone_name
        for c in resolved.brief.geography_constraints
        if c.is_exclusion and c.zone_name
    }
    assert excluded_zones, "expected the value-tier residential proxy to exclude >=1 zone"

    for line in recommendation.primary_package.lines:
        screen = repos.screens.get(line.screen_id)
        assert screen is not None
        is_bus_rear = (
            screen.screen_type.value == "bus"
            and screen.position is not None
            and screen.position.value == "back"
        )
        assert not is_bus_rear, (
            f"bus-rear screen {line.screen_id} was recommended despite the hard exclusion"
        )
        if screen.is_static and screen.location_id is not None:
            zone = repos.geography.zone_for_location(screen.location_id)
            zone_name = zone["zone_name"] if zone is not None else None
            assert zone_name not in excluded_zones, (
                f"screen {line.screen_id} in excluded zone {zone_name!r} was recommended"
            )


def test_basil_and_bloom_stays_within_walking_radius(engines: dict) -> None:
    """Brief 4's hyper-local exclusion: every recommended screen must fall
    inside the stated walking radius of the single new outlet — the
    acceptance-test example named explicitly in solution_plan.md Step 2.5.
    """
    repos = engines["repos"]
    recommendation = _run(engines, "campaign_4.docx")
    resolved = _resolved(engines, "campaign_4.docx")
    hyperlocal = [
        c
        for c in resolved.brief.geography_constraints
        if not c.is_exclusion and c.zone_name is not None
    ]
    assert len(hyperlocal) == 1, "expected exactly one zone-level hyperlocal constraint"
    allowed_zone = hyperlocal[0].zone_name
    allowed_city = hyperlocal[0].city_id

    for line in recommendation.primary_package.lines:
        screen = repos.screens.get(line.screen_id)
        assert screen is not None
        assert screen.city_id == allowed_city
        assert screen.is_static and screen.location_id is not None
        zone = repos.geography.zone_for_location(screen.location_id)
        assert zone is not None and zone["zone_name"] == allowed_zone, (
            f"screen {line.screen_id} in zone {zone} falls outside the resolved "
            f"hyperlocal zone {allowed_zone!r}"
        )


def test_every_price_cites_a_cold_start_ladder_rung(engines: dict) -> None:
    """Step 6 exit criterion: every price in every recommendation cites its
    ladder rung, across all six briefs."""
    from agentiq.domain.enums import ColdStartRung

    for scenario in SCENARIOS:
        recommendation = _run(engines, scenario.source_file)
        for line in recommendation.primary_package.lines:
            assert isinstance(line.price_quote.cold_start_rung, ColdStartRung)


def test_every_recommendation_number_validates_against_narrative(engines: dict) -> None:
    """ADR-0001 hard rule: the narrative agent may not alter computed
    numbers. Every figure quoted in `Recommendation.narrative` must match
    the structured `Recommendation.packages` payload exactly."""
    from agentiq.agents.narrative import validate_narrative_matches_recommendation

    for scenario in SCENARIOS:
        recommendation = _run(engines, scenario.source_file)
        # run_brief_to_recommendation already validates internally before
        # returning; re-validating here is the acceptance-level guarantee,
        # independent of that internal call.
        validate_narrative_matches_recommendation(recommendation)
