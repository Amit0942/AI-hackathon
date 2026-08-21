"""Typed, cached loaders for the raw tables (Step 1.1).

Design notes
------------
* **CSV-safe parsing only.** Every read goes through ``pandas.read_csv`` with the
  standard quoting rules, because quoted fields containing commas are expected in
  this dataset. Nothing is ever split positionally.
* **One loader per table, driven by the catalogue.** Adding a table means adding a
  ``TableSpec``, not writing new code.
* **Lazy and memoised.** ``DataLake`` loads a table the first time it is asked for
  and keeps it. The two large tables are mirrored to parquet on first read, so
  later sessions and later phases reload them in a fraction of the time.
* **Engines never see this module.** Later phases depend on repository protocols;
  this is the file-backed implementation behind them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping

import pandas as pd

from . import catalog as catalog_module
from .catalog import CATALOG, TableSpec
from .paths import ProjectPaths

_TRUE_STRINGS = {"true", "t", "yes", "y", "1"}
_FALSE_STRINGS = {"false", "f", "no", "n", "0"}


@dataclass(frozen=True)
class LoadReport:
    """What happened when one table was read — the evidence for the 1.1 exit criteria."""

    table: str
    filename: str
    layer: str
    rows: int
    columns: int
    column_names: tuple[str, ...]
    memory_mb: float
    seconds: float
    source: str  # "csv" or "parquet-cache"

    def as_row(self) -> Mapping[str, object]:
        return {
            "table": self.table,
            "layer": self.layer,
            "file": self.filename,
            "rows": self.rows,
            "columns": self.columns,
            "memory_mb": round(self.memory_mb, 2),
            "load_seconds": round(self.seconds, 2),
            "source": self.source,
            "column_names": ", ".join(self.column_names),
        }


def _coerce_bools(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    """Cast declared boolean columns to pandas' nullable BooleanDtype in place."""
    for column in columns:
        if column not in frame.columns:
            continue
        series = frame[column]
        if pd.api.types.is_bool_dtype(series):
            frame[column] = series.astype("boolean")
            continue
        lowered = series.astype("string").str.strip().str.lower()
        frame[column] = lowered.map(
            lambda value: True
            if value in _TRUE_STRINGS
            else (False if value in _FALSE_STRINGS else pd.NA)
        ).astype("boolean")


def read_table(
    spec: TableSpec,
    raw_dir: Path,
    *,
    usecols: Iterable[str] | None = None,
    nrows: int | None = None,
) -> pd.DataFrame:
    """Read one table's CSV with the typing declared in its :class:`TableSpec`."""
    path = raw_dir / spec.filename
    if not path.is_file():
        raise FileNotFoundError(f"Raw file for table {spec.name!r} not found at {path}")

    requested = set(usecols) if usecols is not None else None

    def wanted(columns: Iterable[str]) -> list[str]:
        return [c for c in columns if requested is None or c in requested]

    dtypes = {column: "category" for column in wanted(spec.category_columns)}
    # Booleans are read as objects and coerced afterwards so that blanks survive
    # as missing values instead of becoming the string "nan".
    dtypes.update({column: "object" for column in wanted(spec.bool_columns)})

    frame = pd.read_csv(
        path,
        dtype=dtypes or None,
        usecols=list(requested) if requested is not None else None,
        parse_dates=wanted(spec.date_columns) or None,
        nrows=nrows,
        keep_default_na=True,
        skipinitialspace=False,
        encoding="utf-8-sig",
    )
    _coerce_bools(frame, wanted(spec.bool_columns))
    return frame


class DataLake:
    """Lazy, memoised access to every raw table.

    >>> lake = DataLake()
    >>> lake["screens"].shape          # doctest: +SKIP
    >>> lake.inventory()               # per-table row/column report  # doctest: +SKIP
    """

    def __init__(
        self,
        raw_dir: Path | str | None = None,
        *,
        cache_dir: Path | str | None = None,
        catalog: Mapping[str, TableSpec] = CATALOG,
        use_cache: bool = True,
    ) -> None:
        paths = ProjectPaths()
        self.raw_dir = Path(raw_dir) if raw_dir is not None else paths.raw_data
        self.cache_dir = Path(cache_dir) if cache_dir is not None else paths.cache
        self.catalog = catalog
        self.use_cache = use_cache
        self._frames: MutableMapping[str, pd.DataFrame] = {}
        self._reports: MutableMapping[str, LoadReport] = {}

    # ---------------------------------------------------------------- internals
    def _cache_path(self, spec: TableSpec) -> Path:
        return self.cache_dir / f"{spec.name}.parquet"

    def _parquet_available(self) -> bool:
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            try:
                import fastparquet  # noqa: F401
            except ImportError:
                return False
        return True

    def _read_with_cache(self, spec: TableSpec) -> tuple[pd.DataFrame, str]:
        if not (spec.large and self.use_cache and self._parquet_available()):
            return read_table(spec, self.raw_dir), "csv"

        cache_path = self._cache_path(spec)
        csv_path = self.raw_dir / spec.filename
        if cache_path.is_file() and cache_path.stat().st_mtime >= csv_path.stat().st_mtime:
            return pd.read_parquet(cache_path), "parquet-cache"

        frame = read_table(spec, self.raw_dir)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cache_path, index=False)
        return frame, "csv"

    # ------------------------------------------------------------------- public
    def load(self, name: str, *, refresh: bool = False) -> pd.DataFrame:
        """Return table *name*, reading it from disk on first use."""
        if refresh:
            self._frames.pop(name, None)
        if name in self._frames:
            return self._frames[name]

        spec = catalog_module.get(name) if name not in self.catalog else self.catalog[name]
        started = time.perf_counter()
        frame, source = self._read_with_cache(spec)
        elapsed = time.perf_counter() - started

        self._frames[name] = frame
        self._reports[name] = LoadReport(
            table=spec.name,
            filename=spec.filename,
            layer=spec.layer,
            rows=len(frame),
            columns=frame.shape[1],
            column_names=tuple(frame.columns),
            memory_mb=frame.memory_usage(deep=True).sum() / 1024**2,
            seconds=elapsed,
            source=source,
        )
        return frame

    def load_all(self, names: Iterable[str] | None = None) -> Mapping[str, pd.DataFrame]:
        return {name: self.load(name) for name in (names or self.catalog)}

    def sample(self, name: str, n: int = 5) -> pd.DataFrame:
        """Read only the first *n* rows — cheap peek that does not populate the cache."""
        spec = self.catalog[name]
        return read_table(spec, self.raw_dir, nrows=n)

    def report(self, name: str) -> LoadReport:
        if name not in self._reports:
            self.load(name)
        return self._reports[name]

    def inventory(self, names: Iterable[str] | None = None) -> pd.DataFrame:
        """One row per table: rows, columns, memory, load time, column list.

        This frame *is* the Step 1.1 exit criterion.
        """
        names = list(names or self.catalog)
        self.load_all(names)
        return pd.DataFrame([self._reports[name].as_row() for name in names])

    @property
    def loaded(self) -> tuple[str, ...]:
        return tuple(self._frames)

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.load(name)

    def __contains__(self, name: str) -> bool:
        return name in self.catalog

    def __iter__(self):
        return iter(self.catalog)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DataLake(raw_dir={self.raw_dir!s}, tables={len(self.catalog)}, "
            f"loaded={len(self._frames)})"
        )
