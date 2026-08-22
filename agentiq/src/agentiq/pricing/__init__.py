"""D3 — Demand Forecasting & Pricing Model (Phase 6).

Steps 6.1 (demand intensity index), 6.3 (price band), 6.5 (cold-start
ladder), and 6.4 (win-probability recommended price) are built. This pass
adds the last two: 6.2 (expected-footfall forecast, `forecast_footfall`) and
6.6 (human-in-the-loop overrides, `apply_overrides`) — see
`docs/decisions/0003-d3-pricing-scope.md` for the original deferral
reasoning. Public entrypoint: `PricingEngine`, which takes a `Screen` and
returns a `PriceQuote` (`.price()`), a `FootfallForecast` (`.forecast_footfall()`),
or an overridden `PriceQuote` (`.apply_overrides()`) — every one with a full
`Explanation`, ready for Phase 7's optimizer or direct use.

The engine depends only on repository protocols (`agentiq.data.repositories`)
and raw config, never on file paths or ad hoc pandas loading — Phase 6 code
that needs a new data slice adds a repository method, not an inline CSV read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import yaml

from agentiq.audience import AudienceProfileEngine
from agentiq.data.occupancy import occupancy_events
from agentiq.data.paths import ProjectPaths
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.enums import ColdStartRung, IndustryVertical
from agentiq.domain.inventory import Screen
from agentiq.domain.pricing import DemandSignal, FootfallForecast, PriceQuote
from agentiq.pricing.bands import PriceBandConfig, build_price_quote, select_cold_start_rung
from agentiq.pricing.base_rate import (
    FittedBaseRateModel,
    fit_base_rate_model,
    join_screen_attributes,
)
from agentiq.pricing.demand import DemandIndexInputs, compute_demand_signal
from agentiq.pricing.footfall import forecast_footfall
from agentiq.pricing.overrides import (
    HumanOverrideConfig,
    apply_human_overrides,
    load_human_override_config,
)
from agentiq.pricing.win_probability import (
    UNKNOWN_TIER,
    FittedWinModel,
    TradeOffPoint,
    fit_win_model,
    trade_off_curve,
)

__all__ = [
    "UNKNOWN_TIER",
    "DemandIndexInputs",
    "DemandSignal",
    "FittedBaseRateModel",
    "FittedWinModel",
    "FootfallForecast",
    "HumanOverrideConfig",
    "PriceBandConfig",
    "PriceQuote",
    "PricingEngine",
    "TradeOffPoint",
    "compute_demand_signal",
    "fit_base_rate_model",
    "fit_win_model",
    "load_human_override_config",
    "load_price_band_config",
    "trade_off_curve",
]

_DAYPART_BY_TIME_BLOCK: dict[int, str] = {
    1: "night",
    2: "morning",
    3: "midday",
    4: "afternoon",
    5: "evening",
    6: "night",
}


def load_price_band_config(config_path: str | None = None) -> tuple[PriceBandConfig, float]:
    """Read `config/pricing.yaml` into a `PriceBandConfig` plus the recency half-life.

    Never hardcode these values in engine code (CLAUDE.md: "config over
    code") — this is the one place the YAML is parsed.
    """
    path = ProjectPaths().config / "pricing.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    band = raw["price_band"]
    multiplier = raw["demand_multiplier"]
    config = PriceBandConfig(
        floor_percentile=float(band["floor_percentile"]),
        margin_floor_pct=float(band["margin_floor_pct"]),
        cap_gap_pct_vs_client_target=float(band["cap_gap_pct_vs_client_target"]),
        cap_gap_pct_vs_base_rate=float(band["cap_gap_pct_vs_base_rate"]),
        max_uplift_pct=float(multiplier["max_uplift_pct"]),
        max_discount_pct=float(multiplier["max_discount_pct"]),
    )
    half_life_days = float(raw["recency_decay"]["half_life_days"])
    return config, half_life_days


def _load_footfall_std_dev_multiplier(config_path: str | None = None) -> float:
    path = ProjectPaths().config / "pricing.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return float(raw["footfall_forecast"]["std_dev_multiplier"])


def _load_holiday_ridership_multiplier(config_path: str | None = None) -> float:
    path = ProjectPaths().config / "pricing.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return float(raw["footfall_forecast"]["holiday_ridership_multiplier"])


@dataclass
class _CohortIndex:
    """Screen-ID sets for the two cohort-based ladder rungs, built once per engine instance."""

    peer_by_location_or_vehicle: dict[str, tuple[str, ...]]
    cohort_by_zone_type_position_size: dict[tuple, tuple[str, ...]]


def _build_cohort_index(
    screens: tuple[Screen, ...],
    repos: InMemoryRepositories,
) -> _CohortIndex:
    """Group screens by location/vehicle and by (zone, type, position, size) — Step 6.5 rungs 2-3."""
    by_location_or_vehicle: dict[str, list[str]] = {}
    by_cohort: dict[tuple, list[str]] = {}

    for screen in screens:
        anchor = screen.location_id if screen.is_static else screen.vehicle_id
        by_location_or_vehicle.setdefault(anchor, []).append(screen.screen_id)

        zone = None
        if screen.is_static and screen.location_id is not None:
            zone_row = repos.geography.zone_for_location(screen.location_id)
            zone = zone_row["zone_id"] if zone_row is not None else None
        cohort_key = (zone, screen.screen_type, screen.position, screen.screen_size)
        by_cohort.setdefault(cohort_key, []).append(screen.screen_id)

    return _CohortIndex(
        peer_by_location_or_vehicle={k: tuple(v) for k, v in by_location_or_vehicle.items()},
        cohort_by_zone_type_position_size={k: tuple(v) for k, v in by_cohort.items()},
    )


class PricingEngine:
    """D3 entrypoint — fits the base-rate model once, then prices any screen-slot cheaply.

    Fitting (base rate + cohort index) is the offline precompute (design
    principle 5); `price()` is the online per-request lookup + band
    construction, so repeated calls do not re-fit a regression each time.
    """

    def __init__(
        self,
        repos: InMemoryRepositories,
        *,
        config: PriceBandConfig | None = None,
        recency_half_life_days: float | None = None,
        audience_engine: AudienceProfileEngine | None = None,
        human_override_config: HumanOverrideConfig | None = None,
        footfall_std_dev_multiplier: float | None = None,
        holiday_ridership_multiplier: float | None = None,
    ) -> None:
        self.repos = repos
        loaded_config, loaded_half_life = load_price_band_config()
        self.config = config or loaded_config
        self.recency_half_life_days = recency_half_life_days or loaded_half_life
        # Step 6.2 now depends on D1 directly (unlike segment_heat's optional
        # IndustryVertical, D1 exists today) — default-construct one if the
        # caller doesn't already have one to share.
        self.audience_engine = audience_engine or AudienceProfileEngine(repos)
        self.human_override_config = human_override_config or load_human_override_config()
        self.footfall_std_dev_multiplier = (
            footfall_std_dev_multiplier
            if footfall_std_dev_multiplier is not None
            else _load_footfall_std_dev_multiplier()
        )
        self.holiday_ridership_multiplier = (
            holiday_ridership_multiplier
            if holiday_ridership_multiplier is not None
            else _load_holiday_ridership_multiplier()
        )

        self._screens = repos.screens.all()
        screens_frame = repos.lake["screens"]
        self._settled = join_screen_attributes(repos.bookings.settled(), screens_frame)
        self._occupancy = occupancy_events(repos.bookings.committed())
        self._cohorts = _build_cohort_index(self._screens, repos)
        self._base_rate_model = fit_base_rate_model(self._settled)
        # Step 6.4: fit once at construction, alongside the base rate — both
        # are offline precompute, so `price()` stays a cheap lookup.
        self._win_model = fit_win_model(repos.leads.all(), repos.clients.all())

    def price(
        self,
        screen: Screen,
        time_block_id: int,
        slots: int,
        on_date: date,
        *,
        industry_vertical: IndustryVertical | None = None,
        client_target_price: float | None = None,
        competitor_mentioned: bool = False,
        client_tier: str = UNKNOWN_TIER,
    ) -> PriceQuote:
        """Return a floor/target/cap + recommended `PriceQuote` for one screen-slot.

        The three client-context arguments are all optional (ADR-0003
        decisions 6 and 8): D3 must stay independently callable before D2/D5
        exist to supply brief context. Supplying `client_target_price` is what
        makes the price gap mean exactly what `lost_leads.price_gap_pct`
        means; without it the band target substitutes and the quote's
        `Explanation.fallbacks_used` records the substitution.
        """
        cohort_screen_ids: dict[ColdStartRung, tuple[str, ...]] = {
            ColdStartRung.PEER_SCREENS_SAME_LOCATION_OR_CORRIDOR: self._cohorts.peer_by_location_or_vehicle.get(
                screen.location_id if screen.is_static else screen.vehicle_id, ()
            ),
            ColdStartRung.COHORT_ZONE_TYPE_POSITION_SIZE: self._cohort_ids_for(screen),
        }
        rung, comparable_rows = select_cold_start_rung(screen, self._settled, cohort_screen_ids)

        open_leads = self.repos.leads.as_of(on_date)
        active_events = self.repos.context.events_active(screen.city_id, on_date, on_date)
        demand_inputs = DemandIndexInputs(
            settled_bookings=self._settled,
            occupancy_timeline=self._occupancy,
            open_leads=open_leads,
            active_events=active_events,
            time_block_daypart=_DAYPART_BY_TIME_BLOCK[time_block_id],
            city_id=screen.city_id,
            industry_vertical=industry_vertical,
            recency_half_life_days=self.recency_half_life_days,
        )
        demand_signal = compute_demand_signal(screen.screen_id, time_block_id, on_date, demand_inputs)

        fitted_model = self._base_rate_model if rung is not ColdStartRung.GLOBAL_RATE_CARD else None
        return build_price_quote(
            screen=screen,
            time_block_id=time_block_id,
            slots=slots,
            demand_signal=demand_signal,
            rung=rung,
            comparable_rows=comparable_rows,
            config=self.config,
            fitted_model=fitted_model,
            win_model=self._win_model,
            client_target_price=client_target_price,
            competitor_mentioned=competitor_mentioned,
            client_tier=client_tier,
        )

    def discount_trade_off(
        self,
        quote: PriceQuote,
        *,
        client_target_price: float | None = None,
        competitor_mentioned: bool = False,
        client_tier: str = UNKNOWN_TIER,
    ) -> tuple[TradeOffPoint, ...]:
        """The Step 6.4 trade-off curve behind an already-built quote.

        Step 6.4 asks for the recommendation to be shown *with* the curve, so
        a rep can see the cost of discounting rather than only the final
        number. Kept off `PriceQuote` itself (which is a frozen domain value
        that Phase 7 passes around in bulk) and offered here on demand, so a
        thousand-quote optimiser run does not carry a thousand 101-point
        curves it will never read.
        """
        reference = client_target_price if client_target_price is not None else quote.target
        return trade_off_curve(
            self._win_model,
            floor=quote.floor,
            cap=quote.cap,
            reference_price=reference,
            competitor_mentioned=competitor_mentioned,
            client_tier=client_tier,
        )

    def price_for_client(
        self,
        client_id: str,
        screen: Screen,
        time_block_id: int,
        slots: int,
        on_date: date,
        *,
        client_target_price: float | None = None,
        competitor_mentioned: bool = False,
    ) -> PriceQuote:
        """`.price()`, but resolving `client_tier` and `industry_vertical` from
        `client_facts` automatically instead of requiring the caller to
        already know them.

        Before this method existed, nothing in the codebase actually called
        `.price()` with a real `client_tier`/`industry_vertical` sourced from
        `client_facts` — both silently defaulted to neutral unless a caller
        happened to already have the values on hand. `negotiation_leverage`
        is deliberately **not** used here: measured against real settled
        bookings (`docs/decisions/1.9_client_segmentation.md`), high-leverage
        clients paid *more*, not less, in the same city/screen-type cohort —
        the opposite of the naive assumption, and confounded with client size
        rather than a clean causal effect. Building a price adjustment on it
        without controlling for that confound would risk a backwards rule,
        so none is built.
        """
        row = self.repos.clients.get(client_id)
        if row is None:
            raise ValueError(f"Unknown client_id {client_id!r}")

        return self.price(
            screen,
            time_block_id,
            slots,
            on_date,
            industry_vertical=IndustryVertical(row["industry"]),
            client_target_price=client_target_price,
            competitor_mentioned=competitor_mentioned,
            client_tier=str(row["client_tier"]),
        )

    def forecast_footfall(
        self,
        screen: Screen,
        time_block_id: int,
        start_date: date,
        end_date: date,
    ) -> FootfallForecast:
        """Step 6.2 — expected audience exposure over a future campaign window.

        Independent of `.price()`: a rep-facing number shown alongside a
        quote, not an input `build_price_quote` currently consumes.
        """
        return forecast_footfall(
            screen,
            time_block_id,
            start_date,
            end_date,
            self.repos,
            self.audience_engine,
            std_dev_multiplier=self.footfall_std_dev_multiplier,
            holiday_ridership_multiplier=self.holiday_ridership_multiplier,
        )

    def apply_overrides(
        self,
        quote: PriceQuote,
        overrides: dict[str, float | str],
        *,
        model_expected_footfall: float | None = None,
    ) -> PriceQuote:
        """Step 6.6 — apply rep-supplied overrides to an already-built `PriceQuote`.

        *model_expected_footfall* lets a caller pass `forecast_footfall(...)
        .expected_daily_footfall` as the baseline an `expected_footfall`
        override is compared against; without it, that override is logged
        but has no effect (`fallbacks_used` says so explicitly).
        """
        return apply_human_overrides(
            quote,
            overrides,
            config=self.human_override_config,
            price_band_config=self.config,
            model_expected_footfall=model_expected_footfall,
        )

    def _cohort_ids_for(self, screen: Screen) -> tuple[str, ...]:
        zone = None
        if screen.is_static and screen.location_id is not None:
            zone_row = self.repos.geography.zone_for_location(screen.location_id)
            zone = zone_row["zone_id"] if zone_row is not None else None
        key = (zone, screen.screen_type, screen.position, screen.screen_size)
        return self._cohorts.cohort_by_zone_type_position_size.get(key, ())
