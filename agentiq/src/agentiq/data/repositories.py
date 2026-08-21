"""Repository protocols (Step 2.3).

Engines depend on these `Protocol`s, never on `DataLake`, a file path, or a
raw pandas frame passed in directly (CLAUDE.md: "Repositories, not file
paths"). `InMemoryRepositories` is the hackathon implementation — a thin
adapter over `DataLake` — but any engine written against the protocols below
would work unchanged against a real database-backed implementation.

Each method returns `agentiq.domain` value objects, not frames: the
frame-to-domain conversion happens once, here, instead of being repeated
(and re-diverging) inside every engine.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

from agentiq.data.loaders import DataLake
from agentiq.domain import AudienceProfile, MountPosition, Screen, ScreenSize, ScreenType


# --------------------------------------------------------------------------- protocols
@runtime_checkable
class ScreenRepository(Protocol):
    """Access to the inventory spine (`screens.csv`)."""

    def get(self, screen_id: str) -> Screen | None: ...

    def all(self) -> tuple[Screen, ...]: ...

    def by_city(self, city_id: str) -> tuple[Screen, ...]: ...

    def by_type(self, screen_type: ScreenType) -> tuple[Screen, ...]: ...


@runtime_checkable
class BookingRepository(Protocol):
    """Access to realised/committed bookings (`bookings.csv`)."""

    def settled(self) -> pd.DataFrame:
        """Only `booking_status == 'completed'` rows — the sole safe training set."""
        ...

    def committed(self) -> pd.DataFrame:
        """`active`/`upcoming` rows — occupancy, never used as a price-training input."""
        ...

    def for_screen(self, screen_id: str) -> pd.DataFrame: ...

    def has_history(self, screen_id: str) -> bool: ...


@runtime_checkable
class LeadRepository(Protocol):
    """Access to the negative demand signal (`lost_leads.csv`)."""

    def all(self) -> pd.DataFrame: ...

    def with_price_gap(self) -> pd.DataFrame:
        """Rows where `price_gap_pct` is populated — the price-cap calibration subset."""
        ...

    def for_city(self, city_id: str) -> pd.DataFrame: ...

    def as_of(self, as_of_date: date) -> pd.DataFrame:
        """Leads still open (not yet lost) as of *as_of_date* — pipeline pressure input."""
        ...


@runtime_checkable
class ClientRepository(Protocol):
    def get(self, client_id: str) -> dict | None: ...

    def all(self) -> pd.DataFrame: ...


@runtime_checkable
class ContextRepository(Protocol):
    """POIs and events (`points_of_interest.csv`, `events.csv`)."""

    def pois_near(self, location_id: str, radius_km: float) -> pd.DataFrame: ...

    def events_active(self, city_id: str, start: date, end: date) -> pd.DataFrame: ...


@runtime_checkable
class GeographyRepository(Protocol):
    """Cities, zones, locations — the static-geography path."""

    def city(self, city_id: str) -> dict | None: ...

    def zone_for_location(self, location_id: str) -> dict | None: ...

    def location(self, location_id: str) -> dict | None: ...


@runtime_checkable
class AudienceProfileRepository(Protocol):
    """Precomputed D1 artifact — the offline/online split (design principle 5)."""

    def get(self, screen_id: str) -> AudienceProfile | None: ...

    def all(self) -> tuple[AudienceProfile, ...]: ...


# --------------------------------------------------------------------------- as-of date
def compute_as_of_date(bookings: pd.DataFrame) -> date:
    """Re-derive the as-of date the way Step 1.4 §1.1 proved it (triangulated, not assumed).

    The last `completed` booking ends the day *before* the as-of date (there is
    exactly one day between the last `completed` end and the first `upcoming`
    start — Step 1.4 §1.1), so the as-of date is that end date plus one day,
    not the end date itself. Every train/test split and availability check
    must use this date, never the wall clock — otherwise a model trains on
    its own future.
    """
    from datetime import timedelta

    completed_end = bookings.loc[bookings["booking_status"] == "completed", "end_date"].max()
    completed_end = completed_end.date() if hasattr(completed_end, "date") else completed_end
    return completed_end + timedelta(days=1)


# --------------------------------------------------------------------------- conversion
def _row_to_screen(row: pd.Series) -> Screen:
    position = row.get("position")
    return Screen(
        screen_id=row["screen_id"],
        city_id=row["city_id"],
        screen_type=ScreenType(row["screen_type"]),
        position=MountPosition(position) if pd.notna(position) else None,
        screen_size=ScreenSize(row["screen_size"]),
        location_id=row["location_id"] if pd.notna(row.get("location_id")) else None,
        vehicle_id=row["vehicle_id"] if pd.notna(row.get("vehicle_id")) else None,
    )


# --------------------------------------------------------------------------- in-memory impl
class InMemoryScreenRepository:
    """`ScreenRepository` backed by `DataLake["screens"]`, indexed once at construction."""

    def __init__(self, lake: DataLake) -> None:
        frame = lake["screens"]
        self._by_id: dict[str, Screen] = {
            row["screen_id"]: _row_to_screen(row) for _, row in frame.iterrows()
        }

    def get(self, screen_id: str) -> Screen | None:
        return self._by_id.get(screen_id)

    def all(self) -> tuple[Screen, ...]:
        return tuple(self._by_id.values())

    def by_city(self, city_id: str) -> tuple[Screen, ...]:
        return tuple(s for s in self._by_id.values() if s.city_id == city_id)

    def by_type(self, screen_type: ScreenType) -> tuple[Screen, ...]:
        return tuple(s for s in self._by_id.values() if s.screen_type == screen_type)


class InMemoryBookingRepository:
    """`BookingRepository` backed by `DataLake["bookings"]`."""

    def __init__(self, lake: DataLake) -> None:
        self._frame = lake["bookings"]
        self._as_of = compute_as_of_date(self._frame)

    @property
    def as_of_date(self) -> date:
        return self._as_of

    def settled(self) -> pd.DataFrame:
        return self._frame.loc[self._frame["booking_status"] == "completed"]

    def committed(self) -> pd.DataFrame:
        return self._frame.loc[self._frame["booking_status"].isin(("active", "upcoming"))]

    def for_screen(self, screen_id: str) -> pd.DataFrame:
        return self._frame.loc[self._frame["screen_id"] == screen_id]

    def has_history(self, screen_id: str) -> bool:
        return bool((self._frame["screen_id"] == screen_id).any())


class InMemoryLeadRepository:
    """`LeadRepository` backed by `DataLake["lost_leads"]`."""

    def __init__(self, lake: DataLake) -> None:
        self._frame = lake["lost_leads"]

    def all(self) -> pd.DataFrame:
        return self._frame

    def with_price_gap(self) -> pd.DataFrame:
        return self._frame.loc[self._frame["price_gap_pct"].notna()]

    def for_city(self, city_id: str) -> pd.DataFrame:
        return self._frame.loc[self._frame["city_id"] == city_id]

    def as_of(self, as_of_date: date) -> pd.DataFrame:
        lead_dates = pd.to_datetime(self._frame["lead_date"]).dt.date
        lost_dates = pd.to_datetime(self._frame["lost_date"]).dt.date
        return self._frame.loc[(lead_dates <= as_of_date) & (lost_dates > as_of_date)]


class InMemoryClientRepository:
    """`ClientRepository` backed by `DataLake["client_facts"]`."""

    def __init__(self, lake: DataLake) -> None:
        self._frame = lake["client_facts"]
        self._by_id = {row["client_id"]: row.to_dict() for _, row in self._frame.iterrows()}

    def get(self, client_id: str) -> dict | None:
        return self._by_id.get(client_id)

    def all(self) -> pd.DataFrame:
        return self._frame


class InMemoryContextRepository:
    """`ContextRepository` backed by `DataLake["points_of_interest"]` and `DataLake["events"]`."""

    def __init__(self, lake: DataLake) -> None:
        self._pois = lake["points_of_interest"]
        self._events = lake["events"]

    def pois_near(self, location_id: str, radius_km: float) -> pd.DataFrame:
        near = self._pois.loc[self._pois["anchor_location_id"] == location_id]
        return near.loc[near["distance_to_location_km"] <= radius_km]

    def events_active(self, city_id: str, start: date, end: date) -> pd.DataFrame:
        events = self._events.loc[self._events["city_id"] == city_id]
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        overlaps = (events["start_date"] <= end_ts) & (events["end_date"] >= start_ts)
        return events.loc[overlaps]


class InMemoryGeographyRepository:
    """`GeographyRepository` backed by `cities`, `zone_demographics`, `locations`."""

    def __init__(self, lake: DataLake) -> None:
        self._cities = {row["city_id"]: row.to_dict() for _, row in lake["cities"].iterrows()}
        self._zones = {
            row["zone_id"]: row.to_dict() for _, row in lake["zone_demographics"].iterrows()
        }
        self._locations = {
            row["location_id"]: row.to_dict() for _, row in lake["locations"].iterrows()
        }

    def city(self, city_id: str) -> dict | None:
        return self._cities.get(city_id)

    def location(self, location_id: str) -> dict | None:
        return self._locations.get(location_id)

    def zone_for_location(self, location_id: str) -> dict | None:
        location = self._locations.get(location_id)
        if location is None:
            return None
        return self._zones.get(location["zone_id"])


class InMemoryRepositories:
    """Bundle of every in-memory repository, built once from a shared `DataLake`.

    This is the single object an engine's constructor takes in the
    hackathon wiring (`api/main.py`, tests) — swapping to a DB-backed
    implementation means writing one new class with this same shape, not
    touching engine code.
    """

    def __init__(self, lake: DataLake | None = None) -> None:
        self.lake = lake or DataLake()
        self.screens: ScreenRepository = InMemoryScreenRepository(self.lake)
        self.bookings: InMemoryBookingRepository = InMemoryBookingRepository(self.lake)
        self.leads: LeadRepository = InMemoryLeadRepository(self.lake)
        self.clients: ClientRepository = InMemoryClientRepository(self.lake)
        self.context: ContextRepository = InMemoryContextRepository(self.lake)
        self.geography: GeographyRepository = InMemoryGeographyRepository(self.lake)

    @property
    def as_of_date(self) -> date:
        return self.bookings.as_of_date
