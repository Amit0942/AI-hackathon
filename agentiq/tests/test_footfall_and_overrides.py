"""Phase 6 (D3) Steps 6.2 (footfall forecast) and 6.6 (human overrides) tests.

Property tests against the real repositories, matching this repo's
convention (`tests/test_pricing.py`) — no mocking. Steps 6.1/6.3/6.4/6.5 were
already tested there; this file covers only the two steps this pass adds.
"""

from __future__ import annotations

import datetime as dt
import random

import pytest

from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.pricing import FootfallForecast
from agentiq.pricing import PricingEngine


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def engine(repos: InMemoryRepositories) -> PricingEngine:
    return PricingEngine(repos)


@pytest.fixture(scope="module")
def sample_screens(repos: InMemoryRepositories):
    static = [s for s in repos.screens.all() if s.is_static]
    mobile = [s for s in repos.screens.all() if s.is_mobile]
    rng = random.Random(0)
    return rng.sample(static, 10) + rng.sample(mobile, 10)


# --------------------------------------------------------------------------- 6.2 forecast_footfall
def test_forecast_footfall_confidence_interval_contains_the_point_estimate(
    engine: PricingEngine, repos: InMemoryRepositories, sample_screens
) -> None:
    start = repos.as_of_date + dt.timedelta(days=14)
    end = start + dt.timedelta(days=6)
    for screen in sample_screens:
        forecast = engine.forecast_footfall(screen, 3, start, end)
        assert forecast.confidence_interval_low <= forecast.expected_total_footfall
        assert forecast.expected_total_footfall <= forecast.confidence_interval_high
        assert forecast.window_days == 7


def test_forecast_footfall_expected_daily_times_window_equals_total(
    engine: PricingEngine, repos: InMemoryRepositories, sample_screens
) -> None:
    start = repos.as_of_date + dt.timedelta(days=14)
    end = start + dt.timedelta(days=9)
    for screen in sample_screens[:5]:
        forecast = engine.forecast_footfall(screen, 5, start, end)
        assert forecast.expected_daily_footfall * forecast.window_days == pytest.approx(
            forecast.expected_total_footfall, rel=1e-9
        )


def test_forecast_footfall_wider_window_widens_the_interval(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    # std scales with sqrt(n_days) for a fixed daily rate/CV, so a longer
    # window's absolute band should never be narrower than a shorter one
    # starting the same day (Step 6.2 exit criterion: "a forecast without a
    # confidence interval is a guess" implies the interval must behave
    # sensibly as the window grows, not just exist).
    screen = next(s for s in repos.screens.all() if s.is_static)
    start = repos.as_of_date + dt.timedelta(days=14)

    short = engine.forecast_footfall(screen, 3, start, start + dt.timedelta(days=1))
    long = engine.forecast_footfall(screen, 3, start, start + dt.timedelta(days=13))
    short_width = short.confidence_interval_high - short.confidence_interval_low
    long_width = long.confidence_interval_high - long.confidence_interval_low
    assert long_width >= short_width


def test_forecast_footfall_rejects_end_before_start(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    start = repos.as_of_date + dt.timedelta(days=14)
    with pytest.raises(ValueError):
        engine.forecast_footfall(screen, 3, start, start - dt.timedelta(days=1))


def test_footfall_forecast_domain_type_rejects_interval_not_containing_total() -> None:
    from agentiq.domain.enums import Confidence
    from agentiq.domain.explanation import Explanation

    explanation = Explanation(
        headline="test", confidence=Confidence.MEDIUM, confidence_reason="test"
    )
    with pytest.raises(ValueError):
        FootfallForecast(
            screen_id="X",
            time_block_id=1,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 1),
            expected_total_footfall=100.0,
            expected_daily_footfall=100.0,
            confidence_interval_low=200.0,  # above the point estimate — invalid
            confidence_interval_high=300.0,
            explanation=explanation,
        )


# --------------------------------------------------------------------------- 6.6 apply_overrides
def test_apply_overrides_empty_dict_is_a_no_op(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
    assert engine.apply_overrides(quote, {}) is quote


def test_apply_overrides_rejects_unknown_field(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
    with pytest.raises(ValueError):
        engine.apply_overrides(quote, {"made_up_field": 1.0})


def test_apply_overrides_rejects_unknown_strategic_discount_intent(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
    with pytest.raises(ValueError):
        engine.apply_overrides(quote, {"strategic_discount_intent": "extreme"})


def test_apply_overrides_expected_footfall_is_clamped_by_the_demand_guardrail(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
    baseline = 1000.0
    # An absurdly large rep-supplied footfall claim must not move the target
    # further than the Step 6.3 demand multiplier's own uplift ceiling.
    overridden = engine.apply_overrides(
        quote, {"expected_footfall": baseline * 100}, model_expected_footfall=baseline
    )
    max_target = quote.target * (1.0 + engine.config.max_uplift_pct)
    assert overridden.target <= max_target + 1e-6
    assert "human_override_expected_footfall_clamped_by_demand_guardrail" in (
        overridden.explanation.fallbacks_used
    )


def test_apply_overrides_without_baseline_logs_fallback_and_does_not_change_target(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
    overridden = engine.apply_overrides(quote, {"expected_footfall": 999_999.0})
    assert overridden.target == pytest.approx(quote.target)
    assert "human_override_expected_footfall_ignored_no_model_baseline" in (
        overridden.explanation.fallbacks_used
    )


def test_apply_overrides_competitive_intel_never_widens_the_cap(
    engine: PricingEngine, repos: InMemoryRepositories, sample_screens
) -> None:
    for screen in sample_screens:
        quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
        overridden = engine.apply_overrides(quote, {"competitive_intel": "competitor named X"})
        assert overridden.cap <= quote.cap + 1e-6


def test_apply_overrides_band_invariant_holds_across_combinations(
    engine: PricingEngine, repos: InMemoryRepositories, sample_screens
) -> None:
    override_sets = [
        {"expected_footfall": 50_000.0},
        {"strategic_discount_intent": "aggressive"},
        {"competitive_intel": "a competitor undercut us"},
        {
            "expected_footfall": 5_000.0,
            "strategic_discount_intent": "moderate",
            "competitive_intel": "note",
        },
    ]
    for screen in sample_screens:
        quote = engine.price(screen, 3, 2, repos.as_of_date + dt.timedelta(days=30))
        for overrides in override_sets:
            overridden = engine.apply_overrides(quote, overrides, model_expected_footfall=1_000.0)
            assert overridden.floor <= overridden.target <= overridden.cap
            assert overridden.floor <= overridden.recommended <= overridden.cap
            assert overridden.human_overrides == overrides
