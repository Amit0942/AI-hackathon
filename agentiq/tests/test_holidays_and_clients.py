"""Tests for the D3 holiday calendar/footfall integration and the new
client-segmentation module (both from the "optimize D3 using client data
and a real holiday calendar" pass).
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentiq.clients import ClientSegmentationEngine
from agentiq.data.repositories import InMemoryRepositories
from agentiq.pricing import PricingEngine
from agentiq.pricing.holidays import is_us_federal_holiday, us_federal_holidays


# --------------------------------------------------------------------------- holidays.py (pure)
@pytest.mark.parametrize(
    "day",
    [
        dt.date(2026, 1, 1),  # New Year's Day
        dt.date(2026, 1, 19),  # MLK Day (3rd Monday of Jan)
        dt.date(2026, 7, 4),  # Independence Day
        dt.date(2026, 11, 26),  # Thanksgiving (4th Thursday of Nov)
        dt.date(2026, 12, 25),  # Christmas
        dt.date(2027, 5, 31),  # Memorial Day (last Monday of May)
    ],
)
def test_known_holidays_are_recognised(day: dt.date) -> None:
    assert is_us_federal_holiday(day) is True


def test_an_ordinary_day_is_not_a_holiday() -> None:
    assert is_us_federal_holiday(dt.date(2026, 3, 17)) is False


def test_us_federal_holidays_returns_exactly_eleven_dates_per_year() -> None:
    assert len(us_federal_holidays(2026)) == 11
    assert len(set(us_federal_holidays(2026))) == 11  # no accidental duplicates


def test_thanksgiving_is_always_a_thursday() -> None:
    for year in (2025, 2026, 2027, 2028):
        thanksgiving = next(h for h in us_federal_holidays(year) if h.month == 11 and h.day >= 22)
        assert thanksgiving.weekday() == 3  # Thursday


# ------------------------------------------------------------------------- footfall.py integration
@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def engine(repos: InMemoryRepositories) -> PricingEngine:
    return PricingEngine(repos)


def test_forecast_window_containing_a_holiday_is_lower_than_one_without(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = next(s for s in repos.screens.all() if s.is_static)
    # Same weekday/weekend composition (Mon-Sun both windows), one contains
    # Thanksgiving (2026-11-26), the other doesn't — isolates the holiday effect.
    with_holiday = engine.forecast_footfall(
        screen, 3, dt.date(2026, 11, 23), dt.date(2026, 11, 29)
    )
    without_holiday = engine.forecast_footfall(
        screen, 3, dt.date(2026, 11, 2), dt.date(2026, 11, 8)
    )
    assert with_holiday.expected_total_footfall < without_holiday.expected_total_footfall


def test_forecast_explanation_cites_holiday_contribution_when_present(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = next(s for s in repos.screens.all() if s.is_static)
    forecast = engine.forecast_footfall(screen, 3, dt.date(2026, 12, 25), dt.date(2026, 12, 25))
    signals = {c.signal for c in forecast.explanation.contributions}
    assert "holiday_ridership_effect" in signals


def test_forecast_explanation_omits_holiday_contribution_when_absent(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = next(s for s in repos.screens.all() if s.is_static)
    forecast = engine.forecast_footfall(screen, 3, dt.date(2026, 3, 17), dt.date(2026, 3, 17))
    signals = {c.signal for c in forecast.explanation.contributions}
    assert "holiday_ridership_effect" not in signals


def test_price_for_client_resolves_tier_and_industry_automatically(
    engine: PricingEngine, repos: InMemoryRepositories
) -> None:
    screen = repos.screens.all()[0]
    client_id = repos.lake["client_facts"]["client_id"].iloc[0]
    on_date = repos.as_of_date + dt.timedelta(days=30)
    quote = engine.price_for_client(client_id, screen, 3, 2, on_date)
    assert quote.floor <= quote.target <= quote.cap
    assert quote.floor <= quote.recommended <= quote.cap


def test_price_for_client_rejects_unknown_client() -> None:
    repos = InMemoryRepositories()
    engine = PricingEngine(repos)
    screen = repos.screens.all()[0]
    with pytest.raises(ValueError):
        engine.price_for_client(
            "NOT-A-REAL-CLIENT", screen, 3, 2, repos.as_of_date + dt.timedelta(days=30)
        )


# --------------------------------------------------------------------------- client segmentation
@pytest.fixture(scope="module")
def client_engine(repos: InMemoryRepositories) -> ClientSegmentationEngine:
    return ClientSegmentationEngine(repos)


def test_segment_all_covers_every_client(
    client_engine: ClientSegmentationEngine, repos: InMemoryRepositories
) -> None:
    segments = client_engine.segment_all()
    assert len(segments) == len(repos.lake["client_facts"])
    assert {s.client_id for s in segments} == set(repos.lake["client_facts"]["client_id"])


def test_objective_segment_share_reflects_dominance(
    client_engine: ClientSegmentationEngine, repos: InMemoryRepositories
) -> None:
    settled = repos.bookings.settled()
    for client_id, group in list(settled.groupby("client_id"))[:20]:
        segment = client_engine.segment(client_id)
        counts = group["campaign_objective"].astype(str).value_counts()
        assert segment.objective_segment is not None
        assert segment.objective_segment.value == counts.idxmax()
        assert segment.objective_segment_share == pytest.approx(counts.max() / counts.sum())
        assert segment.sample_size == len(group)


def test_client_with_no_settled_history_is_unclassified_not_guessed(
    client_engine: ClientSegmentationEngine, repos: InMemoryRepositories
) -> None:
    settled_client_ids = set(repos.bookings.settled()["client_id"])
    all_client_ids = set(repos.lake["client_facts"]["client_id"])
    never_booked = all_client_ids - settled_client_ids
    if not never_booked:
        pytest.skip("every client has at least one settled booking on this dataset")
    segment = client_engine.segment(next(iter(never_booked)))
    assert segment.objective_segment is None
    assert segment.objective_segment_share == 0.0
    assert segment.sample_size == 0
    assert "no_settled_booking_history" in segment.explanation.fallbacks_used


def test_budget_posture_is_relative_to_the_measured_median(
    client_engine: ClientSegmentationEngine, repos: InMemoryRepositories
) -> None:
    facts = repos.lake["client_facts"]
    median = float(facts["budget_variance_pct"].median())
    below_median_client = facts.loc[facts["budget_variance_pct"] <= median].iloc[0]
    above_median_client = facts.loc[facts["budget_variance_pct"] > median].iloc[0]
    assert client_engine.segment(below_median_client["client_id"]).budget_posture == "disciplined"
    assert client_engine.segment(above_median_client["client_id"]).budget_posture == "flexible"


def test_unknown_client_id_raises(client_engine: ClientSegmentationEngine) -> None:
    with pytest.raises(ValueError):
        client_engine.segment("NOT-A-REAL-CLIENT")
