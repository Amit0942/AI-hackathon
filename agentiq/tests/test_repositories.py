"""Step 2.3 exit criteria: repository protocols are satisfied by the in-memory
implementation, and every screen loads into a valid `Screen` domain object
against the real raw CSVs — no mocking, per this repo's testing conventions
(numeric/structural invariants, not a fake data double)."""

from __future__ import annotations

import datetime as dt

import pytest

from agentiq.data.repositories import (
    BookingRepository,
    ClientRepository,
    ContextRepository,
    GeographyRepository,
    InMemoryRepositories,
    LeadRepository,
    ScreenRepository,
    compute_as_of_date,
)
from agentiq.domain import ScreenType


@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


def test_satisfies_protocols(repos: InMemoryRepositories) -> None:
    assert isinstance(repos.screens, ScreenRepository)
    assert isinstance(repos.bookings, BookingRepository)
    assert isinstance(repos.leads, LeadRepository)
    assert isinstance(repos.clients, ClientRepository)
    assert isinstance(repos.context, ContextRepository)
    assert isinstance(repos.geography, GeographyRepository)


def test_as_of_date_matches_step_1_4(repos: InMemoryRepositories) -> None:
    # Step 1.4 §1.1: triangulated from four independent signals that agree exactly.
    assert repos.as_of_date == dt.date(2026, 8, 19)


def test_all_screens_load_as_valid_domain_objects(repos: InMemoryRepositories) -> None:
    screens = repos.screens.all()
    # Step 1.4 headline number.
    assert len(screens) == 11_163
    assert len({s.screen_id for s in screens}) == 11_163  # primary key uniqueness


def test_static_mobile_split_matches_step_1_4(repos: InMemoryRepositories) -> None:
    screens = repos.screens.all()
    static = [s for s in screens if s.is_static]
    mobile = [s for s in screens if s.is_mobile]
    assert len(static) == 8_548
    assert len(mobile) == 2_615


def test_by_type_counts_match_step_1_4(repos: InMemoryRepositories) -> None:
    counts = {t: len(repos.screens.by_type(t)) for t in ScreenType}
    assert counts[ScreenType.METRO_STATION] == 6_391
    assert counts[ScreenType.BUS_STOP] == 2_157
    assert counts[ScreenType.METRO_RAIL_COACH] == 1_400
    assert counts[ScreenType.BUS] == 1_215


def test_by_city_partitions_all_screens(repos: InMemoryRepositories) -> None:
    screens = repos.screens.all()
    by_city_total = sum(len(repos.screens.by_city(c)) for c in ("ACS", "DAT", "LH"))
    assert by_city_total == len(screens)


def test_bookings_settled_committed_split_matches_step_1_5(repos: InMemoryRepositories) -> None:
    # Step 1.5 §1 headline numbers.
    assert len(repos.bookings.settled()) == 111_727
    assert len(repos.bookings.committed()) == 79_382


def test_settled_and_committed_are_disjoint_status_sets(repos: InMemoryRepositories) -> None:
    settled_status = set(repos.bookings.settled()["booking_status"].unique())
    committed_status = set(repos.bookings.committed()["booking_status"].unique())
    assert settled_status == {"completed"}
    assert committed_status == {"active", "upcoming"}


def test_has_history_is_true_for_a_booked_screen(repos: InMemoryRepositories) -> None:
    some_screen_id = repos.bookings.settled()["screen_id"].iloc[0]
    assert repos.bookings.has_history(some_screen_id) is True


def test_has_history_is_false_for_an_unknown_screen_id(repos: InMemoryRepositories) -> None:
    assert repos.bookings.has_history("NOT-A-REAL-SCREEN-ID") is False


def test_leads_with_price_gap_is_a_strict_subset(repos: InMemoryRepositories) -> None:
    all_leads = repos.leads.all()
    with_gap = repos.leads.with_price_gap()
    assert len(with_gap) < len(all_leads)
    assert with_gap["price_gap_pct"].notna().all()


def test_geography_join_path_screen_to_city(repos: InMemoryRepositories) -> None:
    screen = next(s for s in repos.screens.all() if s.is_static)
    zone = repos.geography.zone_for_location(screen.location_id)
    assert zone is not None
    city = repos.geography.city(screen.city_id)
    assert city is not None
    assert city["city_id"] == screen.city_id


def test_compute_as_of_date_is_one_day_after_last_completed_end(
    repos: InMemoryRepositories,
) -> None:
    settled = repos.bookings.settled()
    last_completed_end = settled["end_date"].max().date()
    assert compute_as_of_date(repos.lake["bookings"]) == last_completed_end + dt.timedelta(days=1)
