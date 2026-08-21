"""Phase 6 exit criteria — back-test the price band on held-out settled bookings.

The plan's Phase 6 exit criteria (solution_plan.md §6) require, beyond the
property tests: *"Back-test on held-out settled bookings — report band
coverage (what % of realised prices fall inside our band) and target-vs-realised
error."*

Band coverage is the single number that answers the problem statement's
"no one knows if the price is right" (§1). A guardrail nobody has measured is
just a different invented number; coverage is the evidence that the floor and
cap bracket what the market actually paid.

**Split policy.** The split is *random over settled lines*, not temporal.
Step 1.4 §1.1 fixes the as-of date at 2026-08-19 and defines `completed` as
everything ending on or before it, so there is no future data to leak into:
the whole settled set is historical by construction. A temporal split would
additionally measure drift over the 2025-08 -> 2026-08 window, which is a
different question from "does the band bracket realised prices" — and would
confound coverage with seasonality. The random split is seeded so the reported
numbers are reproducible.

**What is *not* claimed.** Coverage measures whether realised prices land
inside the band, not whether the band is *tight*. A band from $0 to $1M would
score 100% coverage and be useless, so `BacktestResult` reports median band
width alongside coverage; both must be read together.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from agentiq.pricing.bands import PriceBandConfig, compute_cap, compute_floor, compute_target
from agentiq.pricing.base_rate import TARGET_COLUMN, fit_base_rate_model

#: Share of settled lines held out for evaluation.
DEFAULT_TEST_SIZE = 0.2

#: Seed for the train/test split, so reported figures are reproducible.
DEFAULT_RANDOM_STATE = 0


@dataclass(frozen=True)
class BacktestResult:
    """Measured band quality on held-out settled bookings."""

    n_train: int
    n_test: int
    #: Share of held-out realised prices falling within [floor, cap].
    band_coverage: float
    #: Share falling below floor / above cap — the two failure directions,
    #: reported separately because they mean opposite things commercially.
    below_floor: float
    above_cap: float
    #: Target-vs-realised error on the held-out set.
    mape: float
    median_abs_error: float
    #: Median (cap - floor) / target — the tightness figure that stops a
    #: wide, useless band from scoring well on coverage alone.
    median_band_width_pct: float

    def summary(self) -> str:
        return (
            f"Band back-test on {self.n_test:,} held-out settled lines "
            f"(fit on {self.n_train:,}):\n"
            f"  band coverage      : {self.band_coverage:.1%} "
            f"(below floor {self.below_floor:.1%}, above cap {self.above_cap:.1%})\n"
            f"  median band width  : {self.median_band_width_pct:.1%} of target\n"
            f"  target MAPE        : {self.mape:.1%}\n"
            f"  median abs error   : ${self.median_abs_error:.2f}/slot/day"
        )


def run_backtest(
    settled_bookings: pd.DataFrame,
    config: PriceBandConfig,
    *,
    test_size: float = DEFAULT_TEST_SIZE,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> BacktestResult:
    """Fit the base rate on a train split and measure band quality on the held-out rest.

    *settled_bookings* must already be `completed`-only with screen attributes
    joined (`join_screen_attributes`) — the same frame `PricingEngine` fits on.

    The demand multiplier is held at a neutral 1.0 here deliberately. Step
    6.1's demand index is computed per screen x block x *date*, and a held-out
    historical line's contemporaneous demand is not reconstructible from the
    as-of occupancy snapshot without leaking its own booking into the
    occupancy it would have faced. Holding it neutral measures the base rate
    and guardrails on their own, which is what the exit criterion asks about;
    it means coverage here is a *floor* on what the full engine achieves, not
    a ceiling.
    """
    frame = settled_bookings.dropna(subset=[TARGET_COLUMN]).copy()
    rng = np.random.default_rng(random_state)
    mask = rng.random(len(frame)) >= test_size
    train, test = frame.loc[mask], frame.loc[~mask]

    if len(train) < 100 or len(test) < 100:
        raise ValueError(
            f"Back-test needs a meaningful split; got {len(train)} train / {len(test)} test rows."
        )

    model = fit_base_rate_model(train)

    # Floors are computed **per cohort**, mirroring the online path. On a
    # live request `compute_floor` sees only the comparable rows the
    # cold-start ladder selected for that screen, never the whole network; a
    # single global percentile would be a different (and much weaker)
    # guardrail than the one actually shipped. It matters: the network-wide
    # 10th percentile is $39.73, but per city x screen_type the 10th
    # percentiles span $23-$60 against medians of $42-$100, so one global
    # floor sits above some cohorts' realised prices and far below others'.
    #
    # `city_id x screen_type` is the cohort used here because it is the
    # coarsest ladder rung that still applies to every row
    # (`CITY_SCREEN_TYPE_BASELINE`), so the measurement is a conservative
    # stand-in for the finer rungs a real request usually reaches.
    cohort_keys = ["city_id", "screen_type"]
    floor_by_cohort: dict[tuple, float] = {}
    for key, group in train.groupby(cohort_keys, observed=True):
        try:
            floor_by_cohort[key] = compute_floor(group, config)
        except ValueError:  # no priced rows in this cohort
            continue
    global_floor = compute_floor(train, config)

    realised = test[TARGET_COLUMN].to_numpy(dtype=float)
    base_rates = np.array([model.predict_one(row) for _, row in test.iterrows()])

    # Same defensive guard the online path applies (bands.build_price_quote).
    median_train = float(train[TARGET_COLUMN].median())
    base_rates = np.where(
        (base_rates <= 0) | (base_rates > median_train * 3), median_train, base_rates
    )

    test_keys = list(zip(*(test[col] for col in cohort_keys), strict=True))
    raw_floors = np.array([floor_by_cohort.get(k, global_floor) for k in test_keys])

    targets = np.array([compute_target(b, 1.0, config) for b in base_rates])
    caps = np.array([compute_cap(b, config) for b in base_rates])
    floors = np.minimum(raw_floors, targets)
    caps = np.maximum(caps, targets)

    inside = (realised >= floors) & (realised <= caps)
    below = realised < floors
    above = realised > caps

    abs_error = np.abs(targets - realised)
    return BacktestResult(
        n_train=len(train),
        n_test=len(test),
        band_coverage=float(inside.mean()),
        below_floor=float(below.mean()),
        above_cap=float(above.mean()),
        mape=float(np.mean(abs_error / realised)),
        median_abs_error=float(np.median(abs_error)),
        median_band_width_pct=float(np.median((caps - floors) / targets)),
    )
