"""Phase 7 (D4) exit-criteria tests for Steps 7.1/7.2, built per ADR-0004.

Property tests, not spot-checked values (this repo's testing convention,
CLAUDE.md): budget is never violated; the cost-effective-greedy objective
beats the two named naive baselines on reach-per-dollar once overlap is
present; the minimum-relevance-threshold gate is enforced; every returned
`Package` satisfies its domain invariants.

Unlike `test_pricing.py`/`test_audience.py`, these tests build every fixture
by hand rather than constructing `InMemoryRepositories()` — `optimizer/
candidates.py` and `optimizer/greedy.py` are deliberately repository-free
(ADR-0004 §6), and `bookings.csv` (required to construct
`InMemoryRepositories`) is not present on every checkout. This also means
these tests exercise exactly the same code path a caller with real D1/D3
repositories would hit, just with hand-supplied inputs instead of ones read
from disk.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from agentiq.domain import (
    CampaignBrief,
    ColdStartRung,
    Confidence,
    Explanation,
    IndustryVertical,
    PriceQuote,
    RelevanceScore,
    Screen,
    ScreenSize,
    ScreenType,
)
from agentiq.domain.enums import CampaignObjective
from agentiq.optimizer.candidates import (
    RELEVANCE_DEFAULTED_FALLBACK,
    make_candidate,
)
from agentiq.optimizer.greedy import (
    cheapest_first,
    cost_effective_greedy,
    greedy_by_relevance,
)

REACH_SCALE = 500.0


def _explanation(confidence: Confidence = Confidence.HIGH) -> Explanation:
    return Explanation(headline="test", confidence=confidence, confidence_reason="fixture")


def _screen(screen_id: str, *, location_id: str = "LOC-1") -> Screen:
    return Screen(
        screen_id=screen_id,
        city_id="LH",
        screen_type=ScreenType.METRO_STATION,
        screen_size=ScreenSize.M,
        location_id=location_id,
    )


def _price_quote(screen_id: str, recommended: float) -> PriceQuote:
    return PriceQuote(
        screen_id=screen_id,
        time_block_id=3,
        slots=1,
        floor=recommended * 0.8,
        target=recommended,
        cap=recommended * 1.5,
        recommended=recommended,
        win_probability_at_recommended=0.5,
        cold_start_rung=ColdStartRung.SCREEN_OWN_HISTORY,
        confidence=Confidence.HIGH,
        explanation=_explanation(),
    )


def _brief(*, budget: float, min_relevance: float = 0.0, exclusions: tuple = ()) -> CampaignBrief:
    return CampaignBrief(
        brief_id="B1",
        source_file="campaign_1.docx",
        company="Test Co",
        industry_vertical=IndustryVertical.RETAIL,
        objective=CampaignObjective.AWARENESS,
        budget=budget,
        duration_days=10,
        minimum_relevance_threshold=min_relevance,
        geography_constraints=exclusions,
    )


def _candidate(
    screen_id: str,
    cost_per_slot_day: float,
    *,
    relevance: RelevanceScore | None = None,
    location_id: str = "LOC-1",
    days: int = 1,
):
    end = dt.date(2026, 9, 1) + dt.timedelta(days=days - 1)
    return make_candidate(
        _screen(screen_id, location_id=location_id),
        time_block_id=3,
        slots=1,
        start_date=dt.date(2026, 9, 1),
        end_date=end,
        price_quote=_price_quote(screen_id, cost_per_slot_day),
        relevance_score=relevance,
        neutral_relevance_score=1.0,
    )


# --------------------------------------------------------------------------- candidates.py
def test_relevance_defaults_to_neutral_and_is_flagged() -> None:
    candidate = _candidate("S1", 10.0, relevance=None)
    assert candidate.relevance_score == 1.0
    assert candidate.relevance_is_defaulted is True


def test_real_relevance_score_is_used_and_not_flagged() -> None:
    score = RelevanceScore(
        screen_id="S1", brief_id="B1", score=0.42, explanation=_explanation()
    )
    candidate = _candidate("S1", 10.0, relevance=score)
    assert candidate.relevance_score == 0.42
    assert candidate.relevance_is_defaulted is False


def test_candidate_cost_matches_package_line_value_formula() -> None:
    candidate = _candidate("S1", 25.0, days=4)
    assert candidate.cost == pytest.approx(25.0 * 1 * 4)


# --------------------------------------------------------------------------- greedy.py: budget
@pytest.mark.parametrize("strategy", [cost_effective_greedy, cheapest_first, greedy_by_relevance])
def test_no_strategy_ever_exceeds_budget(strategy) -> None:
    candidates = tuple(_candidate(f"S{i}", 7.0) for i in range(1, 8))  # 7 * $7 = $49
    budget = 20.0  # affords at most 2
    result = strategy(
        candidates,
        overlap_graph={},
        budget=budget,
        reach_saturation_scale=REACH_SCALE,
        impressions_for=lambda c: 100.0,
    )
    assert result.total_cost <= budget + 1e-9


def test_greedy_never_selects_a_single_candidate_over_budget() -> None:
    candidates = (_candidate("S1", 1000.0),)
    result = cost_effective_greedy(
        candidates,
        overlap_graph={},
        budget=10.0,
        reach_saturation_scale=REACH_SCALE,
        impressions_for=lambda c: 100.0,
    )
    assert result.selected == ()
    assert result.total_cost == 0.0


# ------------------------------------------------------------------ greedy.py: overlap-awareness
def test_cost_effective_greedy_beats_cheapest_first_when_overlap_is_present() -> None:
    """Three co-located, fully-overlapping cheap screens vs. one pricier,
    non-overlapping screen with almost as much raw impressions. Naive
    cheapest-first buys the overlapping duplicates (Step 7.2's own example
    of the status quo: "rank and fill until budget runs out"); the
    overlap-aware objective recognizes the second co-located screen adds
    almost nothing and prefers the fresh audience instead."""
    same_location = [_candidate(f"S{i}", 10.0, location_id="LOC-A") for i in (1, 2, 3)]
    fresh_audience = _candidate("S4", 10.0, location_id="LOC-B")
    candidates = tuple(same_location) + (fresh_audience,)

    overlap_graph = {
        ("S1", "S2"): 1.0,
        ("S1", "S3"): 1.0,
        ("S2", "S3"): 1.0,
    }

    def impressions_for(c) -> float:
        return 90.0 if c.screen_id == "S4" else 100.0

    budget = 20.0  # affords exactly two $10 screens

    greedy_result = cost_effective_greedy(
        candidates,
        overlap_graph,
        budget,
        reach_saturation_scale=REACH_SCALE,
        impressions_for=impressions_for,
    )
    cheapest_result = cheapest_first(
        candidates,
        overlap_graph,
        budget,
        reach_saturation_scale=REACH_SCALE,
        impressions_for=impressions_for,
    )

    # Cheapest-first has no overlap signal and (by construction of the
    # candidate order) buys two of the co-located screens.
    assert set(cheapest_result.screen_ids) == {"S1", "S2"}
    # The overlap-aware objective avoids stacking fully-redundant audience
    # and picks the non-overlapping screen instead, for strictly more reach
    # at the same total cost.
    assert "S4" in greedy_result.screen_ids
    assert greedy_result.total_cost == pytest.approx(cheapest_result.total_cost)
    assert greedy_result.reach.unique_reach > cheapest_result.reach.unique_reach


def test_cost_effective_greedy_beats_greedy_by_relevance_when_overlap_is_present() -> None:
    """Same overlap trap, but the naive baseline sorts by relevance instead
    of price — three co-located screens all outrank the fresh-audience
    screen on relevance alone, so a pure-relevance fill also buys
    redundant audience."""
    same_location = [
        _candidate(
            f"S{i}",
            10.0,
            location_id="LOC-A",
            relevance=RelevanceScore(
                screen_id=f"S{i}", brief_id="B1", score=0.9, explanation=_explanation()
            ),
        )
        for i in (1, 2, 3)
    ]
    fresh_audience = _candidate(
        "S4",
        10.0,
        location_id="LOC-B",
        relevance=RelevanceScore(
            screen_id="S4", brief_id="B1", score=0.5, explanation=_explanation()
        ),
    )
    candidates = tuple(same_location) + (fresh_audience,)
    overlap_graph = {("S1", "S2"): 1.0, ("S1", "S3"): 1.0, ("S2", "S3"): 1.0}

    def impressions_for(c) -> float:
        return 90.0 if c.screen_id == "S4" else 100.0

    budget = 20.0

    greedy_result = cost_effective_greedy(
        candidates, overlap_graph, budget,
        reach_saturation_scale=REACH_SCALE, impressions_for=impressions_for,
    )
    relevance_result = greedy_by_relevance(
        candidates, overlap_graph, budget,
        reach_saturation_scale=REACH_SCALE, impressions_for=impressions_for,
    )

    assert set(relevance_result.screen_ids) == {"S1", "S2"}
    assert greedy_result.reach.unique_reach > relevance_result.reach.unique_reach


def test_best_singleton_beats_greedy_when_one_candidate_dominates() -> None:
    """The scenario the best-singleton comparison exists for (ADR-0004
    decision 3). Five $1 candidates all fully overlap each other (one
    audience, coefficient 1.0) but individually have a better reach/dollar
    ratio than the one $5 candidate, so greedy-by-ratio picks one of them
    first — then every other $1 candidate has zero marginal gain (full
    overlap) and the $5 candidate no longer fits the $4 left in the budget,
    so plain greedy-by-ratio gets stuck with one $1 pick. The best-singleton
    comparison (evaluated against the *original* budget) recovers the $5
    candidate's strictly larger reach instead."""
    small = [
        _candidate(f"S{i}", 1.0, location_id=f"LOC-{i}") for i in range(1, 6)
    ]  # reach alone ~= 90.6, ratio ~= 90.6/$
    dominant = _candidate("BIG", 5.0, location_id="LOC-BIG")  # reach alone ~= 300, ratio ~= 60/$
    candidates = tuple(small) + (dominant,)

    overlap_graph = {
        (a.screen_id, b.screen_id): 1.0
        for i, a in enumerate(small)
        for b in small[i + 1 :]
    }

    def impressions_for(c) -> float:
        return 458.0 if c.screen_id == "BIG" else 100.0

    result = cost_effective_greedy(
        candidates,
        overlap_graph,
        budget=5.0,
        reach_saturation_scale=REACH_SCALE,
        impressions_for=impressions_for,
    )
    assert result.screen_ids == ("BIG",)
    assert "singleton" in result.strategy
    assert result.total_cost == pytest.approx(5.0)


