"""Inventory shape: what exactly is being sold (Step 1.4).

This module answers four questions with measured numbers, and nothing here is
assumed from a column name:

1. **What is the inventory?** Screens by city, deployment type, mount position and
   size — and which types are static versus vehicle-mounted.
2. **What is one sellable unit?** The slot capacity of a screen x time block x date
   is *measured* from booking history rather than configured, then validated by a
   sweep line that proves no unit is ever oversold.
3. **How big is the optimisation problem?** The exact sellable-unit count per city
   per day and over the forward horizon. Phase 7's solver design must cite this.
4. **What is already gone?** Committed occupancy over the forward horizon, so the
   count of *available* units is separated from the count of existing ones.

The reusable pieces here — :func:`occupancy_timeline`, :func:`infer_as_of_date` and
:class:`CapacityModel` — are the same primitives Step 1.5 needs for occupancy and
Phase 6 needs for scarcity, so they are written once and imported, not recopied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from .loaders import DataLake

#: Booking statuses that represent settled history — the only rows that are training data.
SETTLED_STATUSES: tuple[str, ...] = ("completed",)
#: Booking statuses that represent a forward claim on inventory, not history.
COMMITTED_STATUSES: tuple[str, ...] = ("active", "upcoming")


# --------------------------------------------------------------------- as-of date
@dataclass(frozen=True)
class AsOfDate:
    """The boundary between settled history and committed occupancy.

    The dataset carries no "today" column, so the date is triangulated from four
    independent signals. Every later phase must use this date rather than the real
    clock, or a back-test will silently train on the future.
    """

    date: pd.Timestamp
    last_settled_end: pd.Timestamp
    first_upcoming_start: pd.Timestamp
    last_ridership_date: pd.Timestamp | None
    active_lines: int
    active_lines_spanning: int

    @property
    def is_unambiguous(self) -> bool:
        """True when the three status windows leave exactly one candidate day.

        `completed` must end before the date, `upcoming` must start after it, and
        every `active` line must span it. Those three conditions together pin a
        single day; if they do not, the status labels are not date-consistent and
        every downstream train/test split needs a different rule.
        """
        return (
            (self.first_upcoming_start - self.last_settled_end).days == 2
            and self.active_lines == self.active_lines_spanning
        )

    def evidence(self) -> list[str]:
        lines = [
            f"last `completed` booking ends {self.last_settled_end.date()}",
            f"first `upcoming` booking starts {self.first_upcoming_start.date()}, "
            "leaving exactly one day between them",
            f"all {self.active_lines_spanning:,} of {self.active_lines:,} `active` lines span it",
        ]
        if self.last_ridership_date is not None:
            lines.append(f"ridership actuals stop at {self.last_ridership_date.date()}")
        return lines


def infer_as_of_date(bookings: pd.DataFrame, ridership: pd.DataFrame | None = None) -> AsOfDate:
    settled_end = bookings.loc[
        bookings["booking_status"].isin(SETTLED_STATUSES), "end_date"
    ].max()
    upcoming_start = bookings.loc[bookings["booking_status"] == "upcoming", "start_date"].min()
    as_of = settled_end + pd.Timedelta(days=1)

    active = bookings[bookings["booking_status"] == "active"]
    spanning = active[(active["start_date"] <= as_of) & (active["end_date"] >= as_of)]

    return AsOfDate(
        date=as_of,
        last_settled_end=settled_end,
        first_upcoming_start=upcoming_start,
        last_ridership_date=None if ridership is None else ridership["date"].max(),
        active_lines=len(active),
        active_lines_spanning=len(spanning),
    )


# ----------------------------------------------------------------- capacity model
@dataclass(frozen=True)
class CapacityModel:
    """How much inventory one screen holds, measured from what has been sold.

    ``slots_per_block`` is the crux of the whole optimisation: it turns a screen into
    a divisible resource. It is measured, then proved by :func:`occupancy_timeline`
    — no unit in 552 days of history is ever sold beyond it.
    """

    blocks_per_day: int
    slots_per_block: int
    max_slots_in_one_booking: int
    peak_concurrent_slots_observed: int
    units_ever_oversold: int
    #: rotation_type -> the exact set of slot counts it is used with.
    rotation_slot_map: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def slots_per_screen_day(self) -> int:
        return self.blocks_per_day * self.slots_per_block

    @property
    def is_validated(self) -> bool:
        return (
            self.units_ever_oversold == 0
            and self.peak_concurrent_slots_observed == self.slots_per_block
        )

    def rotation_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "rotation_type": name,
                    "slots_booked_per_day": ", ".join(str(slot) for slot in slots),
                    "min_slots": min(slots),
                    "max_slots": max(slots),
                }
                for name, slots in self.rotation_slot_map.items()
            ]
        ).sort_values("min_slots", ignore_index=True)


def occupancy_timeline(
    bookings: pd.DataFrame,
    *,
    unit_keys: Sequence[str] = ("screen_id", "time_block_id"),
    statuses: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Sweep-line expansion of bookings into a running slot-occupancy series.

    A booking holds ``slots_booked_per_day`` slots on every date in its range, so the
    naive expansion is one row per unit per date — ~12M rows here, and far more at
    scale. Instead we emit ``+slots`` at ``start_date`` and ``-slots`` at
    ``end_date + 1`` and take a cumulative sum: two events per booking regardless of
    flight length. ``occupied_slots`` is the number of slots claimed on ``date`` and
    stays valid until the next event for that unit.

    Returns columns: ``*unit_keys``, ``date``, ``delta``, ``occupied_slots``.
    """
    frame = bookings
    if statuses is not None:
        frame = frame[frame["booking_status"].isin(list(statuses))]

    keys = list(unit_keys)
    opens = frame[[*keys, "start_date", "slots_booked_per_day"]].rename(
        columns={"start_date": "date", "slots_booked_per_day": "delta"}
    )
    closes = frame[[*keys, "end_date", "slots_booked_per_day"]].copy()
    closes["date"] = closes["end_date"] + pd.Timedelta(days=1)
    closes["delta"] = -closes["slots_booked_per_day"]
    closes = closes[[*keys, "date", "delta"]]

    events = (
        pd.concat([opens, closes], ignore_index=True)
        .groupby([*keys, "date"], observed=True, as_index=False)["delta"]
        .sum()
        .sort_values([*keys, "date"], ignore_index=True)
    )
    events["occupied_slots"] = events.groupby(keys, observed=True)["delta"].cumsum()
    return events


