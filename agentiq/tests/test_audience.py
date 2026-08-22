"""Phase 3 (D1) exit-criteria tests, Steps 3.1-3.5.

Property tests against the real repositories (this repo's convention, no
mocking) plus two pure-math property tests (concavity, sub-additivity) that
hold by construction rather than being checked against one sampled value.
Profile-building tests use a bounded sample of screens, not the full 11,163
— `AudienceProfileEngine.build_all()` is a real ~75s offline precompute
(verified manually against the full network, matching Step 1.7's "0.0%
coverage gap" finding exactly); sampling keeps this suite fast while still
exercising the real data end to end.
"""

from __future__ import annotations

import random

import pytest

from agentiq.audience import AudienceProfileEngine, InMemoryAudienceProfileRepository
from agentiq.audience.reach import attention_factor, impressions, unique_reach
from agentiq.audience.semantic import ALLOWED_ENVIRONMENT_TYPES
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.inventory import TIME_BLOCK_IDS

_SAMPLE_SIZE = 40


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def engine(repos: InMemoryRepositories) -> AudienceProfileEngine:
    return AudienceProfileEngine(repos)


@pytest.fixture(scope="module")
def static_sample(repos: InMemoryRepositories):
    static_screens = [s for s in repos.screens.all() if s.is_static]
    return random.Random(0).sample(static_screens, _SAMPLE_SIZE)


@pytest.fixture(scope="module")
def mobile_sample(repos: InMemoryRepositories):
    mobile_screens = [s for s in repos.screens.all() if s.is_mobile]
    return random.Random(0).sample(mobile_screens, _SAMPLE_SIZE)


# --------------------------------------------------------------------------- pure math (3.5)
def test_attention_factor_is_concave_and_one_at_single_slot() -> None:
    assert attention_factor(1, alpha=0.25) == pytest.approx(1.0)
    for slots in range(1, 6):
        doubled = min(slots * 2, 6)
        assert attention_factor(doubled, alpha=0.25) < 2 * attention_factor(slots, alpha=0.25)


@pytest.mark.parametrize("exposure", [100.0, 5_000.0, 250_000.0])
def test_impressions_concavity_doubling_slots_never_doubles_impressions(exposure: float) -> None:
    for slots in (1, 2, 3):
        base = impressions(exposure, slots, alpha=0.25)
        doubled = impressions(exposure, slots * 2, alpha=0.25)
        assert doubled < 2 * base


@pytest.mark.parametrize(
    "a,b", [(0.0, 0.0), (100.0, 0.0), (500.0, 500.0), (10_000.0, 1.0), (3_000.0, 7_000.0)]
)
def test_unique_reach_is_subadditive(a: float, b: float) -> None:
    scale = 5000.0
    combined = unique_reach(a + b, scale=scale)
    separate = unique_reach(a, scale=scale) + unique_reach(b, scale=scale)
    assert combined <= separate + 1e-9


def test_unique_reach_never_exceeds_gross_impressions_via_reach_estimate(
    engine: AudienceProfileEngine, static_sample
) -> None:
    slots_by_screen = {s.screen_id: 3 for s in static_sample[:5]}
    reach = engine.reach_for(slots_by_screen, time_block_id=3)
    assert reach.unique_reach <= reach.gross_impressions + 1e-6
    assert reach.frequency == pytest.approx(
        reach.gross_impressions / reach.unique_reach if reach.unique_reach > 0 else 0.0
    )


# --------------------------------------------------------------------------- static (3.1)
def test_static_profile_daypart_weights_sum_to_one(
    engine: AudienceProfileEngine, static_sample
) -> None:
    for screen in static_sample:
        profile = engine.profile(screen)
        assert sum(profile.daypart_weight_weekday.values()) == pytest.approx(1.0, abs=1e-6)
        assert sum(profile.daypart_weight_weekend.values()) == pytest.approx(1.0, abs=1e-6)
        assert set(profile.daypart_weight_weekday) == set(TIME_BLOCK_IDS)


def test_static_profile_has_no_coverage_gap(engine: AudienceProfileEngine, static_sample) -> None:
    # Step 1.7 §4: every static screen has POI or ridership coverage, 0.0% gap.
    for screen in static_sample:
        assert engine.profile(screen).has_history is True


def test_static_profile_market_tier_matches_city(
    engine: AudienceProfileEngine, repos: InMemoryRepositories, static_sample
) -> None:
    from agentiq.domain.enums import MarketTier

    for screen in static_sample:
        profile = engine.profile(screen)
        city = repos.geography.city(screen.city_id)
        assert profile.market_tier == MarketTier(city["market_tier"])


# --------------------------------------------------------------------------- mobile (3.2)
def test_mobile_profile_daypart_weights_sum_to_one(
    engine: AudienceProfileEngine, mobile_sample
) -> None:
    for screen in mobile_sample:
        profile = engine.profile(screen)
        assert sum(profile.daypart_weight_weekday.values()) == pytest.approx(1.0, abs=1e-6)


def test_static_and_mobile_exposure_are_a_comparable_scale(
    engine: AudienceProfileEngine, static_sample, mobile_sample
) -> None:
    # Exit criterion: static and mobile land on a comparable scale, not
    # orders of magnitude apart, since both are built from the same
    # primitives (resident/POI footfall, ridership) rather than independently
    # normalised constants.
    static_median = sorted(engine.profile(s).est_daily_exposure for s in static_sample)[
        len(static_sample) // 2
    ]
    mobile_median = sorted(engine.profile(s).est_daily_exposure for s in mobile_sample)[
        len(mobile_sample) // 2
    ]
    ratio = static_median / mobile_median
    assert 0.05 <= ratio <= 20.0


# --------------------------------------------------------------------------- semantic (3.3)
def test_environment_labels_are_always_in_the_controlled_vocabulary(
    engine: AudienceProfileEngine, static_sample, mobile_sample
) -> None:
    for screen in [*static_sample, *mobile_sample]:
        profile = engine.profile(screen)
        assert set(profile.environment_labels) <= ALLOWED_ENVIRONMENT_TYPES


# --------------------------------------------------------------------------- overlap (3.4)
def test_screens_at_the_same_location_fully_overlap(
    engine: AudienceProfileEngine, repos: InMemoryRepositories
) -> None:
    by_location: dict[str, list[str]] = {}
    for screen in repos.screens.all():
        if screen.is_static and screen.location_id is not None:
            by_location.setdefault(screen.location_id, []).append(screen.screen_id)
    location_id, screen_ids = max(by_location.items(), key=lambda kv: len(kv[1]))
    assert len(screen_ids) >= 2

    graph = engine.overlap_graph()
    from agentiq.audience.overlap import overlap_for

    assert overlap_for(graph, screen_ids[0], screen_ids[1]) == pytest.approx(1.0)


def test_overlap_coefficients_are_bounded_zero_to_one(engine: AudienceProfileEngine) -> None:
    graph = engine.overlap_graph()
    assert graph  # non-empty on the real network
    assert all(0.0 <= v <= 1.0 for v in graph.values())


# --------------------------------------------------------------------------- repository wiring
def test_in_memory_audience_profile_repository_matches_engine(
    engine: AudienceProfileEngine, static_sample
) -> None:
    repo = InMemoryAudienceProfileRepository(engine)
    screen = static_sample[0]
    assert repo.get(screen.screen_id) == engine.profile(screen)
    assert repo.get("not-a-real-screen-id") is None
