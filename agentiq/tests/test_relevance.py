"""Phase 5 (D2) exit-criteria tests, Steps 5.1-5.4.

Property tests against the real repositories (no mocking, this repo's
convention). `RelevanceEngine` construction builds every D1 profile
(~90s) to get a network-wide exposure reference, so it is a module-scoped
fixture built once for this whole file, matching `test_pricing.py`'s and
`test_audience.py`'s pattern.

No Phase 4 (brief intake) resolver exists yet, so `CampaignBrief` fixtures
here are hand-constructed from `tests/acceptance/fixtures.py`'s already
hand-checked ground truth for the six real briefs — the same "measured, not
assumed" standard the rest of this repo holds itself to — rather than a
half-built automated resolver standing in for Phase 4's real scope.
"""

from __future__ import annotations

import pytest

from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.campaign import CampaignBrief, GeographyConstraint
from agentiq.domain.enums import CampaignObjective, IndustryVertical
from agentiq.relevance import RelevanceEngine
from agentiq.relevance.rerank import RankedCandidate, bounded_rerank
from agentiq.relevance.signals import audience_affinity, daypart_alignment, environment_poi_fit


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def engine(repos: InMemoryRepositories) -> RelevanceEngine:
    return RelevanceEngine(repos)


@pytest.fixture(scope="module")
def zephyr_ev_brief() -> CampaignBrief:
    """Brief 1's hand-checked ground truth (`tests/acceptance/fixtures.py` scenario 1)."""
    return CampaignBrief(
        brief_id="campaign_1",
        source_file="campaign_1.docx",
        company="Voltaic Motors Inc.",
        industry_vertical=IndustryVertical.AUTO,
        objective=CampaignObjective.AWARENESS,
        target_age_min=28,
        target_age_max=50,
        budget=40_000.0,
        duration_days=45,
        geography_constraints=(GeographyConstraint(city_id="LH"),),
        screen_type_exclusions=("bus:back",),
        requested_environment_types=(
            "business_district_platform",
            "auto_retail_arterial_corridor",
        ),
    )


# --------------------------------------------------------------------------- 5.1 eligibility
def test_eligibility_matches_the_measured_bus_rear_exclusion_count(
    engine: RelevanceEngine, repos: InMemoryRepositories, zephyr_ev_brief: CampaignBrief
) -> None:
    # docs/briefs/campaign_1.md §4: 135 bus-rear screens in LH, out of 6,304
    # total LH screens (data_dictionary.md) -> 6,169 eligible.
    results = engine.eligible_screens(zephyr_ev_brief)
    eligible_ids = {r.screen_id for r in results if r.eligible}
    assert len(eligible_ids) == 6_169
    assert all(s.city_id == "LH" for s in repos.screens.all() if s.screen_id in eligible_ids)


def test_every_eligibility_result_carries_a_reason(
    engine: RelevanceEngine, zephyr_ev_brief: CampaignBrief
) -> None:
    results = engine.eligible_screens(zephyr_ev_brief)
    assert results
    assert all(r.reasons for r in results)


def test_bus_rear_screens_are_excluded_with_a_specific_reason(
    engine: RelevanceEngine, repos: InMemoryRepositories, zephyr_ev_brief: CampaignBrief
) -> None:
    bus_rear = next(
        s
        for s in repos.screens.all()
        if s.city_id == "LH" and s.screen_type.value == "bus" and s.position is not None
        and s.position.value == "back"
    )
    results = engine.eligible_screens(zephyr_ev_brief, (bus_rear,))
    assert len(results) == 1
    assert results[0].eligible is False
    assert "bus:back" in results[0].reasons[0]


def test_out_of_city_screens_are_excluded(
    engine: RelevanceEngine, repos: InMemoryRepositories, zephyr_ev_brief: CampaignBrief
) -> None:
    acs_screen = next(s for s in repos.screens.all() if s.city_id == "ACS")
    result = engine.eligible_screens(zephyr_ev_brief, (acs_screen,))[0]
    assert result.eligible is False