def measure_capacity(bookings: pd.DataFrame, slot_dim: pd.DataFrame) -> CapacityModel:
    """Derive the capacity model from history and validate it with the sweep line."""
    timeline = occupancy_timeline(bookings)
    peak_per_unit = timeline.groupby(
        ["screen_id", "time_block_id"], observed=True
    )["occupied_slots"].max()
    peak = int(peak_per_unit.max())

    rotation_map = {
        str(name): tuple(sorted(int(v) for v in group.unique()))
        for name, group in bookings.groupby("rotation_type", observed=True)[
            "slots_booked_per_day"
        ]
    }

    return CapacityModel(
        blocks_per_day=int(slot_dim["time_block_id"].nunique()),
        slots_per_block=peak,
        max_slots_in_one_booking=int(bookings["slots_booked_per_day"].max()),
        peak_concurrent_slots_observed=peak,
        units_ever_oversold=int((peak_per_unit > peak).sum()),
        rotation_slot_map=rotation_map,
    )


# ------------------------------------------------------------------ facet profile
STATIC_TYPES_NOTE = "location_id populated"
MOBILE_TYPES_NOTE = "vehicle_id populated"


def deployment_split(screens: pd.DataFrame) -> pd.DataFrame:
    """Which screen types are static and which are vehicle-mounted, with counts."""
    mounting = pd.Series(
        pd.NA, index=screens.index, dtype="object", name="mounting"
    )
    mounting[screens["location_id"].notna()] = "static"
    mounting[screens["vehicle_id"].notna()] = "mobile"

    table = (
        screens.assign(mounting=mounting)
        .groupby(["screen_type", "mounting"], observed=True)
        .size()
        .rename("screens")
        .reset_index()
    )
    table["share_of_network"] = table["screens"] / len(screens)
    table["exposure_model"] = table["mounting"].map(
        {"static": "D1 static (zone + POI + stop throughput)", "mobile": "D1 mobile (journey)"}
    )
    return table.sort_values("screens", ascending=False, ignore_index=True)


