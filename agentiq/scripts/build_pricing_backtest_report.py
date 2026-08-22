"""Regenerate docs/results/6.3_pricing_backtest.md — Step 6's exit criterion,
surfaced somewhere visible (`backtest.py`'s math existed with no report to
show it).

    python scripts/build_pricing_backtest_report.py [--out PATH] [--strict]

--strict fails if network-wide band coverage drops below 80% or any
per-cohort backtest cannot be run (too few rows) — usable as a CI check.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentiq.data.repositories import InMemoryRepositories  # noqa: E402
from agentiq.pricing import load_price_band_config  # noqa: E402
from agentiq.pricing.backtest import BacktestResult, run_backtest  # noqa: E402
from agentiq.pricing.base_rate import join_screen_attributes  # noqa: E402

DEFAULT_OUT = Path("docs") / "results" / "6.3_pricing_backtest.md"
MIN_ACCEPTABLE_COVERAGE = 0.80


def _cohort_table(rows: list[tuple[str, str, BacktestResult]]) -> str:
    lines = [
        "| city | screen_type | n_test | band coverage | below floor | above cap | "
        "target MAPE | median band width |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for city_id, screen_type, result in rows:
        lines.append(
            f"| {city_id} | {screen_type} | {result.n_test:,} | "
            f"{result.band_coverage:.1%} | {result.below_floor:.1%} | {result.above_cap:.1%} | "
            f"{result.mape:.1%} | {result.median_band_width_pct:.1%} |"
        )
    return "\n".join(lines)


def render_report(
    overall: BacktestResult,
    cohorts: list[tuple[str, str, BacktestResult]],
    *,
    generated_at: str,
) -> str:
    return f"""# Step 6.3/6 exit criterion — Pricing band back-test

> **Generated file — do not edit by hand.** Regenerate with
> `python scripts/build_pricing_backtest_report.py`.
> Generated {generated_at} against the real settled-booking data
> (`agentiq.pricing.backtest.run_backtest`).

**Purpose.** The plan's Phase 6 exit criteria require a measured answer to
the problem statement's "no one knows if the price is right" (§1): what
share of realised prices actually fall inside our `[floor, cap]` band, and
how far off is `target` from what the market actually paid. This is that
measurement, made visible as a committed document rather than a function
nobody calls.

**What this does *not* claim**: band coverage alone rewards a wide, useless
band (a $0-$1M band scores 100%). Median band width is reported alongside
coverage for exactly this reason — both must be read together, never
coverage alone.

## 1. Network-wide result

```
{overall.summary()}
```

## 2. Per-cohort breakdown (city x screen_type)

The network-wide number can hide cohorts where the band works far better or
worse than average. Same train/test split and method, computed independently
per `(city_id, screen_type)` cohort:

{_cohort_table(cohorts)}

## 3. Reading this

- **Band coverage** — the fraction of held-out realised prices landing
  inside `[floor, cap]`. This is a *floor* on what the live engine achieves,
  not a ceiling: the demand multiplier is held neutral here (Step 6.1's
  index needs contemporaneous occupancy that a held-out historical line's
  own booking would leak into if reconstructed — see `backtest.py`'s
  docstring), so the live `PricingEngine.price()` band is at least this
  tight, usually tighter.
- **Below floor / above cap** are reported separately because they mean
  opposite things commercially: below-floor means the guardrail would have
  rejected a deal the market actually accepted (lost revenue risk); above-cap
  means a real price exceeded what the guardrail thought was defensible
  (margin-protection risk).
- **Target MAPE** — how far the band's `target` (not `recommended`) sits from
  the realised price, on average.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    print("loading repositories ...")
    repos = InMemoryRepositories()
    config, _half_life = load_price_band_config()

    screens_frame = repos.lake["screens"]
    settled = join_screen_attributes(repos.bookings.settled(), screens_frame)
    print(f"  {len(settled):,} settled, screen-attributed booking lines")

    print("running network-wide back-test ...")
    overall = run_backtest(settled, config)
    print(f"  {overall.summary()}")

    print("running per-cohort back-tests (city x screen_type) ...")
    cohorts: list[tuple[str, str, BacktestResult]] = []
    failures: list[str] = []
    for (city_id, screen_type), group in settled.groupby(
        ["city_id", "screen_type"], observed=True
    ):
        try:
            result = run_backtest(group, config)
        except ValueError as exc:
            failures.append(f"{city_id}/{screen_type}: {exc}")
            continue
        cohorts.append((city_id, str(screen_type), result))
        print(f"  {city_id}/{screen_type}: coverage {result.band_coverage:.1%}")

    document = render_report(
        overall, cohorts, generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    )
    target = args.out or (ROOT / DEFAULT_OUT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    print(f"wrote {target} ({len(document):,} chars)")

    if overall.band_coverage < MIN_ACCEPTABLE_COVERAGE:
        failures.append(
            f"network-wide band coverage {overall.band_coverage:.1%} below "
            f"{MIN_ACCEPTABLE_COVERAGE:.0%} threshold"
        )

    for failure in failures:
        print(f"FAIL  {failure}")
    if failures and args.strict:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