# --------------------------------------------------------------------------- eligibility
def test_minimum_relevance_threshold_excludes_low_scoring_candidates() -> None:
    from agentiq.optimizer.candidates import filter_eligible

    brief = _brief(budget=1000.0, min_relevance=0.5)
    low = _candidate(
        "LOW",
        10.0,
        relevance=RelevanceScore(
            screen_id="LOW", brief_id="B1", score=0.2, explanation=_explanation()
        ),
    )
    high = _candidate(
        "HIGH",
        10.0,
        relevance=RelevanceScore(
            screen_id="HIGH", brief_id="B1", score=0.8, explanation=_explanation()
        ),
    )
    eligible, rejections = filter_eligible((low, high), brief)

    assert [c.screen_id for c in eligible] == ["HIGH"]
    assert rejections[0].screen_id == "LOW"
    assert "relevance_score" in rejections[0].reason


def test_screen_type_exclusion_is_enforced() -> None:
    from agentiq.optimizer.candidates import filter_eligible

    excluded_type_screen = make_candidate(
        Screen(
            screen_id="BUSREAR",
            city_id="LH",
            screen_type=ScreenType.BUS,
            screen_size=ScreenSize.S,
            vehicle_id="V1",
        ),
        time_block_id=3,
        slots=1,
        start_date=dt.date(2026, 9, 1),
        end_date=dt.date(2026, 9, 1),
        price_quote=_price_quote("BUSREAR", 10.0),
        relevance_score=None,
        neutral_relevance_score=1.0,
    )
    normal = _candidate("S1", 10.0)
    brief = _brief(budget=1000.0, exclusions=())
    brief = brief.model_copy(update={"screen_type_exclusions": ("bus",)})

    eligible, rejections = filter_eligible((excluded_type_screen, normal), brief)
    assert [c.screen_id for c in eligible] == ["S1"]
    assert rejections[0].screen_id == "BUSREAR"
    assert "bus" in rejections[0].reason