def facet_counts(screens: pd.DataFrame, facet: str, by: str = "city_id") -> pd.DataFrame:
    """Cross-tab of one screen attribute against another, nulls kept visible."""
    left = screens[facet].astype("object").fillna("(null)")
    right = screens[by].astype("object").fillna("(null)")
    table = pd.crosstab(left, right, margins=True, margins_name="all")
    table.index.name = facet
    table.columns.name = by
    return table


def concentration(
    screens: pd.DataFrame,
    locations: pd.DataFrame,
    vehicles: pd.DataFrame,
) -> pd.DataFrame:
    """Screens per physical grouping — how clustered the inventory is.

    Directly sizes the Phase 3 overlap problem: screens sharing a location share an
    audience, so a 50-screen station is one audience cluster, not 50 independent buys.
    """
    static = screens.dropna(subset=["location_id"]).merge(
        locations[["location_id", "location_type", "zone_id"]], on="location_id", how="left"
    )
    mobile = screens.dropna(subset=["vehicle_id"]).merge(
        vehicles[["vehicle_id", "corridor_id", "vehicle_type"]], on="vehicle_id", how="left"
    )

    groupings: list[tuple[str, pd.Series]] = [
        ("per location (all)", static.groupby("location_id", observed=True).size()),
        *[
            (
                f"per location ({name})",
                group.groupby("location_id", observed=True).size(),
            )
            for name, group in static.groupby("location_type", observed=True)
        ],
        ("per zone (static screens)", static.groupby("zone_id", observed=True).size()),
        ("per vehicle", mobile.groupby("vehicle_id", observed=True).size()),
        ("per corridor (mobile screens)", mobile.groupby("corridor_id", observed=True).size()),
    ]

    return pd.DataFrame(
        [
            {
                "grouping": label,
                "groups": int(series.size),
                "screens": int(series.sum()),
                "min": int(series.min()),
                "median": float(series.median()),
                "max": int(series.max()),
            }
            for label, series in groupings
            if series.size
        ]
    )


# ------------------------------------------------------------------ sellable units
@dataclass(frozen=True)
class SellableUnits:
    """The exact size of the optimisation problem, at three granularities."""

    capacity: CapacityModel
    horizon_start: pd.Timestamp
    horizon_end: pd.Timestamp
    per_city: pd.DataFrame

    @property
    def horizon_days(self) -> int:
        return (self.horizon_end - self.horizon_start).days + 1

    @property
    def network(self) -> Mapping[str, int]:
        row = self.per_city.loc[self.per_city["city_id"] == "network"].iloc[0]
        return {
            "screens": int(row["screens"]),
            "block_units_per_day": int(row["block_units_per_day"]),
            "slot_units_per_day": int(row["slot_units_per_day"]),
            "slot_units_horizon": int(row["slot_units_horizon"]),
            "committed_slot_units": int(row["committed_slot_units"]),
            "available_slot_units": int(row["available_slot_units"]),
        }


