"""Regenerate docs/data_dictionary.md from the raw CSVs (Steps 1.1-1.3).

The notebook is for exploration; this is the reproducible path. It performs the same
loading, profiling and join measurement and writes the document, so the dictionary can
never drift from the data.

    python scripts/build_data_dictionary.py [--out docs/data_dictionary.md] [--no-cache]

Exit code is non-zero when a gate fails, which makes it usable as a CI check.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentiq.data import (  # noqa: E402
    KEY_PATHS,
    DataLake,
    ProjectPaths,
    check_all_joins,
    profile_lake,
    render_data_dictionary,
    render_join_section,
    trace_all_paths,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="output markdown path")
    parser.add_argument(
        "--no-cache", action="store_true", help="ignore the parquet mirrors of the large CSVs"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail if any primary key is not unique, any edge is below 99%% integrity, "
        "or any column still lacks a stated meaning",
    )
    args = parser.parse_args(argv)

    paths = ProjectPaths(ROOT).ensure_dirs()
    lake = DataLake(paths.raw_data, cache_dir=paths.cache, use_cache=not args.no_cache)

    print(f"loading {len(lake.catalog)} tables from {paths.raw_data} ...")
    inventory = lake.inventory()
    print(
        f"  {len(inventory)} tables, {inventory['rows'].sum():,} rows, "
        f"{inventory['load_seconds'].sum():.1f}s"
    )

    print("profiling columns ...")
    profiles = profile_lake(lake)

    print("measuring the join graph ...")
    checks = check_all_joins(lake)
    traces = trace_all_paths(lake, KEY_PATHS)

    document = render_data_dictionary(
        profiles,
        join_section=render_join_section(checks, traces),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    target = args.out or (paths.docs / "data_dictionary.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    print(f"wrote {target} ({len(document):,} chars)")

    failures: list[str] = []
    for profile in profiles:
        if profile.primary_key_is_unique is False:
            failures.append(f"{profile.name}: declared primary key is not unique")
    for check in checks:
        if check.integrity_pct < 0.99:
            failures.append(f"{check.edge}: integrity {check.integrity_pct:.2%}")
    todo = sum(len(profile.undocumented_columns) for profile in profiles)
    if todo:
        message = f"{todo} column(s) still marked #TODO-semantics"
        if args.strict:
            failures.append(message)
        else:
            print(f"note: {message}")

    for failure in failures:
        print(f"FAIL  {failure}")
    if failures and args.strict:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