# --------------------------------------------------------------------------- fallback surfacing
def test_relevance_defaulted_fallback_constant_is_stable() -> None:
    # Guards against accidentally renaming the string a UI/test elsewhere
    # might already depend on.
    assert RELEVANCE_DEFAULTED_FALLBACK == "relevance_score_defaulted_neutral_pending_D2"


# --------------------------------------------------------------------------- Package assembly
def test_package_line_construction_from_a_selected_candidate_is_valid() -> None:
    from agentiq.domain import Package, PackageLine

    candidate = _candidate("S1", 25.0)
    line = PackageLine(
        screen_id=candidate.screen_id,
        time_block_id=candidate.time_block_id,
        slots=candidate.slots,
        start_date=candidate.start_date,
        end_date=candidate.end_date,
        price_quote=candidate.price_quote,
        relevance_score=candidate.relevance_score,
    )

    result = cost_effective_greedy(
        (candidate,),
        overlap_graph={},
        budget=100.0,
        reach_saturation_scale=REACH_SCALE,
        impressions_for=lambda c: 50.0,
    )
    package = Package(
        package_id="PKG-1",
        brief_id="B1",
        label="max-reach",
        lines=(line,),
        reach=result.reach,
        total_budget_used=result.total_cost,
        optimizer_strategy=result.strategy,
        optimizer_guarantee=result.guarantee,
        explanation=_explanation(),
    )
    assert package.total_budget_used == pytest.approx(candidate.cost)


def test_package_requires_at_least_one_line() -> None:
    from agentiq.domain import Package, ReachEstimate

    with pytest.raises(ValidationError):
        Package(
            package_id="PKG-EMPTY",
            brief_id="B1",
            label="max-reach",
            lines=(),
            reach=ReachEstimate(
                gross_impressions=0, unique_reach=0, frequency=0.0, explanation=_explanation()
            ),
            total_budget_used=0.0,
            optimizer_strategy="cost_effective_greedy",
            explanation=_explanation(),
        )