# --------------------------------------------------------------------------- 5.2 signals (pure)
def test_audience_affinity_full_band_overlap_is_one() -> None:
    from agentiq.domain.campaign import CampaignBrief as CB

    brief = CB(
        brief_id="x",
        source_file="x",
        company="x",
        industry_vertical=IndustryVertical.RETAIL,
        objective=CampaignObjective.AWARENESS,
        target_age_min=0,
        target_age_max=100,
        budget=1.0,
        duration_days=1,
    )
    age_bands = {
        "pct_age_under_18": 20.0,
        "pct_age_18_34": 30.0,
        "pct_age_35_54": 30.0,
        "pct_age_55_plus": 20.0,
    }
    assert audience_affinity(brief, age_bands) == pytest.approx(1.0)


def test_audience_affinity_no_reference_is_neutral() -> None:
    brief = CampaignBrief(
        brief_id="x",
        source_file="x",
        company="x",
        industry_vertical=IndustryVertical.RETAIL,
        objective=CampaignObjective.AWARENESS,
        target_age_min=20,
        target_age_max=30,
        budget=1.0,
        duration_days=1,
    )
    assert audience_affinity(brief, None) == pytest.approx(0.5)


def test_daypart_alignment_no_preference_is_neutral(
    engine: RelevanceEngine, repos: InMemoryRepositories
) -> None:
    brief = CampaignBrief(
        brief_id="x",
        source_file="x",
        company="x",
        industry_vertical=IndustryVertical.RETAIL,
        objective=CampaignObjective.AWARENESS,
        budget=1.0,
        duration_days=1,
    )
    screen = repos.screens.all()[0]
    profile = engine.audience_engine.profile(screen)
    assert daypart_alignment(brief, profile) == pytest.approx(1.0)


def test_environment_poi_fit_no_request_is_neutral(
    engine: RelevanceEngine, repos: InMemoryRepositories
) -> None:
    brief = CampaignBrief(
        brief_id="x",
        source_file="x",
        company="x",
        industry_vertical=IndustryVertical.RETAIL,
        objective=CampaignObjective.AWARENESS,
        budget=1.0,
        duration_days=1,
    )
    screen = repos.screens.all()[0]
    profile = engine.audience_engine.profile(screen)
    assert environment_poi_fit(brief, profile) == pytest.approx(1.0)


def test_environment_poi_fit_is_the_overlap_fraction(
    engine: RelevanceEngine, repos: InMemoryRepositories
) -> None:
    screen = next(s for s in repos.screens.all() if s.is_static)
    profile = engine.audience_engine.profile(screen)
    labels = set(profile.environment_labels)
    if not labels:
        pytest.skip("sampled screen has no environment labels")
    requested = (*labels, "definitely_not_a_real_label")
    brief = CampaignBrief(
        brief_id="x",
        source_file="x",
        company="x",
        industry_vertical=IndustryVertical.RETAIL,
        objective=CampaignObjective.AWARENESS,
        budget=1.0,
        duration_days=1,
        requested_environment_types=requested,
    )
    fit = environment_poi_fit(brief, profile)
    assert fit == pytest.approx(len(labels) / len(requested))


# --------------------------------------------------------------------------- 5.2/5.4 score
def test_score_is_bounded_zero_to_one(
    engine: RelevanceEngine, repos: InMemoryRepositories, zephyr_ev_brief
) -> None:
    eligible = [r.screen_id for r in engine.eligible_screens(zephyr_ev_brief) if r.eligible]
    by_id = {s.screen_id: s for s in repos.screens.all()}
    for screen_id in eligible[:30]:
        result = engine.score(zephyr_ev_brief, by_id[screen_id])
        assert 0.0 <= result.score <= 1.0
        assert result.explanation.contributions


