"""Phase 4 (Steps 4.1-4.3) resolution tests, built per ADR-0005.

Run against the six REAL brief `.docx` files and the real `InMemoryRepositories()`
(no mocking, per this repo's own convention) — the whole point of Phase 4 is
that it resolves real brief language, so hand-built fixtures would test the
wrong thing. Expected values are cross-checked against the independently
hand-read gold parses in `docs/briefs/campaign_*.md` (Step 1.8), not against
this module's own output.
"""

from __future__ import annotations

import pytest

from agentiq.data.briefs import derive_fields, extract_docx_paragraphs, parse_brief
from agentiq.data.paths import ProjectPaths
from agentiq.data.repositories import InMemoryRepositories
from agentiq.data.resolution import (
    ClarificationQuestion,
    load_resolution_config,
    resolve_brief,
)
from agentiq.domain.enums import CampaignObjective, IndustryVertical

paths = ProjectPaths()


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


def _resolve(repos: InMemoryRepositories, filename: str, brief_id: str):
    path = paths.campaigns / filename
    paragraphs = extract_docx_paragraphs(path)
    document = parse_brief(paragraphs, source_file=filename)
    derived = derive_fields(document)
    return resolve_brief(document, derived, repos, brief_id=brief_id)


# --------------------------------------------------------------------------- config
def test_resolution_config_loads() -> None:
    config = load_resolution_config()
    assert config.default_industry_vertical == "retail"
    assert config.default_objective == "awareness"
    assert ("bus-rear", "bus:back") in config.screen_exclusion_phrases.items()


# ------------------------------------------------------------------ per-brief, hand-checked
def test_brief_1_zephyr_ev(repos: InMemoryRepositories) -> None:
    resolved = _resolve(repos, "campaign_1.docx", "B1")
    brief = resolved.brief

    assert brief.industry_vertical == IndustryVertical.AUTO
    assert brief.objective == CampaignObjective.AWARENESS
    assert brief.budget == pytest.approx(40_000.0)
    assert brief.duration_days == 45
    assert brief.target_age_min == 28
    assert brief.target_age_max == 50

    # City resolved from §1 prose ("launching...in Las Hackland"), not the header.
    city_constraints = [c for c in brief.geography_constraints if not c.is_exclusion]
    assert any(c.city_id == "LH" for c in city_constraints)

    assert {"business_district_platform", "auto_retail_arterial_corridor"} <= set(
        brief.requested_environment_types
    )

    # Hard exclusions: bus-rear (type:position) + the value-tier residential proxy.
    assert "bus:back" in brief.screen_type_exclusions
    excluded_zones = {
        c.zone_name for c in brief.geography_constraints if c.is_exclusion and c.zone_name
    }
    assert excluded_zones, "expected at least one value-tier residential zone excluded"
    # docs/briefs/campaign_1.md §4 hand-derived this exact zone set.
    assert excluded_zones <= {
        "Market Quarter",
        "Old Mill District",
        "Riverside Junction",
        "Uptown Crescent",
    }


def test_brief_2_ember_energy_city_unstated(repos: InMemoryRepositories) -> None:
    resolved = _resolve(repos, "campaign_2.docx", "B2")
    brief = resolved.brief

    assert brief.industry_vertical == IndustryVertical.CPG
    assert brief.objective == CampaignObjective.CONVERSION  # "Trial" precedes nothing else
    assert brief.budget == pytest.approx(12_000.0)
    assert brief.duration_days == 21

    # No city stated anywhere -> no geography constraint at all, not a guess.
    assert not any(not c.is_exclusion for c in brief.geography_constraints)
    assert any(
        "city" in q.question.lower() and q.blocking for q in resolved.clarifications
    )

    assert {
        "nightlife_entertainment_corridor",
        "campus_edge_transit_node",
        "event_venue_precinct",
    } <= set(brief.requested_environment_types)

    # "late evening through early morning" -> blocks 6 and 1.
    assert set(brief.time_block_ids) >= {6, 1}


def test_brief_3_loom_and_thread_weekend(repos: InMemoryRepositories) -> None:
    resolved = _resolve(repos, "campaign_3.docx", "B3")
    brief = resolved.brief

    assert brief.industry_vertical == IndustryVertical.RETAIL
    assert brief.objective == CampaignObjective.CONVERSION  # "Footfall" precedes "Awareness"
    assert brief.weekend_weighting == pytest.approx(1.0)
    assert {"premium_mall_entry", "high_street_retail_corridor"} <= set(
        brief.requested_environment_types
    )


