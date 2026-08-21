"""Regenerate docs/results/1.4_inventory_shape.md from the raw CSVs (Step 1.4).

    python scripts/build_inventory_report.py [--out PATH] [--strict]

--strict fails when a Step 1.4 invariant breaks: the capacity model is not validated
by the sweep line, the as-of boundary is ambiguous, or bookings.daypart disagrees
with dim_slot. Usable as a CI check.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentiq.data import DataLake, ProjectPaths  # noqa: E402
from agentiq.data.inventory import profile_inventory  # noqa: E402
from agentiq.data.inventory_report import render_inventory_report  # noqa: E402

DEFAULT_OUT = Path("docs") / "results" / "1.4_inventory_shape.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    paths = ProjectPaths(ROOT).ensure_dirs()
    lake = DataLake(paths.raw_data, cache_dir=paths.cache)

    print("measuring inventory shape ...")
    shape = profile_inventory(lake)
    print(
        f"  {shape.units.network['screens']:,} screens, "
        f"{shape.capacity.blocks_per_day} blocks x {shape.capacity.slots_per_block} slots, "
        f"as-of {shape.as_of.date.date()}, horizon {shape.units.horizon_days} days"
    )
    print(
        f"  {shape.units.network['slot_units_horizon']:,} slot-units over the horizon; "
        f"{shape.units.network['available_slot_units']:,} still available"
    )

    document = render_inventory_report(
        shape, generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )
    target = args.out or (ROOT / DEFAULT_OUT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    print(f"wrote {target} ({len(document):,} chars)")

    failures: list[str] = []
    if not shape.capacity.is_validated:
        failures.append(
            f"capacity model not validated: peak "
            f"{shape.capacity.peak_concurrent_slots_observed} slots, "
            f"{shape.capacity.units_ever_oversold} units oversold"
        )
    if not shape.as_of.is_unambiguous:
        failures.append("as-of date boundary is ambiguous — settled/committed windows overlap")
    if shape.daypart_mismatches:
        failures.append(
            f"{shape.daypart_mismatches} bookings.daypart rows disagree with dim_slot"
        )

    for failure in failures:
        print(f"FAIL  {failure}")
    if failures and args.strict:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
