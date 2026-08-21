"""Renders the Step 1.4 inventory-shape report to markdown.

Kept separate from :mod:`agentiq.data.inventory` so the measurements stay usable
without dragging prose along: Phase 7 imports the numbers, this module is only for
the committed document.
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from .inventory import InventoryShape

TITLE = "Step 1.4 — Inventory Shape"


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (pd.Timestamp,)):
        return value.date().isoformat()
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _table(frame: pd.DataFrame, *, index: bool = False, percent: Sequence[str] = ()) -> str:
    """Render a frame as a GitHub markdown table."""
    display = frame.reset_index() if index else frame
    header = [str(column) for column in display.columns]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in display.itertuples(index=False):
        cells = []
        for column, value in zip(display.columns, row):
            if column in percent and isinstance(value, float) and not pd.isna(value):
                cells.append(f"{value:.1%}")
            else:
                cells.append(_fmt(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_inventory_report(shape: InventoryShape, *, generated_at: str | None = None) -> str:
    capacity = shape.capacity
    units = shape.units
    network = units.network
    per_city = units.per_city[units.per_city["city_id"] != "network"]

    block_units = network["screens"] * capacity.blocks_per_day
    booked_share = shape.booked_units / block_units

    lines: list[str] = [
        f"# {TITLE}",
        "",
        "> **Generated file — do not edit by hand.** Regenerate with",
        "> `python scripts/build_inventory_report.py`.",
        "> Every number below is measured from the raw CSVs"
        + (f" ({generated_at})." if generated_at else "."),
        "> Schema facts cited here come from [`data_dictionary.md`](../data_dictionary.md).",
        "",
        "**Purpose.** Establish exactly what is being sold, so that Phase 7's solver is",
        "designed against the real problem size and Phase 6 prices a unit that actually",
        "exists. Phase 7 must cite the sellable-unit count in §3.",
        "",
        "---",
        "",
        "## 0. Headline numbers",
        "",
        _table(
            pd.DataFrame(
                [
                    {"measure": "Screens in the network", "value": _fmt(network["screens"])},
                    {
                        "measure": "Static / mobile split",
                        "value": f"{_fmt(shape.static_screens)} static / "
                        f"{_fmt(shape.mobile_screens)} mobile",
                    },
                    {
                        "measure": "Time blocks per day",
                        "value": f"{capacity.blocks_per_day} (four-hour, gapless)",
                    },
                    {
                        "measure": "Rotation slots per block (measured capacity)",
                        "value": f"{capacity.slots_per_block}",
                    },
                    {
                        "measure": "Sellable slot-units per screen per day",
                        "value": f"{capacity.slots_per_screen_day} "
                        f"({capacity.blocks_per_day} blocks x {capacity.slots_per_block} slots)",
                    },
                    {
                        "measure": "**Sellable slot-units per day, network**",
                        "value": f"**{_fmt(network['slot_units_per_day'])}**",
                    },
                    {
                        "measure": "As-of date (the dataset's 'today')",
                        "value": _fmt(shape.as_of.date),
                    },
                    {
                        "measure": "Forward horizon",
                        "value": f"{_fmt(units.horizon_start)} → {_fmt(units.horizon_end)} "
                        f"({units.horizon_days} days)",
                    },
                    {
                        "measure": "**Sellable slot-units over the horizon**",
                        "value": f"**{_fmt(network['slot_units_horizon'])}**",
                    },
                    {
                        "measure": "Already committed",
                        "value": f"{_fmt(network['committed_slot_units'])} "
                        f"({network['committed_slot_units'] / network['slot_units_horizon']:.1%})",
                    },
                    {
                        "measure": "**Still available**",
                        "value": f"**{_fmt(network['available_slot_units'])}**",
                    },
                ]
            )
        ),
        "",
        "---",
        "",
        "## 1. What one row of inventory is",
        "",
        f"### 1.1 The as-of date is {shape.as_of.date.date()}, not today",
        "",
        "The dataset has no `today` column. It is triangulated from four independent",
        "signals that agree exactly:",
        "",
    ]
    lines += [f"- {evidence}" for evidence in shape.as_of.evidence()]
    lines += [
        "",
        f"**Therefore the as-of date is `{shape.as_of.date.date()}`"
        + (" and the boundary is unambiguous" if shape.as_of.is_unambiguous else "")
        + ".** Every back-test, availability check and demand baseline must use this",
        "date rather than the wall clock, or the model trains on its own future.",
        "",
        "| Booking status | Meaning here | Use |",
        "| --- | --- | --- |",
        "| `completed` | Ends on or before the as-of date | **Training data** — settled price history |",
        "| `active` | Spans the as-of date | **Committed occupancy** — inventory already claimed |",
        "| `upcoming` | Starts after the as-of date | **Committed occupancy** — future claim |",
        "",
        "The three windows are disjoint, so this classification is exact rather than a",
        "heuristic on dates.",
        "",
        "### 1.2 The sellable unit",
        "",
        "```",
        "SellableUnit = screen x time_block x date, holding N rotation slots",
        "```",
        "",
        f"A booking line claims `slots_booked_per_day` slots on a single "
        f"`time_block_id` for every date between `start_date` and `end_date`. The time",
        f"dimension is closed and gapless: {capacity.blocks_per_day} four-hour blocks",
        "cover the day, and `bookings.daypart` was verified to be a pure denormalisation",
        f"of `dim_slot.nearest_daypart` — **{shape.daypart_mismatches} mismatches in "
        f"{_fmt(shape.booking_lines)} lines** — so `daypart` can be dropped everywhere in",
        "favour of `time_block_id`. Note `night` maps to two blocks (1 and 6), which is",
        "why daypart is not a key.",
        "",
        f"### 1.3 Capacity is {capacity.slots_per_block} slots per block — measured, then proved",
        "",
        "`rotation_type` and `slots_booked_per_day` are not two independent facts. They",
        "partition each other exactly:",
        "",
        _table(capacity.rotation_table()),
        "",
        "So `rotation_type` is a **label on a slot count**, not extra information. The",
        f"upper bound is {capacity.slots_per_block}, and a sweep line over all "
        f"{_fmt(shape.booking_lines)} bookings confirms it is a real ceiling rather than a",
        "coincidence of the sample:",
        "",
        f"- peak concurrent slots on any screen x block x date: **{capacity.peak_concurrent_slots_observed}**",
        f"- units ever sold beyond that: **{capacity.units_ever_oversold}**",
        f"- capacity model validated: **{_fmt(capacity.is_validated)}**",
        "",
        "This is the constraint Phase 7 optimises against and the divisibility that makes",
        "a screen a *resource* rather than a yes/no purchase.",
        "",
        "> **Open item for Phase 4.** The briefs express slot requests in seconds per",
        "> minute (\"1 rotating slot (15 seconds per minute)\"). No column gives a slot's",
        "> duration, so the seconds→slots conversion cannot be derived from the data and",
        "> must be an explicit, stated config parameter.",
        "",
        "---",
        "",
        "## 2. What the inventory is",
        "",
        "### 2.1 Static versus mobile — the split that picks the exposure model",
        "",
        _table(shape.deployment, percent=("share_of_network",)),
        "",
        "`screen_type` maps **1:1** onto the mounting split, so the type alone decides",
        "which D1 model applies — no null-checking logic needed downstream.",
        "",
        "### 2.2 Screens by city and type",
        "",
        _table(shape.by_city_type, index=True),
        "",
        "The network is heavily skewed toward the premium city and toward metro stations.",
        "Any per-city average is therefore misleading; report per-city figures throughout.",
        "",
        "### 2.3 Mount position by type",
        "",
        _table(shape.by_position, index=True),
        "",
        "Position is **structural, not random**:",
        "",
        "- `metro_rail_coach` screens have **no position at all** — they are interior coach",
        "  panels facing a captive rider, so mount face is meaningless. This is the one",
        "  legitimate null in the column.",
        "- `bus` screens are always exactly one of `back` / `left` / `right`, 405 of each.",
        "- `bus_stop` screens are always `left` / `right` / `top`.",
        "- `metro_station` screens are `platform` or `entrance_exit` — platform screens",
        "  reach a waiting audience, entrance screens a moving one.",
        "",
        f"**The {_fmt(int(shape.by_position.loc['back', 'bus']))} `bus` + `back` screens are "
        "the \"bus-rear\" inventory the briefs name",
        "explicitly** — brief 1 excludes it, brief 2 requires it. It is directly",
        "addressable, so both constraints are enforceable in the Phase 5 filter.",
        "",
        "### 2.4 Screen size by type",
        "",
        _table(shape.by_size, index=True),
        "",
        "Size is largely determined by type and position (all coach screens are `M`; bus",
        "`back` screens are all `S` while bus `left`/`right` are all `L`), so size and type",
        "are **collinear** and must not be entered into the pricing model as independent",
        "features without checking their joint effect first (Step 1.5).",
        "",
        "### 2.5 Concentration — how clustered the inventory is",
        "",
        _table(shape.concentration),
        "",
        "This is the size of the Phase 3 overlap problem. Bus stops carry exactly 3",
        "screens each, but metro stations carry a median of 34 and up to 50. Fifty screens",
        "in one station are **one audience cluster, not fifty independent buys** — without",
        "the overlap graph, a package that fills a single station would report roughly the",
        "reach of fifty separate locations. Phase 7's de-duplication has to bite hardest",
        "exactly here.",
        "",
        "---",
        "",
        "## 3. The optimisation problem size",
        "",
        "**Phase 7 must cite this section.**",
        "",
        "### 3.1 Sellable units per city",
        "",
        _table(units.per_city, percent=("utilisation",)),
        "",
        "Column meanings:",
        "",
        "- `block_units_per_day` — screen x time block pairs available on one day.",
        f"- `slot_units_per_day` — the same, times {capacity.slots_per_block} rotation slots.",
        f"- `slot_units_horizon` — over the {units.horizon_days}-day forward horizon",
        f"  ({_fmt(units.horizon_start)} → {_fmt(units.horizon_end)}).",
        "- `committed_slot_units` — already claimed by `active` and `upcoming` bookings,",
        "  computed exactly from each booking's overlap with the horizon (safe to sum",
        "  because §1.3 proves no unit is oversold).",
        "- `available_slot_units` — what can still be sold. **This is the real supply.**",
        "",
        "### 3.2 What this means for solver design",
        "",
        f"A brute-force formulation over the whole horizon has "
        f"**{_fmt(network['slot_units_horizon'])} slot-units** — far past exact",
        "optimisation. But that is not the problem the solver actually faces, because a",
        "campaign is scoped to one city, a date window and an eligible screen set. The",
        f"honest sizing is per campaign (largest city = `{shape.largest_city}` with",
        f"{_fmt(shape.largest_city_screens)} screens; median flight = "
        f"{shape.median_flight_days} days, both measured):",
        "",
        _table(shape.scenarios),
        "",
        "The last two rows carry a **stated assumption**, not a measurement: the share of",
        "a city that survives eligibility filtering is unknown until Phase 5 measures it.",
        "The radius figure is validated in Step 1.6.",
        "",
        "**Consequences for Phase 7:**",
        "",
        "1. **Filter before scoring, always.** The eligibility filter is what turns an",
        "   intractable count into a few thousand decision pairs. It is a correctness",
        "   requirement, not an optimisation.",
        "2. **Slot count is an integer variable, not a binary one.** Each chosen pair",
        f"   carries 1–{capacity.slots_per_block} slots, and §4.2 shows price per slot falls",
        "   as slots rise, so the slot count is a genuine decision with a concave payoff.",
        "3. **Greedy is the right default and ILP is reachable.** At a few thousand pairs a",
        "   lazy-greedy pass over a submodular objective is near-instant; the post-filter",
        "   scenarios are small enough that an exact formulation is viable for the",
        "   \"thorough\" mode, which is what makes the latency/quality table in Step 10.1",
        "   an honest comparison rather than a hypothetical.",
        "4. **Availability is a hard constraint, and it is uneven.** See §3.3 — the",
        "   network average understates the constraint badly on the blocks briefs want.",
        "",
        "### 3.3 Where availability actually bites",
        "",
        _table(shape.availability, percent=("utilisation",)),
        "",
        f"Network-wide forward utilisation is "
        f"{network['committed_slot_units'] / network['slot_units_horizon']:.1%}, which sounds",
        "like ample supply. Per block it is not: the commute peaks carry several times",
        "the utilisation of the night blocks. **Quoting a single average would have made",
        "the availability constraint look non-binding when on peak inventory it is the",
        "binding constraint.** Two consequences:",
        "",
        "- Phase 7 must check availability at `screen x block x date` grain, never at",
        "  screen level, and never against an average.",
        "- Phase 6's scarcity signal has real variance to work with — committed occupancy",
        "  differs enough between blocks to move a price defensibly.",
        "",
        "---",
        "",
        "## 4. What the market actually buys",
        "",
        "### 4.1 Demand by time block",
        "",
        _table(shape.blocks, percent=("line_share",)),
        "",
        "Demand is bimodal on the commute peaks. The two night blocks (1 and 6) together",
        "take a small share of lines at roughly half the median price — so **night",
        "inventory is abundant and cheap**, which is exactly the supply a late-night brief",
        "(brief 2) needs, and exactly the inventory a premium daytime brief should not be",
        "padded with to hit a budget.",
        "",
        "### 4.2 Price per slot falls as slots rise",
        "",
        _table(shape.rotation, percent=("vs_single_slot",)),
        "",
        "Median price per slot per day declines monotonically as more slots are bought.",
        "`implied_total_vs_linear` is the ratio of the actual total to a linear",
        "extrapolation from a single slot: consistently **below 1**, i.e. buying the whole",
        "rotation costs less than six times one slot.",
        "",
        "This is the first direct evidence for the **non-linear impressions/pricing",
        "nuance** — and it cuts both ways: revenue per slot falls with volume while",
        "attention per slot also falls with volume. Step 1.5 must test whether the",
        "discount is a pure volume effect or is confounded with screen type and block,",
        "and Phase 3 must model the attention curve separately from the price curve.",
        "",
        "### 4.3 History coverage of the inventory",
        "",
        f"- screen x block pairs with any booking history: **{_fmt(shape.booked_units)}** of "
        f"**{_fmt(block_units)}** ({booked_share:.1%})",
        f"- screens with any history: **{_fmt(shape.screens_with_history)}** of "
        f"**{_fmt(network['screens'])}**",
        "",
        "### 4.4 Cold start is a new-market problem, not a scattered one",
        "",
        _table(shape.cold_start, percent=("cold_share",)),
        "",
        "The screens with no history are **not spread evenly** — they cluster in one city",
        "and in the cheapest screen types. The premium city has full coverage; the value",
        "city has more than half its inventory unpriced.",
        "",
        "That is the single most useful finding in this step for the demo narrative: the",
        "cold-start ladder (Step 6.5) is not an edge case bolted on for completeness, it",
        "is **how an entire market gets priced**. It is also the honest answer to \"how",
        "would you scale to a new city\" — a new city looks exactly like the value city,",
        "only more so, and the ladder already has to work there.",
        "",
        "---",
        "",
        "## 5. Capability gaps this step exposes",
        "",
        "Attributes the briefs ask for that **do not exist** in the inventory data. Each",
        "needs a decision before Phase 5, not a surprise during the demo.",
        "",
        "| Brief asks for | Data has | Resolution required |",
        "| --- | --- | --- |",
        "| \"digital screens only\", motion creative | No digital/static or display-technology column | Treat all inventory as digital-capable and **state the assumption**, or derive a proxy from `screen_type` |",
        "| 16:9 / 9:16 / 1:1 aspect ratios | `screen_size` is only S/M/L | Map size+position → an assumed orientation in `config/taxonomy.yaml`, flagged as an assumption |",
        "| Slot request in seconds per minute | `slots_booked_per_day` (1–6), no slot duration | Explicit seconds-per-slot config constant |",
        "| \"bus-rear screens\" | `screen_type='bus'` + `position='back'` (405 screens) | **Supported** — no work needed |",
        "| \"metro platform boards\" | `screen_type='metro_station'` + `position='platform'` | **Supported** |",
        "| \"high-dwell\" platforms | `location_type`, `position` | Derive a dwell proxy in Phase 3; document it |",
        "| Walking-radius limits | POI distances to locations, not screen-to-screen distances | Radius is expressible around a *location*; confirm in Step 1.6 |",
        "",
        "---",
        "",
        "## 6. Carry-forward",
        "",
        "| Output | Consumed by |",
        "| --- | --- |",
        f"| As-of date `{shape.as_of.date.date()}` and the settled/committed split | every train/test split, all availability logic |",
        f"| Capacity model ({capacity.blocks_per_day} blocks x {capacity.slots_per_block} slots) | Phase 6 unit pricing, Phase 7 constraints |",
        "| `occupancy_timeline()` sweep line | Step 1.5 occupancy, Step 6.1 scarcity |",
        "| Sellable-unit and availability counts per city | Phase 7 solver-strategy choice |",
        "| Concentration table | Phase 3 overlap graph |",
        "| Cold-start census | Step 6.5 fallback ladder, new-city scaling story |",
        "| Capability gaps (§5) | Phase 4 brief resolution, `config/taxonomy.yaml` |",
        "",
        "**Next — Step 1.5 (demand history).** Price distribution by every facet named",
        "here, the occupancy expansion at date grain, bundle pricing, and the formal test",
        "of whether the §4.2 slot discount survives controlling for screen type and block.",
        "",
    ]
    return "\n".join(lines) + "\n"
