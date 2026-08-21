"""Measured entity-relationship map (Step 1.3).

Nothing here is inferred from column names. For every declared foreign key we
measure:

* **Referential integrity** — what share of non-null child keys exist in the parent.
* **Fan-out** — max children per parent and max parents per child, which together
  classify the edge as 1:1 / N:1 / 1:N / N:M. A fan-out trap (e.g. a screen that
  joins to many route rows) is a silent row-multiplier in every later aggregation,
  so it is recorded with the aggregation the consumer must apply.
* **Orphans** — child rows that join to nothing. These are the cold-start
  population that Phase 6's fallback ladder has to serve.

Multi-hop **key paths** (screen -> location -> zone -> city, and the rest of the
paths named in the plan) are then traced end to end, so we know what fraction of
screens can actually be resolved to demographics, to a corridor, to POIs, and to
commercial history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from .catalog import CATALOG, ForeignKey, TableSpec, all_foreign_keys
from .loaders import DataLake


@dataclass(frozen=True)
class JoinCheck:
    """The measured truth about one child -> parent edge."""

    child_table: str
    child_column: str
    parent_table: str
    parent_column: str
    declared_nullable: bool
    note: str
    child_rows: int
    child_non_null: int
    child_null_pct: float
    child_distinct_keys: int
    matched_rows: int
    orphan_rows: int
    orphan_distinct_keys: int
    orphan_examples: tuple[Any, ...]
    parent_rows: int
    parent_distinct_keys: int
    parent_key_unique: bool
    matched_parent_keys: int
    max_children_per_parent: int
    max_parents_per_child: int

    @property
    def integrity_pct(self) -> float:
        """Share of non-null child keys that resolve to a parent."""
        return 1.0 if self.child_non_null == 0 else self.matched_rows / self.child_non_null

    @property
    def parent_coverage_pct(self) -> float:
        """Share of parent keys that are referenced at least once."""
        if self.parent_distinct_keys == 0:
            return 0.0
        return self.matched_parent_keys / self.parent_distinct_keys

    @property
    def cardinality(self) -> str:
        """Child-side : parent-side, e.g. ``N:1`` for many bookings to one screen."""
        child_side = "1" if self.max_children_per_parent <= 1 else "N"
        parent_side = "1" if self.max_parents_per_child <= 1 else "N"
        return f"{child_side}:{parent_side}"

    @property
    def is_fanout_trap(self) -> bool:
        """True when a naive merge on this edge multiplies rows."""
        return self.max_parents_per_child > 1

    @property
    def status(self) -> str:
        if self.child_non_null == 0:
            return "EMPTY"
        if self.integrity_pct == 1.0:
            return "OK"
        if self.integrity_pct >= 0.99:
            return "NEAR-OK"
        return "BROKEN"

    @property
    def unexpected_nulls(self) -> bool:
        return not self.declared_nullable and self.child_null_pct > 0

    @property
    def edge(self) -> str:
        return (
            f"{self.child_table}.{self.child_column} -> "
            f"{self.parent_table}.{self.parent_column}"
        )

    def as_row(self) -> Mapping[str, Any]:
        return {
            "child_table": self.child_table,
            "child_column": self.child_column,
            "parent_table": self.parent_table,
            "parent_column": self.parent_column,
            "child_rows": self.child_rows,
            "child_null_pct": round(self.child_null_pct, 4),
            "nullable_declared": self.declared_nullable,
            "integrity_pct": round(self.integrity_pct, 6),
            "orphan_rows": self.orphan_rows,
            "orphan_keys": self.orphan_distinct_keys,
            "cardinality": self.cardinality,
            "max_children_per_parent": self.max_children_per_parent,
            "max_parents_per_child": self.max_parents_per_child,
            "parent_key_unique": self.parent_key_unique,
            "parent_coverage_pct": round(self.parent_coverage_pct, 4),
            "fanout_trap": self.is_fanout_trap,
            "status": self.status,
            "note": self.note,
        }


def check_join(
    child: pd.DataFrame,
    parent: pd.DataFrame,
    foreign_key: ForeignKey,
    *,
    child_table: str,
    orphan_examples: int = 5,
) -> JoinCheck:
    """Measure one declared edge. Pure function — no I/O, no catalogue lookups."""
    if foreign_key.column not in child.columns:
        raise KeyError(f"{child_table} has no column {foreign_key.column!r}")
    if foreign_key.parent_column not in parent.columns:
        raise KeyError(
            f"{foreign_key.parent_table} has no column {foreign_key.parent_column!r}"
        )

    child_keys = child[foreign_key.column]
    # Categorical dtypes make set arithmetic awkward; compare on plain values.
    child_present = child_keys.dropna().astype("object")
    parent_keys = parent[foreign_key.parent_column].dropna().astype("object")

    parent_counts = parent_keys.value_counts()
    parent_key_set = set(parent_counts.index)

    matched_mask = child_present.isin(parent_key_set)
    matched_rows = int(matched_mask.sum())
    orphans = child_present[~matched_mask]
    orphan_key_counts = orphans.value_counts()

    child_counts = child_present.value_counts()
    matched_keys = [key for key in child_counts.index if key in parent_key_set]

    max_children_per_parent = int(child_counts.reindex(matched_keys).max()) if matched_keys else 0
    max_parents_per_child = int(parent_counts.reindex(matched_keys).max()) if matched_keys else 0

    return JoinCheck(
        child_table=child_table,
        child_column=foreign_key.column,
        parent_table=foreign_key.parent_table,
        parent_column=foreign_key.parent_column,
        declared_nullable=foreign_key.nullable,
        note=foreign_key.note,
        child_rows=len(child),
        child_non_null=len(child_present),
        child_null_pct=0.0 if len(child) == 0 else 1 - len(child_present) / len(child),
        child_distinct_keys=int(child_counts.size),
        matched_rows=matched_rows,
        orphan_rows=int(len(orphans)),
        orphan_distinct_keys=int(orphan_key_counts.size),
        orphan_examples=tuple(orphan_key_counts.index[:orphan_examples]),
        parent_rows=len(parent),
        parent_distinct_keys=int(parent_counts.size),
        parent_key_unique=bool(parent_counts.empty or parent_counts.max() == 1),
        matched_parent_keys=len(matched_keys),
        max_children_per_parent=max_children_per_parent,
        max_parents_per_child=max_parents_per_child,
    )


def check_all_joins(
    lake: DataLake,
    *,
    edges: Sequence[tuple[str, ForeignKey]] | None = None,
) -> tuple[JoinCheck, ...]:
    """Measure every declared edge in the catalogue."""
    return tuple(
        check_join(
            lake.load(child_table),
            lake.load(foreign_key.parent_table),
            foreign_key,
            child_table=child_table,
        )
        for child_table, foreign_key in (edges or all_foreign_keys())
    )


def joins_frame(checks: Iterable[JoinCheck]) -> pd.DataFrame:
    return pd.DataFrame([check.as_row() for check in checks])


# ------------------------------------------------------------------- key paths
@dataclass(frozen=True)
class PathHop:
    """One hop of a key path: join *from_table*.*from_column* onto *to_table*.*to_column*."""

    from_column: str
    to_table: str
    to_column: str
    label: str = ""


@dataclass(frozen=True)
class KeyPath:
    """A multi-hop path whose end-to-end resolution rate we care about."""

    name: str
    start_table: str
    hops: tuple[PathHop, ...]
    why: str = ""
    #: Optional predicate name applied to the start table before tracing
    #: (e.g. only static screens can resolve through a location).
    subset: str = ""


@dataclass(frozen=True)
class PathTrace:
    path: KeyPath
    start_rows: int
    resolved_at_hop: tuple[tuple[str, int], ...]
    final_rows: int
    row_multiplication: float
    unresolved_rows: int

    @property
    def resolution_pct(self) -> float:
        return 0.0 if self.start_rows == 0 else 1 - self.unresolved_rows / self.start_rows

    def as_rows(self) -> list[Mapping[str, Any]]:
        rows = []
        for hop_label, resolved in self.resolved_at_hop:
            rows.append(
                {
                    "path": self.path.name,
                    "hop": hop_label,
                    "rows_resolved": resolved,
                    "start_rows": self.start_rows,
                    "resolved_pct": round(
                        0.0 if self.start_rows == 0 else resolved / self.start_rows, 4
                    ),
                }
            )
        return rows


#: The paths the plan requires us to establish and validate before Phase 3.
KEY_PATHS: tuple[KeyPath, ...] = (
    KeyPath(
        name="static geography: screen -> location -> zone -> city",
        start_table="screens",
        subset="static_screens",
        hops=(
            PathHop("location_id", "locations", "location_id", "screen -> location"),
            PathHop("zone_id", "zone_demographics", "zone_id", "location -> zone"),
            PathHop("city_id", "cities", "city_id", "zone -> city"),
        ),
        why="D1 static exposure: resident base and daytime multiplier for a fixed screen.",
    ),
    KeyPath(
        name="mobile exposure: screen -> vehicle -> corridor",
        start_table="screens",
        subset="mobile_screens",
        hops=(
            PathHop("vehicle_id", "vehicles", "vehicle_id", "screen -> vehicle"),
            PathHop("corridor_id", "route_stops", "corridor_id", "vehicle -> corridor stops"),
        ),
        why="D1 mobile exposure: the journey a vehicle-mounted screen travels.",
    ),
    KeyPath(
        name="ridership: ridership_actuals -> schedule -> route",
        start_table="ridership_actuals",
        hops=(
            PathHop("schedule_id", "route_schedules", "schedule_id", "actuals -> schedule"),
            PathHop("route_id", "route_stops", "route_id", "schedule -> route stops"),
        ),
        why="Daypart exposure curve per route/corridor.",
    ),
    KeyPath(
        name="POI context: location -> POI",
        start_table="points_of_interest",
        hops=(PathHop("anchor_location_id", "locations", "location_id", "POI -> location"),),
        why="D1 POI pull, distance decay and side-of-road visibility.",
    ),
    KeyPath(
        name="event context: event -> location/zone",
        start_table="events",
        hops=(PathHop("anchor_location_id", "locations", "location_id", "event -> location"),),
        why="Phase 6 event-surge component.",
    ),
    KeyPath(
        name="commercial history: booking -> screen",
        start_table="bookings",
        hops=(PathHop("screen_id", "screens", "screen_id", "booking -> screen"),),
        why="Pricing training data and committed occupancy per screen.",
    ),
    KeyPath(
        name="slot claim: booking -> dim_slot",
        start_table="bookings",
        hops=(PathHop("time_block_id", "dim_slot", "time_block_id", "booking -> time block"),),
        why="How a booking claims inventory in time; defines the sellable unit.",
    ),
    KeyPath(
        name="client: booking -> client",
        start_table="bookings",
        hops=(PathHop("client_id", "client_facts", "client_id", "booking -> client"),),
        why="Client-relationship adjustment in pricing.",
    ),
    KeyPath(
        name="pipeline: lead -> client",
        start_table="lost_leads",
        hops=(PathHop("client_id", "client_facts", "client_id", "lead -> client"),),
        why="Pipeline pressure and win-probability calibration.",
    ),
)


#: Named subsets used by :data:`KEY_PATHS`. Kept as small pure predicates so the
#: static/mobile split is defined once and reused by Phase 3.
SUBSETS: Mapping[str, Any] = {
    "static_screens": lambda frame: frame[frame["location_id"].notna()],
    "mobile_screens": lambda frame: frame[frame["vehicle_id"].notna()],
}


def trace_path(lake: DataLake, path: KeyPath) -> PathTrace:
    """Follow *path* hop by hop, counting how many start rows survive each hop."""
    frame = lake.load(path.start_table)
    if path.subset:
        frame = SUBSETS[path.subset](frame)
    start_rows = len(frame)

    current = frame
    resolved: list[tuple[str, int]] = []
    for index, hop in enumerate(path.hops):
        parent = lake.load(hop.to_table)
        parent_keys = set(parent[hop.to_column].dropna().astype("object"))
        keys = current[hop.from_column].astype("object")
        current = current[keys.isin(parent_keys)]
        # Carry the parent columns needed by the next hop, de-duplicating the
        # parent first so a fan-out edge does not inflate the count.
        next_columns = {hop.to_column}
        remaining = path.hops[index + 1 :]
        if remaining:
            next_columns.add(remaining[0].from_column)
        parent_slim = parent[list(next_columns)].drop_duplicates(subset=[hop.to_column])
        current = current.merge(
            parent_slim,
            left_on=hop.from_column,
            right_on=hop.to_column,
            how="inner",
            suffixes=("", f"__{hop.to_table}"),
        )
        resolved.append((hop.label or hop.to_table, len(current)))

    final_rows = len(current)
    return PathTrace(
        path=path,
        start_rows=start_rows,
        resolved_at_hop=tuple(resolved),
        final_rows=final_rows,
        row_multiplication=0.0 if start_rows == 0 else final_rows / start_rows,
        unresolved_rows=max(start_rows - final_rows, 0),
    )


def trace_all_paths(
    lake: DataLake, paths: Sequence[KeyPath] = KEY_PATHS
) -> tuple[PathTrace, ...]:
    return tuple(trace_path(lake, path) for path in paths)


def paths_frame(traces: Iterable[PathTrace]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "path": trace.path.name,
                "start_table": trace.path.start_table,
                "subset": trace.path.subset or "(all rows)",
                "start_rows": trace.start_rows,
                "resolved_rows": trace.final_rows,
                "resolution_pct": round(trace.resolution_pct, 4),
                "unresolved_rows": trace.unresolved_rows,
                "hops": " → ".join(label for label, _ in trace.resolved_at_hop),
                "why": trace.path.why,
            }
            for trace in traces
        ]
    )


# --------------------------------------------------------------------- diagrams
def mermaid_er(
    checks: Sequence[JoinCheck] = (),
    catalog: Mapping[str, TableSpec] = CATALOG,
) -> str:
    """Mermaid ER diagram of the measured graph, reusable in the C4 component view."""
    by_edge = {(check.child_table, check.child_column, check.parent_table): check for check in checks}
    lines = ["erDiagram"]
    for spec in catalog.values():
        for foreign_key in spec.foreign_keys:
            check = by_edge.get((spec.name, foreign_key.column, foreign_key.parent_table))
            if check is None:
                # Unmeasured edge: draw the declaration, flag it as unverified.
                parent_side, child_side = "||", "o{"
                label = f"{foreign_key.column} (unmeasured)"
            else:
                parent_side = "}o" if check.max_parents_per_child > 1 else "||"
                optional = check.declared_nullable or check.child_null_pct > 0
                if check.max_children_per_parent > 1:
                    child_side = "o{" if optional else "|{"
                else:
                    child_side = "o|" if optional else "||"
                label = f"{foreign_key.column} {check.integrity_pct:.0%}"
            connector = f"{parent_side}--{child_side}"
            lines.append(f"    {foreign_key.parent_table} {connector} {spec.name} : \"{label}\"")
    return "\n".join(lines)


def render_join_section(
    checks: Sequence[JoinCheck],
    traces: Sequence[PathTrace] = (),
) -> str:
    """Markdown for ``docs/data_dictionary.md#join-graph``."""
    lines = [
        "Every edge below was **measured**, not assumed. `integrity` is the share of "
        "non-null child keys that resolve to a parent; `fan-out trap` marks edges where "
        "a naive merge multiplies rows and an explicit aggregation is required.",
        "",
        "### Measured edges",
        "",
        "| Child | Parent | Integrity | Null keys | Cardinality | Fan-out trap | Orphan rows | Status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        lines.append(
            f"| `{check.child_table}.{check.child_column}` "
            f"| `{check.parent_table}.{check.parent_column}` "
            f"| {check.integrity_pct:.2%} "
            f"| {check.child_null_pct:.1%}"
            f"{' (declared nullable)' if check.declared_nullable else ''} "
            f"| {check.cardinality} "
            f"| {'**yes** — aggregate before merging' if check.is_fanout_trap else 'no'} "
            f"| {check.orphan_rows:,} "
            f"| {check.status} |"
        )

    broken = [check for check in checks if check.status == "BROKEN"]
    traps = [check for check in checks if check.is_fanout_trap]
    surprises = [check for check in checks if check.unexpected_nulls]

    if broken:
        lines += ["", "### Integrity failures", ""]
        for check in broken:
            lines.append(
                f"- `{check.edge}` — {check.integrity_pct:.2%} integrity, "
                f"{check.orphan_rows:,} orphan rows across {check.orphan_distinct_keys:,} keys. "
                f"Examples: {', '.join(map(str, check.orphan_examples))}"
            )
    if surprises:
        lines += ["", "### Unexpected nulls (declared non-nullable)", ""]
        for check in surprises:
            lines.append(f"- `{check.edge}` — {check.child_null_pct:.1%} null keys.")
    if traps:
        lines += ["", "### Fan-out traps and their required aggregation", ""]
        for check in traps:
            lines.append(
                f"- `{check.edge}` — up to {check.max_parents_per_child:,} parent rows per child key. "
                + (check.note or "Aggregate the parent to one row per key before merging.")
            )

    if traces:
        lines += [
            "",
            "### Key-path resolution",
            "",
            "| Path | Start rows | Resolved | % | Why it matters |",
            "| --- | --- | --- | --- | --- |",
        ]
        for trace in traces:
            lines.append(
                f"| {trace.path.name} | {trace.start_rows:,} | {trace.final_rows:,} "
                f"| {trace.resolution_pct:.2%} | {trace.path.why} |"
            )

    lines += ["", "### Diagram", "", "```mermaid", mermaid_er(checks), "```", ""]
    return "\n".join(lines)
