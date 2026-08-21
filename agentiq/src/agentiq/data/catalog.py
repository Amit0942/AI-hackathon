"""Declarative catalogue of the 14 raw Urban Media tables (Step 1.1).

This is the single place where a table's file name, grain, primary key, foreign
keys and per-column typing hints live. Loaders, the profiler, the join-graph
checker and every later phase read from here, so a schema fact is stated once.

Important: the ``grain``, ``primary_key`` and ``foreign_keys`` entries are
*hypotheses declared from the column names*. They are not trusted — Step 1.2
tests every primary key for uniqueness and Step 1.3 measures the referential
integrity and fan-out of every foreign key. A declaration that measurement
contradicts is a catalogue bug: fix it here and re-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Mapping, Sequence

#: The five conceptual layers used throughout the plan and the C4 component view.
LAYERS: tuple[str, ...] = ("geography", "network", "inventory", "context", "commercial")


@dataclass(frozen=True)
class ForeignKey:
    """A declared child -> parent relationship, to be verified by measurement."""

    column: str
    parent_table: str
    parent_column: str
    nullable: bool = False
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.column} -> {self.parent_table}.{self.parent_column}"


@dataclass(frozen=True)
class TableSpec:
    """Everything the pipeline needs to know about one raw CSV."""

    name: str
    filename: str
    layer: str
    grain: str
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    date_columns: tuple[str, ...] = ()
    bool_columns: tuple[str, ...] = ()
    category_columns: tuple[str, ...] = ()
    #: Read via a parquet cache because the CSV is large enough for reload cost to matter.
    large: bool = False
    description: str = ""
    column_notes: Mapping[str, str] = field(default_factory=dict)

    def parent_tables(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(fk.parent_table for fk in self.foreign_keys))


_SPECS: tuple[TableSpec, ...] = (
    # ------------------------------------------------------------------ geography
    TableSpec(
        name="cities",
        filename="cities.csv",
        layer="geography",
        grain="One row per city in the network.",
        primary_key=("city_id",),
        category_columns=("transit_density", "market_tier", "timezone"),
        description="Top of the geography hierarchy; market tier is a candidate price driver.",
        column_notes={
            "city_id": "Short city code (LH / ACS / DAT). Prefix of every other id in the city.",
            "city_name": "Display name of the city. Never a join key — use city_id.",
            "population": "Total city population. Scale reference only; audience maths uses zone figures.",
            "market_tier": "premium / standard / value. One city per tier, so this is the city-level "
            "price-tier lever and the base of the pricing ladder's top rung.",
            "transit_density": "dense / mixed / sprawling. Shapes how much of the audience is transit-borne.",
            "timezone": "IANA zone, one per city. All daypart and slot reasoning must be in local time.",
        },
    ),
    TableSpec(
        name="zone_demographics",
        filename="zone_demographics.csv",
        layer="geography",
        grain="One row per city zone.",
        primary_key=("zone_id",),
        foreign_keys=(ForeignKey("city_id", "cities", "city_id"),),
        category_columns=("dominant_occupation",),
        description="Resident base and daytime multiplier per zone — the D1 demographic backbone.",
        column_notes={
            "zone_id": "Zone key, '<CITY>-ZONE-nnn'. 10 zones per city, 30 in total.",
            "city_id": "Owning city.",
            "zone_name": "Display name, unique across the network. Matches locations.city_zone.",
            "resident_population": "Residents living in the zone — the night-time base, not the audience.",
            "population_density_per_sqkm": "Residents per km2. Proxy for how compressed footfall is.",
            "median_age": "Median resident age. Coarse audience-fit signal; the pct_* bands are sharper.",
            "pct_age_under_18": "Share of residents under 18. Rarely an ad target; useful as a dilution signal.",
            "pct_age_18_34": "Share aged 18-34. Maps to the young-adult target bands the briefs request.",
            "pct_age_35_54": "Share aged 35-54. Maps to the professional/upgrader target bands.",
            "pct_age_55_plus": "Share aged 55+. Completes the age mix (the four bands sum to ~100).",
            "median_household_income": "Absolute income in local currency. income_index is the comparable form.",
            "income_index": "Affluence indexed to the network (100 = average). Feeds premium-audience affinity.",
            "pct_bachelor_or_higher": "Education share; correlates with white-collar and premium segments.",
            "dominant_occupation": "mixed / white_collar / blue_collar / retail_service / student. The single "
            "strongest categorical discriminator between zones for audience labelling.",
            "daytime_population_multiplier": "Daytime population / residents. The bridge from residents to "
            "actual audience — a 3.4x business district behaves nothing like a 1.0x suburb. Key D1 input.",
        },
    ),
    TableSpec(
        name="locations",
        filename="locations.csv",
        layer="geography",
        grain="One row per physical location (stop / station / roadside point).",
        primary_key=("location_id",),
        foreign_keys=(
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey("zone_id", "zone_demographics", "zone_id"),
        ),
        category_columns=("location_type",),
        description="Anchor of the static-geography path screen -> location -> zone -> city.",
        column_notes={
            "location_id": "Location key, '<CITY>-LOC-nnnn'. 910 locations across the three cities.",
            "city_id": "Owning city.",
            "name": "Street-intersection or station name. Display only — never match on it.",
            "city_zone": "Denormalised zone name; zone_id is the join key. Both are always populated.",
            "zone_id": "Zone the location sits in — the hop that gives a static screen its demographics.",
            "location_type": "bus_stop (719) or metro_station (191). Determines dwell time: a platform "
            "holds a waiting audience for minutes, a bus stop for far less.",
        },
    ),
    # -------------------------------------------------------------------- network
    TableSpec(
        name="route_stops",
        filename="route_stops.csv",
        layer="network",
        grain="One row per (route, stop_sequence) — a route's ordered stop list.",
        primary_key=("route_id", "stop_sequence"),
        foreign_keys=(
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey("location_id", "locations", "location_id"),
        ),
        bool_columns=("is_first_stop", "is_last_stop"),
        category_columns=("mode", "direction"),
        description="Path a vehicle-mounted screen traverses; source of corridor identity.",
        column_notes={
            "route_id": "Directional route key, '<CITY>-RT-<code>-<IN|OUT>'.",
            "corridor_id": "Directionless route family (the route_id without the direction suffix). "
            "Vehicles attach to a corridor, not to a route — this is the mobile-audience unit.",
            "city_id": "Owning city.",
            "route_name": "Display name of the route (e.g. 'Route B1').",
            "mode": "bus (1,660 stop rows) or metro (776). Sets which vehicle_type serves the route.",
            "direction": "inbound / outbound, perfectly balanced. The two directions of one corridor "
            "share an audience, so de-duplicate across them in the overlap graph.",
            "stop_sequence": "1-based position of the stop along the route; second half of the primary key.",
            "location_id": "The physical location served — the join that ties a route to POIs and zones.",
            "is_first_stop": "True at stop_sequence 1. Terminus flag, useful for dwell assumptions.",
            "is_last_stop": "True at the final stop.",
            "num_stops": "Denormalised stop count for the route (8-21). Sanity-check value only.",
        },
    ),
    TableSpec(
        name="route_schedules",
        filename="route_schedules.csv",
        layer="network",
        grain="One row per scheduled trip (route x day_type x departure time).",
        primary_key=("schedule_id",),
        foreign_keys=(
            ForeignKey(
                "route_id",
                "route_stops",
                "route_id",
                note="Parent key is non-unique (route_stops is per stop); expect high fan-out.",
            ),
        ),
        category_columns=("direction", "day_type"),
        description="Trip frequency by day type — the exposure multiplier for mobile screens.",
        column_notes={
            "schedule_id": "Trip key, '<CITY>-SCH-nnnnnn'. One row per scheduled departure.",
            "route_id": "Directional route the trip runs on.",
            "corridor_id": "Denormalised corridor of that route.",
            "direction": "inbound / outbound; redundant with the route_id suffix.",
            "day_type": "weekday (13,052) or weekend (6,786). The only calendar dimension of the "
            "schedule — weekday/weekend service levels differ and briefs ask for weekend weighting.",
            "start_time": "HH:MM departure in local city time. Bucket into dim_slot to get the time block.",
            "estimated_ridership": "Planned riders for the trip. Compare with ridership_actuals to "
            "measure how much the schedule under- or over-states real exposure.",
        },
    ),
    TableSpec(
        name="ridership_actuals",
        filename="ridership_actuals.csv",
        layer="network",
        grain="One row per (scheduled trip, date) with realised ridership.",
        primary_key=("schedule_id", "date"),
        foreign_keys=(
            ForeignKey("schedule_id", "route_schedules", "schedule_id"),
            ForeignKey("city_id", "cities", "city_id"),
        ),
        date_columns=("date",),
        bool_columns=("is_holiday",),
        category_columns=("day_of_week",),
        large=True,
        description="Realised exposure volume; source of the normalised daypart curve (Step 1.6).",
        column_notes={
            "schedule_id": "The scheduled trip this observation belongs to.",
            "route_id": "Denormalised route of that trip.",
            "city_id": "Owning city.",
            "date": "Calendar date of the observation. Spans 2026-02-19 to 2026-08-19 — six months, "
            "which is narrower than the bookings span, so exposure must be seasonally extrapolated.",
            "day_of_week": "Weekday name. Weekday trips appear on all five weekdays; weekend trips only "
            "Sat/Sun — so day_type in route_schedules and this column must agree.",
            "is_holiday": "True on holidays (~1% of rows). Holiday days behave like weekends; keep them "
            "out of the weekday baseline curve.",
            "actual_ridership": "Realised riders on the trip (2-734, median 129). The exposure numerator "
            "for every mobile screen and for transit throughput at a stop.",
        },
    ),
    TableSpec(
        name="vehicles",
        filename="vehicles.csv",
        layer="network",
        grain="One row per vehicle carrying screens.",
        primary_key=("vehicle_id",),
        foreign_keys=(
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey(
                "corridor_id",
                "route_stops",
                "corridor_id",
                note="Parent key is non-unique; a corridor spans many route_stops rows.",
            ),
        ),
        category_columns=("vehicle_type",),
        description="Links a mobile screen to the corridor whose audience it is exposed to.",
        column_notes={
            "vehicle_id": "Vehicle key, '<CITY>-VEH-nnnnn'.",
            "city_id": "Owning city.",
            "vehicle_type": "metro_train (449) or bus (405). Decides whether a screen's audience is "
            "captive riders in a coach or street-facing passers-by.",
            "corridor_id": "The corridor the vehicle is assigned to — the mobile screen's exposure path.",
            "screen_count": "Screens fitted to the vehicle (2-4). Cross-check against the screens table.",
        },
    ),
    # ------------------------------------------------------------------ inventory
    TableSpec(
        name="screens",
        filename="screens.csv",
        layer="inventory",
        grain="One row per physical screen — the unit that is sold.",
        primary_key=("screen_id",),
        foreign_keys=(
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey(
                "location_id",
                "locations",
                "location_id",
                nullable=True,
                note="Null for vehicle-mounted screens.",
            ),
            ForeignKey(
                "vehicle_id",
                "vehicles",
                "vehicle_id",
                nullable=True,
                note="Null for static screens.",
            ),
        ),
        category_columns=("screen_type", "position", "screen_size"),
        description=(
            "The inventory spine. location_id XOR vehicle_id decides static vs mobile, "
            "which decides which D1 exposure model applies."
        ),
        column_notes={
            "screen_id": "Screen key, '<CITY>-SCR-nnnnnn'. The sellable asset; 11,163 in total.",
            "city_id": "Owning city.",
            "screen_type": "metro_station (6,391) / bus_stop (2,157) / metro_rail_coach (1,400) / bus "
            "(1,215). The first two are static, the last two vehicle-mounted — a measured 1:1 match "
            "with the location_id / vehicle_id split, so screen_type alone identifies the D1 model.",
            "location_id": "Set for the 8,548 static screens (76.6%), null for mobile ones.",
            "vehicle_id": "Set for the 2,615 mobile screens (23.4%), null for static ones. Exactly one "
            "of location_id / vehicle_id is populated on every row — verified, not assumed.",
            "position": "platform / entrance_exit / left / right / top / back. Null on all 1,400 "
            "metro_rail_coach screens (interior coach panels have no mount face). Drives visibility "
            "and the interior-captive vs exterior-passer-by audience distinction.",
            "screen_size": "S / M / L, roughly evenly split. Candidate price driver — test in Step 1.5.",
        },
    ),
    TableSpec(
        name="dim_slot",
        filename="dim_slot.csv",
        layer="inventory",
        grain="One row per sellable time block of the day.",
        primary_key=("time_block_id",),
        category_columns=("time_block_label", "nearest_daypart"),
        description="The time dimension of a sellable unit (screen x time block x slot x date).",
        column_notes={
            "time_block_id": "1-6. Six four-hour blocks cover the full day with no gaps or overlaps.",
            "time_block_label": "'HH:MM-HH:MM' display form of the block.",
            "start_hour": "Inclusive start hour, local time (0, 4, 8, 12, 16, 20).",
            "end_hour": "Exclusive end hour (4, 8, 12, 16, 20, 24).",
            "nearest_daypart": "night / morning / midday / afternoon / evening. Note night maps to two "
            "blocks (1 and 6), so daypart is NOT a key — always aggregate by time_block_id.",
        },
    ),
    # -------------------------------------------------------------------- context
    TableSpec(
        name="points_of_interest",
        filename="points_of_interest.csv",
        layer="context",
        grain="One row per POI, already anchored to its nearest location.",
        primary_key=("poi_id",),
        foreign_keys=(
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey("anchor_location_id", "locations", "location_id"),
        ),
        bool_columns=("is_network_hub",),
        category_columns=("poi_type", "scale", "side_of_road", "peak_daypart"),
        description="Footfall pull and environment character around a location (D1 POI signal).",
        column_notes={
            "poi_id": "POI key, '<CITY>-POI-nnnn'.",
            "city_id": "Owning city.",
            "city_zone": "Zone name the POI sits in; may differ from the anchor location's zone.",
            "name": "Display name of the POI.",
            "poi_type": "13 values — shopping_mall, grocery_anchor, office_park, residential_tower, "
            "entertainment_district, government_building, hospital, corporate_campus, university, "
            "hotel_convention, museum, tourist_landmark, stadium_arena. This is the vocabulary "
            "the briefs' environment language (mall entry, campus edge, nightlife) must resolve onto.",
            "scale": "neighborhood / minor / major / flagship. Ordinal weight on the POI's pull; use "
            "alongside est_daily_footfall rather than instead of it.",
            "est_daily_footfall": "Estimated daily visitors. The magnitude of the pull — cap any single "
            "POI's contribution so one flagship cannot dominate a screen's profile.",
            "anchor_location_id": "Nearest network location. Proximity is pre-computed for us, so POI "
            "context is a join plus a distance filter, not a geospatial search.",
            "distance_to_location_km": "Distance to that location in km. Distance-decay input; the "
            "radius cut-off that actually carries signal is validated in Step 1.6.",
            "distance_to_location_mi": "The same distance in miles. Redundant — use the km column.",
            "is_network_hub": "True where the POI is itself a transit interchange-scale hub (~46%).",
            "side_of_road": "near_side / far_side. A far-side POI is weaker visibility evidence: the "
            "audience is across the road from the screen.",
            "peak_daypart": "Daypart when the POI's footfall peaks — aligns POI pull with the time block "
            "being sold rather than smearing it across the day.",
        },
    ),
    TableSpec(
        name="events",
        filename="events.csv",
        layer="context",
        grain="One row per event occurrence with its impact window.",
        primary_key=("event_id",),
        foreign_keys=(
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey("poi_id", "points_of_interest", "poi_id", nullable=True),
            ForeignKey("anchor_location_id", "locations", "location_id", nullable=True),
        ),
        date_columns=("start_date", "end_date"),
        category_columns=(
            "event_type",
            "recurrence",
            "attendance_tier",
            "primary_impact_daypart",
        ),
        description="Temporal demand surges — raw material for the Phase 6 event-surge component.",
        column_notes={
            "event_id": "Event key, '<CITY>-EVT-nnnnn'.",
            "city_id": "Owning city.",
            "city_zone": "Zone the event takes place in.",
            "poi_id": "Host POI where one applies; null for 23% of events (street events, parades).",
            "anchor_location_id": "Nearest network location — the geographic anchor for the surge.",
            "event_name": "Display name of the event.",
            "event_type": "10 values: sports_game, concert, festival, community_fair, parade, "
            "convention, trade_show, holiday_event, political_rally, marathon_race. Type predicts the "
            "audience the surge brings, not just its size.",
            "recurrence": "one_time (264) / weekly_season (82) / annual (21). weekly_season rows must be "
            "expanded across their season before they can be matched to a campaign window.",
            "start_date": "First day of the event. Span 2025-08 to 2027-02, covering the booking window.",
            "end_date": "Last day; equals start_date for single-day events.",
            "expected_attendance": "Headcount estimate — the magnitude of the demand surge.",
            "attendance_tier": "small / medium / large. Banded form of expected_attendance; use the tier "
            "for the surge multiplier so a single outlier cannot distort pricing.",
            "primary_impact_daypart": "Daypart the surge lands in — restricts the uplift to the time "
            "blocks actually affected instead of the whole day.",
            "impact_radius_km": "Radius over which the surge is felt. Combined with POI/location "
            "distances, this is what joins an event to the screens it should uplift.",
        },
    ),
    # ----------------------------------------------------------------- commercial
    TableSpec(
        name="client_facts",
        filename="client_facts.csv",
        layer="commercial",
        grain="One row per client account.",
        primary_key=("client_id",),
        foreign_keys=(ForeignKey("home_city_id", "cities", "city_id"),),
        date_columns=("relationship_start_date",),
        category_columns=(
            "industry",
            "client_tier",
            "campaign_frequency",
            "bundle_affinity",
            "negotiation_leverage",
            "account_status",
        ),
        description="Client context for the relationship adjustment in pricing (Step 6.3).",
        column_notes={
            "client_id": "Client key, 'CLI-nnnnn'. 520 accounts.",
            "company_name": "Display name of the client.",
            "industry": "Client's vertical, drawn from the same 13-value set as bookings.industry_vertical.",
            "client_tier": "local_business (294) / regional_chain (149) / national_chain (77). Size of "
            "the account; a pricing and leverage input, not an audience one.",
            "home_city_id": "City the account is based in; may differ from where it buys.",
            "active_cities": "Pipe-delimited city codes ('ACS|LH|DAT'). Must be split before joining — "
            "and the order varies, so treat it as a set, never as a string to match.",
            "preferred_geographies": "Pipe-delimited '<CITY>:<Zone name>' pairs (243 distinct values). "
            "Parse into (city_id, zone_name) tuples; the zone name joins to zone_demographics.zone_name.",
            "typical_campaign_budget": "The account's usual spend. Prior for a brief with no stated budget.",
            "budget_variance_pct": "How much that budget typically moves — the width of the prior.",
            "campaign_frequency": "one_off / seasonal / quarterly / always_on. How often the account buys; "
            "an always_on client is worth more over the year than one deal suggests.",
            "avg_campaign_duration_days": "Typical flight length for the account.",
            "bundle_affinity": "single_screen (277) / moderate_bundle (160) / heavy_bundle (83). Prior on "
            "whether this client will accept a multi-screen package.",
            "negotiation_leverage": "low (262) / medium (180) / high (78). Direct input to the "
            "win-probability model and the client-relationship price adjustment (Steps 6.3-6.4).",
            "relationship_start_date": "First date of the relationship; tenure is a discount justification.",
            "account_status": "active (465) or lapsed (55). Lapsed accounts should not set current demand.",
        },
    ),
    TableSpec(
        name="bookings",
        filename="bookings.csv",
        layer="commercial",
        grain=(
            "One row per booking line item: a screen x time block held for a date range. "
            "Occupancy needs the booking-expansion transform (Step 1.5)."
        ),
        primary_key=("booking_id",),
        foreign_keys=(
            ForeignKey("client_id", "client_facts", "client_id"),
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey("screen_id", "screens", "screen_id"),
            ForeignKey("time_block_id", "dim_slot", "time_block_id"),
        ),
        date_columns=("start_date", "end_date", "booked_date"),
        bool_columns=("is_bundle",),
        category_columns=(
            "ad_type",
            "industry_vertical",
            "campaign_objective",
            "daypart",
            "rotation_type",
            "booking_status",
        ),
        large=True,
        description=(
            "Realised commercial history and committed future occupancy. Only settled rows "
            "are training data; future-dated rows are occupancy, a different input."
        ),
        column_notes={
            "booking_id": "Line-item key, '<CITY>-BKG-nnnnnnn'. 191,109 lines.",
            "deal_id": "Groups line items into one negotiated deal — the 'bundle is one deal' key. "
            "56,762 deals; the 55,485 non-bundle lines are one deal each, while 135,624 bundled lines "
            "belong to only 1,277 deals (~106 lines per bundle). Bundles dominate value and must be "
            "priced jointly, never line by line.",
            "client_id": "Buying account.",
            "city_id": "City of the booked screen.",
            "screen_id": "The booked screen. 9,939 of 11,163 screens (89%) appear at least once.",
            "ad_type": "Free-text creative/campaign name with the objective in parentheses. High "
            "cardinality — use campaign_objective and industry_vertical for modelling, not this.",
            "industry_vertical": "13 values (auto, cpg, education, entertainment, finance, government, "
            "healthcare, hospitality, nonprofit, real_estate, retail, technology, telecom). Segment-heat "
            "demand signal and the target of the brief-vertical taxonomy mapping.",
            "campaign_objective": "awareness / conversion / frequency / reach. Only four values, and the "
            "briefs state objectives in prose — so taxonomy.yaml must map onto exactly these.",
            "time_block_id": "The four-hour block bought; joins to dim_slot.",
            "daypart": "Denormalised dim_slot.nearest_daypart for that block. Redundant, and lossy for "
            "night (blocks 1 and 6 both map to it).",
            "slots_booked_per_day": "Rotation slots claimed per day, 1-6 (median 2). The quantity axis of "
            "the sellable unit and where price non-linearity must be tested.",
            "rotation_type": "partial_rotation (93,532) / single_rotation (64,728) / full_exclusivity "
            "(32,849). Categorical view of the same intensity as slots_booked_per_day — check they agree.",
            "start_date": "First day of the flight. Span 2025-08-19 to 2027-02-21, so the table holds "
            "both settled history and future commitments.",
            "end_date": "Last day of the flight, inclusive.",
            "duration_days": "Flight length, 2-180 days (median 63). Should equal end-start+1.",
            "booked_date": "When the deal was signed. The only column safe for time-ordered validation: "
            "splitting on start_date leaks future information into training.",
            "contracted_price_per_slot_per_day": "The price target variable, already normalised per slot "
            "per day — model this, not line_item_value.",
            "line_item_value": "Realised value of this line (~price x slots x days).",
            "deal_total_value": "Value of the whole deal, repeated on every line. Summing it over lines "
            "multiplies bundle revenue ~106-fold — always de-duplicate by deal_id first.",
            "is_bundle": "True on the 135,624 lines belonging to a multi-screen deal.",
            "booking_status": "completed (111,727) / active (29,954) / upcoming (49,428). Only completed "
            "is training data; active and upcoming are committed occupancy, a different input entirely.",
        },
    ),
    TableSpec(
        name="lost_leads",
        filename="lost_leads.csv",
        layer="commercial",
        grain="One row per lost lead / failed negotiation.",
        primary_key=("lead_id",),
        foreign_keys=(
            ForeignKey("client_id", "client_facts", "client_id", nullable=True),
            ForeignKey("city_id", "cities", "city_id"),
            ForeignKey("anchor_screen_id", "screens", "screen_id", nullable=True),
        ),
        date_columns=("lead_date", "lost_date", "requested_start_date"),
        bool_columns=("competitor_mentioned",),
        category_columns=(
            "industry_vertical",
            "lead_source",
            "sales_stage_reached",
            "loss_reason",
            "campaign_objective",
            "ad_type",
        ),
        description=(
            "The negative half of the demand signal: pipeline pressure (Step 6.1) and the "
            "price-gap curve that calibrates the price cap (Step 6.3)."
        ),
        column_notes={
            "lead_id": "Lead key, 'LEAD-nnnnnn'. 1,450 lost leads.",
            "client_id": "Existing account, where the lead came from one. Null on 643 rows — and those "
            "are exactly the rows where company_name_raw is populated, so every lead is identified by "
            "one column or the other. Null here means a new prospect, not missing data.",
            "company_name_raw": "Free-text company name for prospects with no account yet (643 rows); "
            "null on the 807 rows that do have a client_id.",
            "industry_vertical": "Same 13-value vocabulary as bookings; drives segment-level pipeline heat.",
            "city_id": "City the lead asked for.",
            "requested_geography": "'<CITY>:<Zone name>' string — parse to a zone before use. This is "
            "what makes a lead attributable to specific inventory and therefore to demand pressure.",
            "anchor_screen_id": "The specific screen asked about, where the lead named one.",
            "lead_source": "repeat_client_inquiry (500) / website_form / inbound_call / cold_outreach / "
            "referral / trade_show. Source correlates with intent quality.",
            "lead_date": "When the lead arrived. The age input for the recency-decay weighting — a "
            "stale lead must count for less than a fresh one.",
            "sales_stage_reached": "initial_inquiry (531) / quote_sent (415) / negotiating (281) / "
            "verbal_agreement (141) / contract_sent (82). How far it got — a lead lost at contract_sent "
            "is far stronger evidence of real demand than one lost at initial_inquiry.",
            "lost_date": "When the lead was marked lost. lost_date minus lead_date is the cycle length.",
            "requested_start_date": "Flight start the client wanted — matches the lead to a demand window.",
            "requested_duration_days": "Flight length requested.",
            "requested_num_screens": "Screens requested, 1-33 (median 5). Sizes the lost opportunity.",
            "indicated_budget": "Budget the client stated.",
            "quoted_price_per_slot_per_day": "Our quote. Null for all 531 initial_inquiry leads and only "
            "those — the lead died before a price existed, so absence is meaningful, not missing.",
            "client_target_price_per_slot_per_day": "The price the client wanted; null wherever no quote "
            "was made or no counter-offer was given (47.6%).",
            "price_gap_pct": "(quote - client target) / target. The core price-cap calibration signal: "
            "the gap at which deals demonstrably die is the willingness-to-pay ceiling.",
            "negotiation_rounds": "Counter-offers exchanged, 0-5 (median 0). Effort spent before losing.",
            "competitor_mentioned": "True where a competitor was named — a competitive-pressure flag.",
            "loss_reason": "10 values. price_too_high (305) and budget_mismatch (186) are price losses "
            "and calibrate the cap; no_response_ghosted (262), went_with_competitor, timing_conflict, "
            "contract_terms_disagreement, inventory_unavailable, campaign_cancelled_internally, "
            "targeting_mismatch and creative_not_ready are not, and must be excluded from that fit. "
            "inventory_unavailable (107) is separately valuable: it is direct evidence of scarcity.",
            "loss_reason_detail": "Free-text elaboration of the reason; qualitative colour only.",
            "campaign_objective": "Same four-value vocabulary as bookings.",
            "ad_type": "Free-text creative name, as in bookings.",
        },
    ),
)

CATALOG: Mapping[str, TableSpec] = {spec.name: spec for spec in _SPECS}

TABLE_NAMES: tuple[str, ...] = tuple(CATALOG)


def get(name: str) -> TableSpec:
    try:
        return CATALOG[name]
    except KeyError:
        raise KeyError(f"Unknown table {name!r}. Known tables: {', '.join(TABLE_NAMES)}") from None


def iter_tables(layer: str | None = None) -> Iterator[TableSpec]:
    for spec in CATALOG.values():
        if layer is None or spec.layer == layer:
            yield spec


def tables_by_layer() -> Mapping[str, tuple[str, ...]]:
    return {
        layer: tuple(spec.name for spec in iter_tables(layer))
        for layer in LAYERS
    }


def all_foreign_keys() -> Sequence[tuple[str, ForeignKey]]:
    """Every declared edge as (child_table, ForeignKey), in catalogue order."""
    return [(spec.name, fk) for spec in CATALOG.values() for fk in spec.foreign_keys]
