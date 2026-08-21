"""The booking-expansion transform (Step 1.5 §3) — a core reusable artifact.

`occupancy_timeline()` is ported verbatim from `notebooks/02_demand_profile.ipynb`
(cell defining the function), where it was validated against a brute-force
per-row overlap check on synthetic data and cross-checked against Step 1.4's
independent sweep-line proof of the 6-slot capacity ceiling. Step 6.1's
scarcity signal and Phase 7's availability constraint both reuse this
function rather than re-deriving it, per the notebook's own carry-forward
note and `docs/decisions/1.5_demand_profile.md` §3/§7.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from agentiq.domain.inventory import MAX_ROTATION_SLOTS


def occupancy_events(lines: pd.DataFrame) -> pd.DataFrame:
    """Claimed-slot level per (screen_id, time_block_id), via a +/- sweep line.

    *lines* must have `screen_id`, `time_block_id`, `start_date`, `end_date`,
    `slots_booked_per_day` columns — any subset of `bookings` (settled,
    committed, or both) can be passed, per the caller's intent.

    Returns a **sparse event log**, not a dense daily series: one row per
    (screen_id, time_block_id, date) where occupancy *changes* (including
    drops back to zero), carrying the new `occupied_slots` level from that
    date forward until the next event. This is the shared sweep behind both
    `occupancy_timeline` (filtered to non-zero rows, for reporting) and
    `committed_occupancy_share` (an as-of lookup, which needs the
    zero-crossing rows to correctly report zero after a booking lapses) —
    kept as one function so the two callers cannot silently disagree on the
    underlying computation.
    """
    starts = lines[["screen_id", "time_block_id", "start_date", "slots_booked_per_day"]].rename(
        columns={"start_date": "date", "slots_booked_per_day": "delta"}
    )
    ends = lines[["screen_id", "time_block_id", "end_date", "slots_booked_per_day"]].rename(
        columns={"end_date": "date", "slots_booked_per_day": "delta"}
    )
    ends["date"] = ends["date"] + pd.Timedelta(1, unit="D")
    ends["delta"] = -ends["delta"]

    events = pd.concat([starts, ends], ignore_index=True)
    events = events.groupby(["screen_id", "time_block_id", "date"], as_index=False)["delta"].sum()
    events = events.sort_values(["screen_id", "time_block_id", "date"])
    events["occupied_slots"] = events.groupby(["screen_id", "time_block_id"])["delta"].cumsum()
    return events[["screen_id", "time_block_id", "date", "occupied_slots"]]


def occupancy_timeline(lines: pd.DataFrame) -> pd.DataFrame:
    """Non-zero occupancy rows only — Step 1.5 §3's reporting contract.

    Ported from `notebooks/02_demand_profile.ipynb`, where it was validated
    against a brute-force per-row overlap check on synthetic data and
    cross-checked against Step 1.4's independent sweep-line proof of the
    6-slot capacity ceiling. Used for counting non-zero (screen, block,
    date) rows and finding the peak — **not** for an as-of "what is
    occupancy on date X" lookup, since dates where occupancy is zero (or
    unchanged since the last event) are absent by construction; use
    `committed_occupancy_share` (backed by the unfiltered `occupancy_events`)
    for that.
    """
    events = occupancy_events(lines)
    return events.loc[events["occupied_slots"] > 0]


def committed_occupancy_share(
    events: pd.DataFrame,
    screen_id: str,
    time_block_id: int,
    on_date: date,
    *,
    capacity: int = MAX_ROTATION_SLOTS,
) -> float:
    """Share of capacity already claimed for one (screen, block, date) — Step 6.1's input.

    *events* must be the **unfiltered** sweep from `occupancy_events` (not
    `occupancy_timeline`'s `> 0`-filtered output) — this is an as-of lookup
    (most recent event on or before `on_date`, value carried forward), and
    needs the zero-crossing rows to correctly report zero after a booking
    lapses. Returns 0.0 when no event exists on or before `on_date`.
    """
    on_date_ts = pd.Timestamp(on_date)
    rows = events.loc[
        (events["screen_id"] == screen_id)
        & (events["time_block_id"] == time_block_id)
        & (events["date"] <= on_date_ts)
    ]
    if rows.empty:
        return 0.0
    latest = rows.loc[rows["date"].idxmax()]
    occupied = float(latest["occupied_slots"])
    return min(max(occupied, 0.0) / capacity, 1.0)