def test_brief_4_basil_and_bloom_hyperlocal(repos: InMemoryRepositories) -> None:
    resolved = _resolve(repos, "campaign_4.docx", "B4")
    brief = resolved.brief

    assert brief.objective == CampaignObjective.CONVERSION  # "Footfall" precedes "Recall"
    assert brief.budget == pytest.approx(9_000.0)
    assert brief.duration_days == 15

    # City resolved from §1 prose ("Las Hackland's business district").
    assert any(c.city_id == "LH" and not c.is_exclusion for c in brief.geography_constraints)

    # The zone-level hyperlocal default: exactly one non-exclusion zone constraint,
    # narrowing far tighter than "all of LH".
    non_exclusion_zones = [
        c.zone_name
        for c in brief.geography_constraints
        if not c.is_exclusion and c.zone_name is not None
    ]
    assert len(non_exclusion_zones) == 1
    assert "hyperlocal_walking_radius" in brief.requested_environment_types

    # The outlet-identification gap must be surfaced as a blocking clarification,
    # per the plan's own acceptance-scenario language ("stays within its walking radius").
    assert any(
        "office park" in q.question.lower() or "outlet" in q.question.lower()
        for q in resolved.clarifications
    )
    assert any(q.blocking for q in resolved.clarifications)


def test_brief_5_skynimbus_multi_environment(repos: InMemoryRepositories) -> None:
    resolved = _resolve(repos, "campaign_5.docx", "B5")
    brief = resolved.brief

    assert brief.industry_vertical == IndustryVertical.HOSPITALITY
    assert brief.objective == CampaignObjective.AWARENESS
    assert brief.budget == pytest.approx(35_000.0)
    assert brief.duration_days == 40
    assert any(c.city_id == "LH" and not c.is_exclusion for c in brief.geography_constraints)
    assert {
        "airport_transit_corridor",
        "premium_business_core",
        "financial_district_node",
    } <= set(brief.requested_environment_types)


def test_brief_6_lumiere_weekend_and_gender_gap(repos: InMemoryRepositories) -> None:
    resolved = _resolve(repos, "campaign_6.docx", "B6")
    brief = resolved.brief

    assert brief.industry_vertical == IndustryVertical.RETAIL
    assert brief.objective == CampaignObjective.AWARENESS
    assert brief.weekend_weighting is not None and brief.weekend_weighting > 0
    assert {
        "mall_beauty_retail_entry",
        "high_street_retail_corridor",
        "central_metro_entry",
    } <= set(brief.requested_environment_types)
    # No city stated for brief 6 either.
    assert not any(not c.is_exclusion for c in brief.geography_constraints)


# --------------------------------------------------------------------------- property tests
_ALL_BRIEFS = tuple(f"campaign_{i}.docx" for i in range(1, 7))


@pytest.mark.parametrize("filename", _ALL_BRIEFS)
def test_every_real_brief_resolves_to_a_valid_campaign_brief(
    repos: InMemoryRepositories, filename: str
) -> None:
    resolved = _resolve(repos, filename, filename)
    assert resolved.brief.budget > 0
    assert resolved.brief.duration_days > 0
    assert isinstance(resolved.brief.industry_vertical, IndustryVertical)
    assert isinstance(resolved.brief.objective, CampaignObjective)


@pytest.mark.parametrize("filename", _ALL_BRIEFS)
def test_every_clarification_states_a_default_assumption(
    repos: InMemoryRepositories, filename: str
) -> None:
    resolved = _resolve(repos, filename, filename)
    for question in resolved.clarifications:
        assert isinstance(question, ClarificationQuestion)
        assert question.question
        assert question.default_assumption


@pytest.mark.parametrize("filename", _ALL_BRIEFS)
def test_nothing_from_derived_unresolved_requirements_is_dropped(
    repos: InMemoryRepositories, filename: str
) -> None:
    path = paths.campaigns / filename
    document = parse_brief(extract_docx_paragraphs(path), source_file=filename)
    derived = derive_fields(document)
    resolved = resolve_brief(document, derived, repos, brief_id=filename)
    assert set(derived.unresolved_requirements) <= set(resolved.brief.unresolved_requirements)
