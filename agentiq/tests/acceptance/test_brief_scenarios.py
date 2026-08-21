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
from tests.acceptance.fixtures import SCENARIOS, AcceptanceScenario

paths = ProjectPaths()


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
_E2E_REASON = (
    "Phase 8 orchestrator (parse_brief -> ... -> compose_recommendation) is not built "
    "yet — see solution_plan.md Phase 8. Collected here per Step 2.5 so the definition "
    "of done is visible before the code exists."
)


@pytest.mark.xfail(reason=_E2E_REASON, strict=True)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"brief_{s.brief_number}")
def test_recommendation_only_uses_required_environments(scenario: AcceptanceScenario) -> None:
    """Every recommended screen's audience profile must carry at least one of
    this brief's expected environment labels — a premium brief must not be
    padded with unrelated inventory just to hit a budget.
    """
    from agentiq.agents import run_brief_to_recommendation  # Phase 8, not yet built

    recommendation = run_brief_to_recommendation(paths.campaigns / scenario.source_file)
    for package in recommendation.packages:
        for _line in package.lines:
            raise AssertionError("Phase 8 not implemented")


@pytest.mark.xfail(reason=_E2E_REASON, strict=True)
def test_zephyr_ev_excludes_bus_rear_and_value_tier_residential() -> None:
    """Brief 1's hard exclusion: no bus-rear screens, no value-tier inventory
    in high-density residential areas, anywhere in the returned package.
    """
    from agentiq.agents import run_brief_to_recommendation

    run_brief_to_recommendation(paths.campaigns / "campaign_1.docx")
    raise AssertionError("Phase 8 not implemented")


@pytest.mark.xfail(reason=_E2E_REASON, strict=True)
def test_basil_and_bloom_stays_within_walking_radius() -> None:
    """Brief 4's hyper-local exclusion: every recommended screen must fall
    inside the stated walking radius of the single new outlet — the
    acceptance-test example named explicitly in solution_plan.md Step 2.5.
    """
    from agentiq.agents import run_brief_to_recommendation

    run_brief_to_recommendation(paths.campaigns / "campaign_4.docx")
    raise AssertionError("Phase 8 not implemented")


@pytest.mark.xfail(reason=_E2E_REASON, strict=True)
def test_every_price_cites_a_cold_start_ladder_rung() -> None:
    """Step 6 exit criterion: every price in every recommendation cites its
    ladder rung, across all six briefs."""
    from agentiq.agents import run_brief_to_recommendation

    for scenario in SCENARIOS:
        run_brief_to_recommendation(paths.campaigns / scenario.source_file)
        raise AssertionError("Phase 8 not implemented")


@pytest.mark.xfail(reason=_E2E_REASON, strict=True)
def test_every_recommendation_number_validates_against_narrative() -> None:
    """ADR-0001 hard rule: the narrative agent may not alter computed
    numbers. Every figure quoted in `Recommendation.narrative` must match
    the structured `Recommendation.packages` payload exactly."""
    from agentiq.agents import run_brief_to_recommendation

    for scenario in SCENARIOS:
        run_brief_to_recommendation(paths.campaigns / scenario.source_file)
        raise AssertionError("Phase 8 not implemented")
