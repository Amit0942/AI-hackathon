"""Sales-rep performance scoring tests.

This is a simulated layer (no `sales_rep_id` exists in the raw data — see
`domain/rep.py`), so unlike `test_pricing.py`/`test_relevance.py` these
tests do not claim to validate against a measured real-world figure. What
they do validate: the pure scoring math behaves exactly as specified, the
engine composes it correctly, and the requested trade-off (a rep can lose
margin score but recover overall score via target attainment, and vice
versa) actually holds.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.pricing import PriceQuote
from agentiq.domain.rep import RepSale, SalesRep
from agentiq.pricing import PricingEngine
from agentiq.reps import RepScoringEngine
from agentiq.reps.scoring import (
    blend_rep_score,
    is_price_anomaly,
    margin_score,
    target_attainment_ratio,
)
from agentiq.reps.simulate import default_reps, simulate_rep_sales


def _quote(floor: float, target: float, cap: float) -> PriceQuote:
    from agentiq.domain.enums import ColdStartRung, Confidence
    from agentiq.domain.explanation import Explanation

    return PriceQuote(
        screen_id="X",
        time_block_id=1,
        slots=1,
        floor=floor,
        target=target,
        cap=cap,
        recommended=target,
        win_probability_at_recommended=0.5,
        cold_start_rung=ColdStartRung.GLOBAL_RATE_CARD,
        confidence=Confidence.LOW,
        explanation=Explanation(headline="x", confidence=Confidence.LOW, confidence_reason="x"),
    )


def _sale(rep_id: str, sold_price: float, quote: PriceQuote, sold_date: dt.date) -> RepSale:
    return RepSale(
        rep_id=rep_id,
        screen_id="X",
        time_block_id=1,
        slots=1,
        days=10,
        sold_price=sold_price,
        sold_date=sold_date,
        price_quote=quote,
    )


# --------------------------------------------------------------------------- pure functions
def test_margin_score_at_target_is_one() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    assert margin_score(_sale("r", 100.0, quote, dt.date(2026, 1, 1))) == pytest.approx(1.0)


def test_margin_score_at_floor_is_zero() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    assert margin_score(_sale("r", 80.0, quote, dt.date(2026, 1, 1))) == pytest.approx(0.0)


def test_margin_score_midpoint_is_half() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    assert margin_score(_sale("r", 90.0, quote, dt.date(2026, 1, 1))) == pytest.approx(0.5)


def test_margin_score_clamps_above_target_and_below_floor() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    assert margin_score(_sale("r", 120.0, quote, dt.date(2026, 1, 1))) == pytest.approx(1.0)
    assert margin_score(_sale("r", 60.0, quote, dt.date(2026, 1, 1))) == pytest.approx(0.0)


def test_margin_score_handles_zero_width_band() -> None:
    quote = _quote(100.0, 100.0, 100.0)
    assert margin_score(_sale("r", 100.0, quote, dt.date(2026, 1, 1))) == pytest.approx(1.0)
    assert margin_score(_sale("r", 90.0, quote, dt.date(2026, 1, 1))) == pytest.approx(0.0)


def test_is_price_anomaly_flags_outside_band() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    assert is_price_anomaly(_sale("r", 60.0, quote, dt.date(2026, 1, 1))) is True
    assert is_price_anomaly(_sale("r", 130.0, quote, dt.date(2026, 1, 1))) is True
    assert is_price_anomaly(_sale("r", 100.0, quote, dt.date(2026, 1, 1))) is False


def test_target_attainment_ratio_and_zero_target() -> None:
    assert target_attainment_ratio(50_000.0, 100_000.0) == pytest.approx(0.5)
    assert target_attainment_ratio(50_000.0, 0.0) == pytest.approx(0.0)


def test_blend_rep_score_caps_attainment_contribution() -> None:
    # Way over target should score the same as exactly at the cap.
    at_cap = blend_rep_score(1.0, 1.5, attainment_cap=1.5, margin_weight=0.5, attainment_weight=0.5)
    way_over = blend_rep_score(
        1.0, 10.0, attainment_cap=1.5, margin_weight=0.5, attainment_weight=0.5
    )
    assert at_cap == pytest.approx(way_over) == pytest.approx(1.0)


def test_blend_rep_score_requires_positive_cap() -> None:
    with pytest.raises(ValueError):
        blend_rep_score(1.0, 1.0, attainment_cap=0.0, margin_weight=0.5, attainment_weight=0.5)


# --------------------------------------------------------------------------- domain validators
def test_sales_rep_rejects_end_before_start() -> None:
    with pytest.raises(ValueError):
        SalesRep(
            rep_id="r1",
            name="Rep",
            target_revenue=1000.0,
            period_start=dt.date(2026, 2, 1),
            period_end=dt.date(2026, 1, 1),
        )


def test_rep_sale_deal_value_and_discount_pct() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    sale = RepSale(
        rep_id="r1",
        screen_id="X",
        time_block_id=1,
        slots=2,
        days=5,
        sold_price=90.0,
        sold_date=dt.date(2026, 1, 1),
        price_quote=quote,
    )
    assert sale.deal_value == pytest.approx(90.0 * 2 * 5)
    assert sale.discount_vs_target_pct == pytest.approx((100.0 - 90.0) / 100.0)


# --------------------------------------------------------------------------- RepScoringEngine
def test_engine_no_sales_defaults_margin_neutral_and_score_from_attainment_only() -> None:
    rep = SalesRep(
        rep_id="r1",
        name="Rep",
        target_revenue=1000.0,
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 1, 31),
    )
    engine = RepScoringEngine()
    perf = engine.score(rep, ())
    assert perf.sale_count == 0
    assert perf.average_margin_score == pytest.approx(1.0)
    assert perf.target_attainment_pct == pytest.approx(0.0)
    assert perf.rep_score == pytest.approx(engine.config.blend.margin_weight)
    assert "no_sales_this_period_margin_score_defaulted_neutral" in perf.explanation.fallbacks_used


def test_engine_filters_by_rep_id_and_period_window() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    rep = SalesRep(
        rep_id="r1",
        name="Rep",
        target_revenue=100.0,
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 1, 31),
    )
    sales = (
        _sale("r1", 100.0, quote, dt.date(2026, 1, 15)),  # in window
        _sale("r2", 100.0, quote, dt.date(2026, 1, 15)),  # wrong rep
        _sale("r1", 100.0, quote, dt.date(2026, 3, 1)),  # outside window
    )
    engine = RepScoringEngine()
    perf = engine.score(rep, sales)
    assert perf.sale_count == 1


def test_engine_high_discount_high_attainment_can_still_score_moderately() -> None:
    # The requested dynamic: heavy discounting to chase a big target should
    # not crater the score to zero if revenue clears the target.
    quote = _quote(50.0, 100.0, 150.0)
    rep = SalesRep(
        rep_id="r1",
        name="Rep",
        target_revenue=500.0,
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 1, 31),
    )
    # 10 sales at the floor (worst allowed margin) but high volume clears target.
    sales = tuple(
        RepSale(
            rep_id="r1",
            screen_id="X",
            time_block_id=1,
            slots=1,
            days=10,
            sold_price=50.0,
            sold_date=dt.date(2026, 1, 15),
            price_quote=quote,
        )
        for _ in range(10)
    )
    engine = RepScoringEngine()
    perf = engine.score(rep, sales)
    assert perf.average_margin_score == pytest.approx(0.0)
    assert perf.target_attainment_pct > 1.0
    # Margin is zero, so score is exactly the attainment half of the blend.
    assert perf.rep_score == pytest.approx(engine.config.blend.attainment_weight)
    assert perf.rep_score > 0.0


def test_engine_flags_out_of_band_sales_as_anomalies() -> None:
    quote = _quote(80.0, 100.0, 120.0)
    rep = SalesRep(
        rep_id="r1",
        name="Rep",
        target_revenue=100.0,
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 1, 31),
    )
    sale = _sale("r1", 200.0, quote, dt.date(2026, 1, 15))  # way above cap
    engine = RepScoringEngine()
    perf = engine.score(rep, (sale,))
    assert any("priced_outside_floor_cap_band" in f for f in perf.explanation.fallbacks_used)


# ----------------------------------------------------------------- end-to-end (real PriceQuotes)
@pytest.fixture(scope="module")
def repos() -> InMemoryRepositories:
    return InMemoryRepositories()


@pytest.fixture(scope="module")
def pricing_engine(repos: InMemoryRepositories) -> PricingEngine:
    return PricingEngine(repos)


def test_simulated_sales_produce_bounded_scores_against_real_price_quotes(
    repos: InMemoryRepositories, pricing_engine: PricingEngine
) -> None:
    period_start = repos.as_of_date + dt.timedelta(days=30)
    period_end = period_start + dt.timedelta(days=90)
    reps = default_reps(period_start=period_start, period_end=period_end, count=5)
    screens = repos.screens.all()[:100]

    sales = simulate_rep_sales(reps, pricing_engine, screens, sales_per_rep=10)
    assert len(sales) == 5 * 10

    scorer = RepScoringEngine()
    for rep in reps:
        perf = scorer.score(rep, sales)
        assert 0.0 <= perf.rep_score <= 1.0
        assert perf.sale_count == 10
        assert perf.explanation.headline
