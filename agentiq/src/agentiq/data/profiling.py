"""Column- and table-level profiling, and data-dictionary rendering (Step 1.2).

The dictionary is *generated*, never hand-maintained, so it cannot drift from the
data. Human knowledge lives in ``catalog.py`` (grain, keys, column notes) and is
merged into the generated output. Any column with no note is emitted with a
``#TODO-semantics`` marker, which is the checklist for the Step 1.9 review gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from .catalog import CATALOG, LAYERS, TableSpec
from .loaders import DataLake

TODO_MARKER = "#TODO-semantics"


@dataclass(frozen=True)
class ColumnProfile:
    table: str
    column: str
    dtype: str
    kind: str  # numeric | datetime | boolean | categorical
    rows: int
    non_null: int
    null_pct: float
    n_unique: int
    unique_pct: float
    minimum: Any = None
    maximum: Any = None
    mean: float | None = None
    std: float | None = None
    p50: float | None = None
    top_values: tuple[tuple[Any, int], ...] = ()
    note: str = ""

    @property
    def has_note(self) -> bool:
        return bool(self.note.strip())

    def as_row(self) -> Mapping[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "dtype": self.dtype,
            "kind": self.kind,
            "non_null": self.non_null,
            "null_pct": round(self.null_pct, 4),
            "n_unique": self.n_unique,
            "unique_pct": round(self.unique_pct, 4),
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "p50": self.p50,
            "top_values": _format_top_values(self.top_values),
            "note": self.note or TODO_MARKER,
        }


@dataclass(frozen=True)
class TableProfile:
    name: str
    layer: str
    grain: str
    description: str
    rows: int
    columns: int
    memory_mb: float
    primary_key: tuple[str, ...]
    primary_key_is_unique: bool | None
    primary_key_nulls: int | None
    duplicate_rows: int
    column_profiles: tuple[ColumnProfile, ...] = field(default_factory=tuple)

    @property
    def undocumented_columns(self) -> tuple[str, ...]:
        return tuple(p.column for p in self.column_profiles if not p.has_note)

    def as_row(self) -> Mapping[str, Any]:
        return {
            "table": self.name,
            "layer": self.layer,
            "rows": self.rows,
            "columns": self.columns,
            "memory_mb": round(self.memory_mb, 2),
            "primary_key": " + ".join(self.primary_key) or "(none declared)",
            "pk_unique": self.primary_key_is_unique,
            "pk_nulls": self.primary_key_nulls,
            "duplicate_rows": self.duplicate_rows,
            "undocumented_columns": len(self.undocumented_columns),
            "grain": self.grain,
        }


def _format_top_values(top: Sequence[tuple[Any, int]], limit: int = 10) -> str:
    return "; ".join(f"{value!s} ({count:,})" for value, count in list(top)[:limit])


def _classify(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series) or isinstance(series.dtype, pd.BooleanDtype):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    return "categorical"


def profile_column(
    series: pd.Series,
    *,
    table: str,
    note: str = "",
    top_n: int = 10,
) -> ColumnProfile:
    rows = len(series)
    non_null = int(series.notna().sum())
    kind = _classify(series)
    n_unique = int(series.nunique(dropna=True))

    minimum = maximum = mean = std = p50 = None
    top: tuple[tuple[Any, int], ...] = ()

    if kind == "numeric":
        described = series.dropna()
        if not described.empty:
            minimum, maximum = described.min(), described.max()
            mean, std, p50 = float(described.mean()), float(described.std()), float(described.median())
    elif kind == "datetime":
        described = series.dropna()
        if not described.empty:
            minimum, maximum = described.min(), described.max()
    else:
        counts = series.value_counts(dropna=True).head(top_n)
        top = tuple((index, int(value)) for index, value in counts.items())
        if kind == "boolean" and non_null:
            minimum, maximum = False, True

    return ColumnProfile(
        table=table,
        column=str(series.name),
        dtype=str(series.dtype),
        kind=kind,
        rows=rows,
        non_null=non_null,
        null_pct=0.0 if rows == 0 else 1 - non_null / rows,
        n_unique=n_unique,
        unique_pct=0.0 if non_null == 0 else n_unique / non_null,
        minimum=minimum,
        maximum=maximum,
        mean=mean,
        std=std,
        p50=p50,
        top_values=top,
        note=note,
    )


def profile_table(frame: pd.DataFrame, spec: TableSpec, *, top_n: int = 10) -> TableProfile:
    present_pk = [column for column in spec.primary_key if column in frame.columns]
    pk_unique: bool | None = None
    pk_nulls: int | None = None
    if present_pk and len(present_pk) == len(spec.primary_key):
        pk_unique = not frame.duplicated(subset=present_pk).any()
        pk_nulls = int(frame[present_pk].isna().any(axis=1).sum())

    profiles = tuple(
        profile_column(
            frame[column],
            table=spec.name,
            note=spec.column_notes.get(column, ""),
            top_n=top_n,
        )
        for column in frame.columns
    )

    return TableProfile(
        name=spec.name,
        layer=spec.layer,
        grain=spec.grain,
        description=spec.description,
        rows=len(frame),
        columns=frame.shape[1],
        memory_mb=frame.memory_usage(deep=True).sum() / 1024**2,
        primary_key=spec.primary_key,
        primary_key_is_unique=pk_unique,
        primary_key_nulls=pk_nulls,
        duplicate_rows=int(frame.duplicated().sum()),
        column_profiles=profiles,
    )


def profile_lake(
    lake: DataLake,
    *,
    names: Iterable[str] | None = None,
    top_n: int = 10,
) -> tuple[TableProfile, ...]:
    return tuple(
        profile_table(lake.load(name), lake.catalog[name], top_n=top_n)
        for name in (names or lake.catalog)
    )


# ------------------------------------------------------------------- dataframes
def tables_frame(profiles: Iterable[TableProfile]) -> pd.DataFrame:
    return pd.DataFrame([profile.as_row() for profile in profiles])


def columns_frame(profiles: Iterable[TableProfile]) -> pd.DataFrame:
    return pd.DataFrame(
        [column.as_row() for profile in profiles for column in profile.column_profiles]
    )


# ---------------------------------------------------------------------- markdown
def _md_row(cells: Sequence[Any]) -> str:
    return "| " + " | ".join("" if cell is None else str(cell) for cell in cells) + " |"


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:,.4g}"
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def render_data_dictionary(
    profiles: Sequence[TableProfile],
    *,
    join_section: str = "",
    dq_section: str = "",
    generated_at: str | None = None,
) -> str:
    """Render the full ``docs/data_dictionary.md`` body from measured profiles."""
    total_rows = sum(profile.rows for profile in profiles)
    todo_total = sum(len(profile.undocumented_columns) for profile in profiles)
    by_name = {profile.name: profile for profile in profiles}

    lines: list[str] = [
        "# Data Dictionary — Urban Media Datasets",
        "",
        "> **Generated file — do not edit by hand.** Regenerate with "
        "`python scripts/build_data_dictionary.py`.",
        f"> Every figure below is measured from the raw CSVs"
        + (f" ({generated_at})." if generated_at else "."),
        "",
        f"**Tables:** {len(profiles)} · **Total rows:** {total_rows:,} · "
        f"**Columns awaiting a stated meaning:** {todo_total}",
        "",
        "## Contents",
        "",
    ]
    for layer in LAYERS:
        in_layer = [p.name for p in profiles if p.layer == layer]
        if in_layer:
            links = ", ".join(f"[`{name}`](#{name})" for name in in_layer)
            lines.append(f"- **{layer.title()}** — {links}")
    lines += ["", "## Table summary", ""]

    header = ["Table", "Layer", "Rows", "Cols", "Primary key", "PK unique", "Dupe rows", "Grain"]
    lines.append(_md_row(header))
    lines.append(_md_row(["---"] * len(header)))
    for layer in LAYERS:
        for profile in (p for p in profiles if p.layer == layer):
            lines.append(
                _md_row(
                    [
                        f"[`{profile.name}`](#{profile.name})",
                        profile.layer,
                        f"{profile.rows:,}",
                        profile.columns,
                        " + ".join(profile.primary_key) or "—",
                        {True: "yes", False: "**NO**", None: "n/a"}[profile.primary_key_is_unique],
                        f"{profile.duplicate_rows:,}",
                        profile.grain,
                    ]
                )
            )

    lines += ["", "## Tables", ""]
    for layer in LAYERS:
        for profile in (by_name[p.name] for p in profiles if p.layer == layer):
            lines += _render_table_section(profile)

    if join_section:
        lines += ["", "## Join graph", "", join_section.rstrip(), ""]
    if dq_section:
        lines += ["", "## DQ register", "", dq_section.rstrip(), ""]

    lines += [
        "",
        "## Open semantics",
        "",
        f"{todo_total} column(s) still carry `{TODO_MARKER}`. Each must be resolved "
        "before Phase 3 by adding a `column_notes` entry in "
        "`src/agentiq/data/catalog.py` and regenerating this file.",
        "",
    ]
    for profile in profiles:
        if profile.undocumented_columns:
            lines.append(
                f"- `{profile.name}`: " + ", ".join(f"`{c}`" for c in profile.undocumented_columns)
            )
    return "\n".join(lines) + "\n"


def _render_table_section(profile: TableProfile) -> list[str]:
    lines = [
        f'<a id="{profile.name}"></a>',
        "",
        f"### `{profile.name}`",
        "",
        f"*Layer:* **{profile.layer}** · *Rows:* **{profile.rows:,}** · "
        f"*Columns:* **{profile.columns}** · *Memory:* {profile.memory_mb:,.1f} MB",
        "",
        f"**Grain.** {profile.grain}",
        "",
    ]
    if profile.description:
        lines += [f"**Role.** {profile.description}", ""]
    if profile.primary_key:
        verdict = {
            True: "verified unique",
            False: "**NOT unique — investigate**",
            None: "not verifiable (column missing)",
        }[profile.primary_key_is_unique]
        nulls = "—" if profile.primary_key_nulls is None else f"{profile.primary_key_nulls:,}"
        lines += [
            f"**Primary key.** `{' + '.join(profile.primary_key)}` — {verdict}; "
            f"nulls in key: {nulls}; exact duplicate rows: {profile.duplicate_rows:,}",
            "",
        ]

    header = ["Column", "Dtype", "Null %", "Distinct", "Min / Max", "Mean", "Top values", "Meaning"]
    lines += [_md_row(header), _md_row(["---"] * len(header))]
    for column in profile.column_profiles:
        span = (
            f"{_fmt(column.minimum)} / {_fmt(column.maximum)}"
            if column.minimum is not None or column.maximum is not None
            else "—"
        )
        lines.append(
            _md_row(
                [
                    f"`{column.column}`",
                    column.dtype,
                    f"{column.null_pct:.1%}",
                    f"{column.n_unique:,}",
                    span,
                    _fmt(column.mean),
                    _format_top_values(column.top_values, limit=6) or "—",
                    column.note or TODO_MARKER,
                ]
            )
        )
    lines.append("")
    return lines


def build_data_dictionary(
    lake: DataLake | None = None,
    *,
    join_section: str = "",
    generated_at: str | None = None,
) -> tuple[str, tuple[TableProfile, ...]]:
    """Convenience entry point used by both the notebook and the CLI script."""
    lake = lake or DataLake()
    profiles = profile_lake(lake, names=CATALOG)
    return render_data_dictionary(
        profiles, join_section=join_section, generated_at=generated_at
    ), profiles
