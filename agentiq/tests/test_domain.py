"""Step 2.1/2.2 exit criteria: domain types are immutable, validated, and their
cross-field invariants raise at construction — never trusted to the caller."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentiq.domain import (
    ColdStartRung,
    Confidence,
    Explanation,
    Package,
    PackageLine,
    PriceQuote,
    ReachEstimate,
    Screen,
    ScreenSize,
    ScreenType,
    merge_confidence,
)


def _explanation(confidence: Confidence = Confidence.HIGH) -> Explanation:
    return Explanation(headline="test", confidence=confidence, confidence_reason="fixture")


# --------------------------------------------------------------------------- Screen
def test_screen_requires_exactly_one_of_location_or_vehicle() -> None:
    with pytest.raises(ValidationError):
        Screen(
            screen_id="X",
            city_id="LH",
            screen_type=ScreenType.METRO_STATION,
            screen_size=ScreenSize.L,
        )
    with pytest.raises(ValidationError):
        Screen(
            screen_id="X",
            city_id="LH",
            screen_type=ScreenType.METRO_STATION,
            screen_size=ScreenSize.L,
            location_id="L1",
            vehicle_id="V1",
        )


def test_screen_type_must_agree_with_static_mobile_split() -> None:
    with pytest.raises(ValidationError):
        Screen(
            screen_id="X",
            city_id="LH",
            screen_type=ScreenType.BUS,  # mobile
            screen_size=ScreenSize.S,
            location_id="L1",  # but given a location, not a vehicle
        )


def test_screen_is_frozen() -> None:
    screen = Screen(
        screen_id="X",
        city_id="LH",
        screen_type=ScreenType.BUS,
        screen_size=ScreenSize.S,
        vehicle_id="V1",
    )
    with pytest.raises(ValidationError):
        screen.city_id = "ACS"  # type: ignore[misc]


# --------------------------------------------------------------------------- Explanation
def test_contribution_direction_must_match_magnitude_sign() -> None:
    from agentiq.domain import Contribution

    with pytest.raises(ValidationError):
        Contribution(signal="s", direction="positive", weight=0.5, magnitude=-1.0)
    with pytest.raises(ValidationError):
        Contribution(signal="s", direction="negative", weight=0.5, magnitude=1.0)
    with pytest.raises(ValidationError):
        Contribution(signal="s", direction="neutral", weight=0.5, magnitude=1.0)

    # valid cases do not raise
    Contribution(signal="s", direction="positive", weight=0.5, magnitude=1.0)
    Contribution(signal="s", direction="negative", weight=0.5, magnitude=-1.0)
    Contribution(signal="s", direction="neutral", weight=0.0, magnitude=0.0)


def test_merge_confidence_returns_weakest_link() -> None:
    assert merge_confidence(Confidence.HIGH, Confidence.LOW, Confidence.MEDIUM) == Confidence.LOW
    assert merge_confidence(Confidence.HIGH, Confidence.HIGH) == Confidence.HIGH
    with pytest.raises(ValueError):
        merge_confidence()


# --------------------------------------------------------------------------- PriceQuote
def _price_quote(**overrides) -> PriceQuote:
    defaults = dict(
        screen_id="X",
        time_block_id=1,
        slots=1,
        floor=40.0,
        target=55.0,
        cap=70.0,
        recommended=58.0,
        win_probability_at_recommended=0.6,
        cold_start_rung=ColdStartRung.SCREEN_OWN_HISTORY,
        confidence=Confidence.HIGH,
        explanation=_explanation(),
    )
    defaults.update(overrides)
    return PriceQuote(**defaults)


def test_price_band_ordering_enforced() -> None:
    _price_quote()  # valid, does not raise
    with pytest.raises(ValidationError):
        _price_quote(floor=60.0, target=55.0, cap=70.0)
    with pytest.raises(ValidationError):
        _price_quote(floor=40.0, target=55.0, cap=50.0)


def test_recommended_price_must_be_inside_band() -> None:
    with pytest.raises(ValidationError):
        _price_quote(recommended=100.0)
    with pytest.raises(ValidationError):
        _price_quote(recommended=10.0)


def test_total_for_slots() -> None:
    quote = _price_quote(slots=3, recommended=50.0)
    assert quote.total_for_slots == 150.0


# --------------------------------------------------------------------------- ReachEstimate
def test_unique_reach_cannot_exceed_gross_impressions() -> None:
    ReachEstimate(
        gross_impressions=100, unique_reach=80, frequency=1.25, explanation=_explanation()
    )
    with pytest.raises(ValidationError):
        ReachEstimate(
            gross_impressions=50, unique_reach=80, frequency=0.6, explanation=_explanation()
        )


# --------------------------------------------------------------------------- Package
def _package_line(confidence: Confidence) -> PackageLine:
    import datetime as dt

    return PackageLine(
        screen_id="X",
        time_block_id=1,
        slots=1,
        start_date=dt.date(2026, 9, 1),
        end_date=dt.date(2026, 9, 10),
        price_quote=_price_quote(confidence=confidence),
        relevance_score=0.8,
    )


def test_package_line_rejects_inverted_date_range() -> None:
    import datetime as dt

    with pytest.raises(ValidationError):
        PackageLine(
            screen_id="X",
            time_block_id=1,
            slots=1,
            start_date=dt.date(2026, 9, 10),
            end_date=dt.date(2026, 9, 1),
            price_quote=_price_quote(),
            relevance_score=0.8,
        )


def test_package_confidence_is_weakest_link_of_its_lines() -> None:
    package = Package(
        package_id="P1",
        brief_id="B1",
        label="max-reach",
        lines=(_package_line(Confidence.HIGH), _package_line(Confidence.LOW)),
        reach=ReachEstimate(
            gross_impressions=100, unique_reach=90, frequency=1.1, explanation=_explanation()
        ),
        total_budget_used=100.0,
        optimizer_strategy="greedy-submodular",
        explanation=_explanation(),
    )
    assert package.confidence == Confidence.LOW
    assert len(package.screen_ids) == 1  # both lines share screen_id "X"