def test_score_weights_sum_to_one_for_every_objective(engine: RelevanceEngine) -> None:
    for objective in CampaignObjective:
        weights = engine.config.weights_for(objective)
        assert sum(weights.as_dict().values()) == pytest.approx(1.0, abs=1e-6)


def test_historical_performance_prior_is_a_small_weight_everywhere(engine: RelevanceEngine) -> None:
    # Step 5.2's explicit rule: this signal must never bury a cold-start screen.
    for objective in CampaignObjective:
        weights = engine.config.weights_for(objective)
        assert weights.historical_performance_prior <= 0.10


# --------------------------------------------------------------------------- 5.1+5.2+5.3 rank()
def test_rank_only_returns_eligible_screens(
    engine: RelevanceEngine, zephyr_ev_brief: CampaignBrief
) -> None:
    eligible_ids = {r.screen_id for r in engine.eligible_screens(zephyr_ev_brief) if r.eligible}
    ranked = engine.rank(zephyr_ev_brief, top_n=50)
    assert {r.screen_id for r in ranked} <= eligible_ids


def test_rank_top_n_respects_the_limit(
    engine: RelevanceEngine, zephyr_ev_brief: CampaignBrief
) -> None:
    ranked = engine.rank(zephyr_ev_brief, top_n=7)
    assert len(ranked) == 7


def test_rank_is_never_far_from_sorted_by_score(
    engine: RelevanceEngine, zephyr_ev_brief: CampaignBrief
) -> None:
    # The bounded rerank may reorder within a tie band, but a screen must
    # never end up ranked above another screen whose score is more than
    # tie_epsilon higher.
    ranked = engine.rank(zephyr_ev_brief, top_n=100)
    tie_epsilon = engine.config.semantic_rerank.tie_epsilon
    for earlier, later in zip(ranked, ranked[1:], strict=False):
        assert later.score <= earlier.score + tie_epsilon


# -------------------------------------------------------------------- 5.3 bounded_rerank (pure)
def test_bounded_rerank_never_reorders_beyond_tie_epsilon() -> None:
    candidates = (
        RankedCandidate("a", 0.90, tiebreak=0),
        RankedCandidate("b", 0.50, tiebreak=5),  # far below "a" - must never move above it
        RankedCandidate("c", 0.49, tiebreak=1),
    )
    order = bounded_rerank(candidates, max_band_positions=5, tie_epsilon=0.02)
    assert order[0] == "a"


def test_bounded_rerank_breaks_real_ties_by_tiebreak() -> None:
    candidates = (
        RankedCandidate("a", 0.50, tiebreak=0),
        RankedCandidate("b", 0.505, tiebreak=3),
    )
    order = bounded_rerank(candidates, max_band_positions=5, tie_epsilon=0.02)
    assert order == ("b", "a")


def test_bounded_rerank_respects_band_size() -> None:
    # Six mutually-tied candidates split into two non-overlapping windows of
    # 3 by max_band_positions; each window is independently sorted by
    # tiebreak descending, so "f" (the global tiebreak maximum) can rise to
    # the top of the *second* window but never all the way to rank 1.
    candidates = tuple(RankedCandidate(chr(ord("a") + i), 0.50, tiebreak=i) for i in range(6))
    order = bounded_rerank(candidates, max_band_positions=3, tie_epsilon=0.02)
    assert order == ("c", "b", "a", "f", "e", "d")


# --------------------------------------------------------------------------- domain
def test_campaign_brief_screen_type_exclusion_convention_round_trips() -> None:
    brief = CampaignBrief(
        brief_id="x",
        source_file="x",
        company="x",
        industry_vertical=IndustryVertical.AUTO,
        objective=CampaignObjective.AWARENESS,
        budget=1.0,
        duration_days=1,
        screen_type_exclusions=("bus:back", "metro_rail_coach"),
    )
    assert brief.screen_type_exclusions == ("bus:back", "metro_rail_coach")
