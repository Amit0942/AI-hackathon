"""Synthetic rep-sales generator — for demos and tests only.

There is no historical record of what any real rep sold anything for, so
this module exists to make `RepScoringEngine` demoable against **real**
`PriceQuote`s (real screens, real D3 pricing) with a **simulated** rep
identity and negotiation behaviour layered on top. Nothing here should be
read as a reconstruction of real sales history — it is clearly a generator,
named and documented as one.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from agentiq.domain.inventory import Screen
from agentiq.domain.rep import RepSale, SalesRep
from agentiq.pricing import PricingEngine


def simulate_rep_sales(
    reps: tuple[SalesRep, ...],
    pricing_engine: PricingEngine,
    screens: tuple[Screen, ...],
    *,
    sales_per_rep: int = 10,
    seed: int = 0,
) -> tuple[RepSale, ...]:
    """One simulated sale per (rep, sample screen), each priced by the real
    `PricingEngine` and then sold at a rep-specific simulated discount.

    Each rep is assigned one "discount tendency" in `[0, 1]`, drawn once and
    held fixed for all their sales (0 = always closes at `target` or above,
    1 = always closes near `floor`) — this is the stated simulation input
    that stands in for "how hard does this rep negotiate", since no such
    behaviour is measured anywhere in the raw data.
    """
    rng = random.Random(seed)
    sales: list[RepSale] = []

    for rep in reps:
        tendency = rng.random()
        sample_screens = rng.sample(screens, min(sales_per_rep, len(screens)))
        for screen in sample_screens:
            time_block_id = rng.randint(1, 6)
            slots = rng.randint(1, 3)
            days = rng.randint(7, 30)
            sold_date = rep.period_start + timedelta(
                days=rng.randint(0, max((rep.period_end - rep.period_start).days, 0))
            )
            quote = pricing_engine.price(screen, time_block_id, slots, sold_date)

            jitter = rng.uniform(0.9, 1.1)
            raw_price = quote.target - tendency * (quote.target - quote.floor) * jitter
            sold_price = max(quote.floor * 0.95, min(raw_price, quote.cap))

            sales.append(
                RepSale(
                    rep_id=rep.rep_id,
                    screen_id=screen.screen_id,
                    time_block_id=time_block_id,
                    slots=slots,
                    days=days,
                    sold_price=round(sold_price, 2),
                    sold_date=sold_date,
                    price_quote=quote,
                )
            )

    return tuple(sales)


def default_reps(*, period_start: date, period_end: date, count: int = 5) -> tuple[SalesRep, ...]:
    """A small roster of synthetic reps with varied targets, for a quick demo."""
    targets = [40_000.0, 60_000.0, 80_000.0, 100_000.0, 150_000.0]
    return tuple(
        SalesRep(
            rep_id=f"REP-{i + 1:03d}",
            name=f"Rep {i + 1}",
            target_revenue=targets[i % len(targets)],
            period_start=period_start,
            period_end=period_end,
        )
        for i in range(count)
    )


__all__ = ["default_reps", "simulate_rep_sales"]