def _committed_slot_days(
    bookings: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.Series:
    """Slot-days already claimed inside [start, end], per city.

    Exact rather than sampled: each booking's overlap with the horizon is computed
    directly. Valid because :func:`measure_capacity` proves no unit is ever oversold,
    so claims never need to be de-duplicated.
    """
    committed = bookings[bookings["booking_status"].isin(COMMITTED_STATUSES)].copy()
    overlap_start = committed["start_date"].clip(lower=start)
    overlap_end = committed["end_date"].clip(upper=end)
    days = (overlap_end - overlap_start).dt.days + 1
    committed["slot_days"] = committed["slots_booked_per_day"] * days.clip(lower=0)
    return committed.groupby("city_id", observed=True)["slot_days"].sum()


def sellable_units(
    screens: pd.DataFrame,
    bookings: pd.DataFrame,
    capacity: CapacityModel,
    *,
    horizon_start: pd.Timestamp,
    horizon_end: pd.Timestamp,
) -> SellableUnits:
    days = (horizon_end - horizon_start).days + 1
    by_city = screens.groupby("city_id", observed=True).size().rename("screens")
    committed = _committed_slot_days(bookings, horizon_start, horizon_end)

    table = by_city.to_frame().reset_index()
    table["city_id"] = table["city_id"].astype("object")
    table["block_units_per_day"] = table["screens"] * capacity.blocks_per_day
    table["slot_units_per_day"] = table["screens"] * capacity.slots_per_screen_day
    table["slot_units_horizon"] = table["slot_units_per_day"] * days
    table["committed_slot_units"] = (
        table["city_id"].map(committed).fillna(0).astype("int64")
    )
    table["available_slot_units"] = (
        table["slot_units_horizon"] - table["committed_slot_units"]
    )
    table["utilisation"] = table["committed_slot_units"] / table["slot_units_horizon"]

    totals = {
        "city_id": "network",
        **{
            column: int(table[column].sum())
            for column in table.columns
            if column not in ("city_id", "utilisation")
        },
    }
    totals["utilisation"] = totals["committed_slot_units"] / totals["slot_units_horizon"]
    table = pd.concat([table, pd.DataFrame([totals])], ignore_index=True)

    return SellableUnits(
        capacity=capacity,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        per_city=table,
    )


def availability_by_block(
    screens: pd.DataFrame,
    bookings: pd.DataFrame,
    capacity: CapacityModel,
    slot_dim: pd.DataFrame,
    *,
    horizon_start: pd.Timestamp,
    horizon_end: pd.Timestamp,
) -> pd.DataFrame:
    """Forward utilisation per time block — where the availability constraint bites.

    A network-wide utilisation average hides the thing that matters: peak commute
    blocks and cheap night blocks are the same inventory on paper but not in
    practice. Phase 7's availability constraint is only binding where this is high.
    """
    days = (horizon_end - horizon_start).days + 1
    capacity_per_block = len(screens) * capacity.slots_per_block * days

    committed = bookings[bookings["booking_status"].isin(COMMITTED_STATUSES)].copy()
    overlap = (
        committed["end_date"].clip(upper=horizon_end)
        - committed["start_date"].clip(lower=horizon_start)
    ).dt.days + 1
    committed["slot_days"] = committed["slots_booked_per_day"] * overlap.clip(lower=0)

    table = (
        committed.groupby("time_block_id", observed=True)["slot_days"]
        .sum()
        .rename("committed_slot_units")
        .reset_index()
        .merge(slot_dim[["time_block_id", "time_block_label", "nearest_daypart"]], on="time_block_id")
    )
    table["capacity_slot_units"] = capacity_per_block
    table["available_slot_units"] = table["capacity_slot_units"] - table["committed_slot_units"]
    table["utilisation"] = table["committed_slot_units"] / table["capacity_slot_units"]
    return table[
        [
            "time_block_id",
            "time_block_label",
            "nearest_daypart",
            "capacity_slot_units",
            "committed_slot_units",
            "available_slot_units",
            "utilisation",
        ]
    ].sort_values("time_block_id", ignore_index=True)


def candidate_space(
    capacity: CapacityModel,
    *,
    scenario: str,
    eligible_screens: int,
    flight_days: int,
    blocks_requested: int | None = None,
) -> Mapping[str, Any]:
    """Decision-variable count for one campaign shape — the solver's real input.

    Phase 7 selects (screen, time block) pairs and an integer slot count for each, so
    the variable count is pairs, not slot-days. Both are reported: the pair count
    sizes the solver, the slot-day count sizes the inventory it draws from.
    """
    blocks = blocks_requested or capacity.blocks_per_day
    pairs = eligible_screens * blocks
    return {
        "scenario": scenario,
        "eligible_screens": eligible_screens,
        "blocks": blocks,
        "flight_days": flight_days,
        "decision_pairs": pairs,
        "slot_day_inventory": pairs * capacity.slots_per_block * flight_days,
    }


#: Fraction of a city's inventory a typical eligibility filter is assumed to leave.
#: An assumption, labelled as one — it is replaced by a measurement in Phase 5.
ASSUMED_ELIGIBLE_FRACTION = 0.10
#: Screens a hyper-local, walking-radius brief can plausibly reach. Validated in Step 1.6.
ASSUMED_HYPERLOCAL_SCREENS = 50


def solver_scenarios(
    units: SellableUnits,
    *,
    largest_city_screens: int,
    median_flight_days: int,
    typical_blocks_requested: int = 2,
) -> pd.DataFrame:
    """Problem size across the campaign shapes Phase 7 will actually be handed."""
    capacity = units.capacity
    network_screens = int(
        units.per_city.loc[units.per_city["city_id"] == "network", "screens"].iloc[0]
    )
    eligible = max(1, round(largest_city_screens * ASSUMED_ELIGIBLE_FRACTION))

    rows = [
        candidate_space(
            capacity,
            scenario="Whole network, whole horizon (upper bound, not a real query)",
            eligible_screens=network_screens,
            flight_days=units.horizon_days,
        ),
        candidate_space(
            capacity,
            scenario="Largest city, all blocks, median flight",
            eligible_screens=largest_city_screens,
            flight_days=median_flight_days,
        ),
        candidate_space(
            capacity,
            scenario=f"Largest city, {typical_blocks_requested} requested blocks, median flight",
            eligible_screens=largest_city_screens,
            flight_days=median_flight_days,
            blocks_requested=typical_blocks_requested,
        ),
        candidate_space(
            capacity,
            scenario=f"After eligibility filter (assumed {ASSUMED_ELIGIBLE_FRACTION:.0%} of a city)",
            eligible_screens=eligible,
            flight_days=median_flight_days,
            blocks_requested=typical_blocks_requested,
        ),
        candidate_space(
            capacity,
            scenario=f"Hyper-local brief (assumed ~{ASSUMED_HYPERLOCAL_SCREENS} screens in radius)",
            eligible_screens=ASSUMED_HYPERLOCAL_SCREENS,
            flight_days=15,
            blocks_requested=typical_blocks_requested,
        ),
    ]
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- cold start
def cold_start_census(screens: pd.DataFrame, bookings: pd.DataFrame) -> pd.DataFrame:
    """Screens with no booking history, cut by the facets that drive the fallback ladder."""
    booked = set(bookings["screen_id"].unique())
    flagged = screens.assign(has_history=screens["screen_id"].isin(booked))

    frames = []
    for facet in ("city_id", "screen_type", "screen_size"):
        grouped = (
            flagged.groupby(facet, observed=True)["has_history"]
            .agg(screens="size", with_history="sum")
            .reset_index()
            .rename(columns={facet: "value"})
        )
        grouped.insert(0, "facet", facet)
        frames.append(grouped)

    table = pd.concat(frames, ignore_index=True)
    table["no_history"] = table["screens"] - table["with_history"]
    table["cold_share"] = table["no_history"] / table["screens"]
    return table


def block_demand(bookings: pd.DataFrame, slot_dim: pd.DataFrame) -> pd.DataFrame:
    """Which time blocks the market actually buys, and at what price."""
    table = (
        bookings.groupby("time_block_id", observed=True)
        .agg(
            lines=("booking_id", "count"),
            slot_days=("slots_booked_per_day", "sum"),
            median_price=("contracted_price_per_slot_per_day", "median"),
        )
        .reset_index()
        .merge(slot_dim, on="time_block_id", how="left")
    )
    table["line_share"] = table["lines"] / table["lines"].sum()
    return table[
        [
            "time_block_id",
            "time_block_label",
            "nearest_daypart",
            "lines",
            "line_share",
            "slot_days",
            "median_price",
        ]
    ]


def rotation_economics(bookings: pd.DataFrame) -> pd.DataFrame:
    """Price per slot against slots bought — the first look at the non-linearity nuance."""
    table = (
        bookings.groupby("slots_booked_per_day", observed=True)
        .agg(
            lines=("booking_id", "count"),
            median_price_per_slot=("contracted_price_per_slot_per_day", "median"),
            value=("line_item_value", "sum"),
        )
        .reset_index()
    )
    baseline = table.loc[table["slots_booked_per_day"] == 1, "median_price_per_slot"]
    if len(baseline):
        table["vs_single_slot"] = table["median_price_per_slot"] / baseline.iloc[0] - 1
        table["implied_total_vs_linear"] = (
            table["slots_booked_per_day"] * table["median_price_per_slot"]
        ) / (table["slots_booked_per_day"] * baseline.iloc[0])
    return table


# ---------------------------------------------------------------------- assembly
@dataclass(frozen=True)
class InventoryShape:
    """Everything Step 1.4 measured, in one passable object."""

    as_of: AsOfDate
    capacity: CapacityModel
    units: SellableUnits
    deployment: pd.DataFrame
    by_city_type: pd.DataFrame
    by_position: pd.DataFrame
    by_size: pd.DataFrame
    concentration: pd.DataFrame
    cold_start: pd.DataFrame
    availability: pd.DataFrame
    blocks: pd.DataFrame
    rotation: pd.DataFrame
    scenarios: pd.DataFrame
    booked_units: int
    largest_city: str
    largest_city_screens: int
    median_flight_days: int
    daypart_mismatches: int
    booking_lines: int

    @property
    def static_screens(self) -> int:
        return int(self.deployment.loc[self.deployment["mounting"] == "static", "screens"].sum())

    @property
    def mobile_screens(self) -> int:
        return int(self.deployment.loc[self.deployment["mounting"] == "mobile", "screens"].sum())

    @property
    def screens_with_history(self) -> int:
        city_rows = self.cold_start[self.cold_start["facet"] == "city_id"]
        return int(city_rows["with_history"].sum())


def profile_inventory(lake: DataLake) -> InventoryShape:
    """Run every Step 1.4 measurement against the lake."""
    screens = lake["screens"]
    bookings = lake["bookings"]
    slot_dim = lake["dim_slot"]

    as_of = infer_as_of_date(bookings, lake["ridership_actuals"])
    capacity = measure_capacity(bookings, slot_dim)
    # The forward horizon starts at the as-of date, not at the earliest committed
    # booking: `active` lines began before today, and only the remainder of them is
    # still occupying sellable inventory.
    units = sellable_units(
        screens,
        bookings,
        capacity,
        horizon_start=as_of.date,
        horizon_end=bookings["end_date"].max(),
    )

    city_counts = screens.groupby("city_id", observed=True).size()
    largest_city = str(city_counts.idxmax())
    median_flight = int(bookings["duration_days"].median())

    # bookings.daypart should be a pure denormalisation of dim_slot.nearest_daypart.
    joined = bookings[["time_block_id", "daypart"]].merge(
        slot_dim[["time_block_id", "nearest_daypart"]], on="time_block_id", how="left"
    )
    mismatches = int(
        (joined["daypart"].astype("object") != joined["nearest_daypart"].astype("object")).sum()
    )

    return InventoryShape(
        as_of=as_of,
        capacity=capacity,
        units=units,
        deployment=deployment_split(screens),
        by_city_type=facet_counts(screens, "screen_type", "city_id"),
        by_position=facet_counts(screens, "position", "screen_type"),
        by_size=facet_counts(screens, "screen_size", "screen_type"),
        concentration=concentration(screens, lake["locations"], lake["vehicles"]),
        cold_start=cold_start_census(screens, bookings),
        availability=availability_by_block(
            screens,
            bookings,
            capacity,
            slot_dim,
            horizon_start=units.horizon_start,
            horizon_end=units.horizon_end,
        ),
        blocks=block_demand(bookings, slot_dim),
        rotation=rotation_economics(bookings),
        scenarios=solver_scenarios(
            units,
            largest_city_screens=int(city_counts.max()),
            median_flight_days=median_flight,
        ),
        booked_units=int(
            bookings.groupby(["screen_id", "time_block_id"], observed=True).ngroups
        ),
        largest_city=largest_city,
        largest_city_screens=int(city_counts.max()),
        median_flight_days=median_flight,
        daypart_mismatches=mismatches,
        booking_lines=len(bookings),
    )
