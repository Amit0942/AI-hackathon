"""Phase 6 (D3) exit-criteria tests for Steps 6.1/6.3/6.5, built per ADR-0003.

Property tests, not spot-checked values (this repo's testing convention,
CLAUDE.md): `floor <= target <= cap` always; monotonicity (more demand never
lowers the target); every price cites its cold-start ladder rung. Run
against the real repositories, no mocking — same convention as
`tests/test_repositories.py`.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from agentiq.data.occupancy import committed_occupancy_share, occupancy_events, occupancy_timeline
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.enums import ColdStartRung
from agentiq.domain.pricing import PriceQuote
from agentiq.pricing import PricingEngine
from agentiq.pricing.bands import compute_target
from agentiq.pricing.demand import recency_decay_weight


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def engine(repos: InMemoryRepositories) -> PricingEngine:
    return PricingEngine(repos)


# --------------------------------------------------------------------------- occupancy_timeline
def test_occupancy_never_exceeds_measured_capacity_ceiling(repos: InMemoryRepositories) -> None:
    # Step 1.4's independently proved ceiling — re-verified here on the
    # committed-occupancy slice this engine actually uses.
    timeline = occupancy_timeline(repos.bookings.committed())
    assert timeline["occupied_slots"].max() <= 6


def test_occupancy_timeline_sweep_matches_brute_force_overlap() -> None:
    # Two overlapping bookings, one 1-slot, one 2-slot, on the same
    # screen/block — brute-force expected occupancy per day, checked via the
    # as-of lookup on the *unfiltered* event log (`occupancy_events`), which
    # is what `committed_occupancy_share` requires (see its docstring: the
    # `occupancy_timeline` filtered log drops zero-crossings, so a lookup
    # against it would wrongly carry forward stale nonzero occupancy).
    lines = pd.DataFrame(
        {
            "screen_id": ["S1", "S1"],
            "time_block_id": [1, 1],
            "start_date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")],
            "end_date": [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-07")],
            "slots_booked_per_day": [1, 2],
        }
    )
    events = occupancy_events(lines)

    expected_by_date = {
        dt.date(2026, 1, 1): 1,
        dt.date(2026, 1, 2): 1,
        dt.date(2026, 1, 3): 3,
        dt.date(2026, 1, 4): 3,
        dt.date(2026, 1, 5): 3,
        dt.date(2026, 1, 6): 2,
        dt.date(2026, 1, 7): 2,
        dt.date(2026, 1, 8): 0,  # after both bookings end — genuinely zero
    }
    for day, expected_occupied in expected_by_date.items():
        share = committed_occupancy_share(events, "S1", 1, day, capacity=6)
        assert share == pytest.approx(expected_occupied / 6)


def test_occupancy_timeline_drops_the_zero_crossing_row() -> None:
    # Documents the filtered contract precisely, so a future edit that
    # changes `occupancy_timeline`'s filter is caught immediately.
    lines = pd.DataFrame(
        {
            "screen_id": ["S1"],
            "time_block_id": [1],
            "start_date": [pd.Timestamp("2026-01-01")],
            "end_date": [pd.Timestamp("2026-01-02")],
            "slots_booked_per_day": [3],
        }
    )
    timeline = occupancy_timeline(lines)
    assert (timeline["occupied_slots"] > 0).all()
    assert len(timeline) == 1  # only the start event; the end/zero event is filtered out


def test_committed_occupancy_share_absent_or_lapsed_date_is_zero() -> None:
    events = occupancy_events(
        pd.DataFrame(
            {
                "screen_id": ["S1"],
                "time_block_id": [1],
                "start_date": [pd.Timestamp("2026-01-01")],
                "end_date": [pd.Timestamp("2026-01-02")],
                "slots_booked_per_day": [3],
            }
        )
    )
    assert committed_occupancy_share(events, "S1", 1, dt.date(2026, 1, 1)) == 0.5
    # Regression: a date long after the booking lapses must read back to
    # zero, not the last-ever nonzero occupancy.
    assert committed_occupancy_share(events, "S1", 1, dt.date(2026, 6, 1)) == 0.0
    assert committed_occupancy_share(events, "S2", 1, dt.date(2026, 1, 1)) == 0.0


# --------------------------------------------------------------------------- recency decay
def test_recency_decay_halves_at_half_life() -> None:
    assert recency_decay_weight(21.0, half_life_days=21.0) == pytest.approx(0.5)
    assert recency_decay_weight(0.0, half_life_days=21.0) == 1.0
    assert recency_decay_weight(42.0, half_life_days=21.0) == pytest.approx(0.25)


# --------------------------------------------------------------------------- compute_target
def test_target_monotonic_in_demand_index() -> None:
    from agentiq.pricing.bands import PriceBandConfig

    config = PriceBandConfig(
        floor_percentile=0.10, margin_floor_pct=0.05,
        cap_gap_pct_vs_client_target=0.15, cap_gap_pct_vs_base_rate=0.35,
        max_uplift_pct=0.40, max_discount_pct=0.25,
    )
    low = compute_target(base_rate=100.0, demand_index=0.8, config=config)
    mid = compute_target(base_rate=100.0, demand_index=1.0, config=config)
    high = compute_target(base_rate=100.0, demand_index=1.5, config=config)
    assert low < mid < high


def test_target_uplift_and_discount_are_clamped() -> None:
    from agentiq.pricing.bands import PriceBandConfig

    config = PriceBandConfig(
        floor_percentile=0.10, margin_floor_pct=0.05,
        cap_gap_pct_vs_client_target=0.15, cap_gap_pct_vs_base_rate=0.35,
        max_uplift_pct=0.40, max_discount_pct=0.25,
    )
    # An extreme demand index must not translate into an unbounded price move.
    assert compute_target(100.0, demand_index=10.0, config=config) == pytest.approx(140.0)
    assert compute_target(100.0, demand_index=0.0, config=config) == pytest.approx(75.0)


# --------------------------------------------------------------------------- PricingEngine end-to-end
def _all_screens_sample(repos: InMemoryRepositories, n: int = 25):
    return repos.screens.all()[:n]


def test_price_band_invariant_floor_le_target_le_cap(
    repos: InMemoryRepositories, engine: PricingEngine
) -> None:
    on_date = repos.as_of_date
    for screen in _all_screens_sample(repos):
        quote = engine.price(screen, time_block_id=2, slots=2, on_date=on_date)
        assert quote.floor <= quote.target <= quote.cap
        assert quote.floor <= quote.recommended <= quote.cap


def test_every_quote_cites_a_cold_start_rung(
    repos: InMemoryRepositories, engine: PricingEngine
) -> None:
    on_date = repos.as_of_date
    for screen in _all_screens_sample(repos):
        quote = engine.price(screen, time_block_id=3, slots=1, on_date=on_date)
        assert isinstance(quote.cold_start_rung, ColdStartRung)
        assert quote.explanation.headline  # non-empty, human-readable
        assert quote.explanation.confidence_reason


def test_screen_with_rich_history_uses_own_history_rung(
    repos: InMemoryRepositories, engine: PricingEngine
) -> None:
    settled = repos.bookings.settled()
    counts = settled["screen_id"].value_counts()
    rich_id = counts[counts >= 20].index[0]
    screen = repos.screens.get(rich_id)
    assert screen is not None

    quote = engine.price(screen, time_block_id=5, slots=3, on_date=repos.as_of_date)
    assert quote.cold_start_rung == ColdStartRung.SCREEN_OWN_HISTORY


def test_screen_with_zero_history_falls_back_down_the_ladder(
    repos: InMemoryRepositories, engine: PricingEngine
) -> None:
    settled = repos.bookings.settled()
    committed = repos.bookings.committed()
    booked_ids = set(settled["screen_id"]) | set(committed["screen_id"])
    all_ids = {s.screen_id for s in repos.screens.all()}
    cold_id = next(iter(all_ids - booked_ids))
    screen = repos.screens.get(cold_id)
    assert screen is not None

    quote = engine.price(screen, time_block_id=3, slots=1, on_date=repos.as_of_date)
    assert quote.cold_start_rung != ColdStartRung.SCREEN_OWN_HISTORY
    assert quote.explanation.is_fallback


def test_returned_object_is_a_valid_price_quote(
    repos: InMemoryRepositories, engine: PricingEngine
) -> None:
    screen = repos.screens.all()[0]
    quote = engine.price(screen, time_block_id=1, slots=1, on_date=repos.as_of_date)
    assert isinstance(quote, PriceQuote)
    assert quote.total_for_slots == pytest.approx(quote.recommended * quote.slots)
