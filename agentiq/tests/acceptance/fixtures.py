"""Gold-parse acceptance fixtures for the six supplied campaign briefs (Step 2.5).

Every field below was hand-read from `data/raw/Campaigns/campaign_N.docx`,
not inferred from `agentiq.data.briefs`'s regexes — this is the independent
"hand-checked expectation" the plan asks for, so a bug in the deterministic
parser cannot also hide in its own test fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AcceptanceScenario:
    """One brief's hand-checked ground truth."""

    brief_number: int
    source_file: str
    campaign_title_contains: str
    company: str
    budget_amount: float
    duration_days: int
    age_min: int
    age_max: int

    #: Environment types (config/taxonomy.yaml vocabulary) this brief's location
    #: requirements should resolve onto. Order-independent, checked as a set.
    expected_environment_types: frozenset[str]

    #: True if the brief states a hard exclusion (never buy this inventory,
    #: regardless of fit) as opposed to a soft preference.
    has_hard_exclusion: bool

    #: Screen-type or inventory substrings the exclusion names, for a human to
    #: cross-check the Phase 5 eligibility filter against — empty if no exclusion.
    excluded_inventory_hints: tuple[str, ...] = ()

    #: True if the brief explicitly asks for a walking-radius / distance constraint.
    requires_walking_radius: bool = False

    #: True if the brief explicitly asks for weekend-vs-weekday weighted delivery.
    requires_weekend_weighting: bool = False

    #: True if the brief explicitly asks the response to report a business vs.
    #: leisure, or repeat vs. one-time, frequency split (not just total reach).
    requires_frequency_split: bool = False

    #: Minimum number of location-requirement environment types the eligibility
    #: filter must actually use (never silently drop to one and still call it done).
    min_required_environments: int = 1

    unresolved_capability_keywords: frozenset[str] = field(default_factory=frozenset)


SCENARIOS: tuple[AcceptanceScenario, ...] = (
    AcceptanceScenario(
        brief_number=1,
        source_file="campaign_1.docx",
        campaign_title_contains="ZEPHYR EV",
        company="Voltaic Motors Inc.",
        budget_amount=40_000.0,
        duration_days=45,
        age_min=28,
        age_max=50,
        expected_environment_types=frozenset(
            {"business_district_platform", "auto_retail_arterial_corridor"}
        ),
        has_hard_exclusion=True,
        excluded_inventory_hints=("bus-rear", "bus_rear", "back", "value-tier", "residential"),
        min_required_environments=2,
        unresolved_capability_keywords=frozenset({"dwell", "aspect", "digital inventory"}),
    ),
    AcceptanceScenario(
        brief_number=2,
        source_file="campaign_2.docx",
        campaign_title_contains="EMBER ENERGY",
        company="Ember Beverages LLC",
        budget_amount=12_000.0,
        duration_days=21,
        age_min=18,
        age_max=30,
        expected_environment_types=frozenset(
            {
                "nightlife_entertainment_corridor",
                "campus_edge_transit_node",
                "event_venue_precinct",
            }
        ),
        has_hard_exclusion=False,
        requires_weekend_weighting=False,
        requires_frequency_split=True,
        min_required_environments=3,
        unresolved_capability_keywords=frozenset({"frequency"}),
    ),
    AcceptanceScenario(
        brief_number=3,
        source_file="campaign_3.docx",
        campaign_title_contains="LOOM & THREAD",
        company="Loom & Thread Apparel Co.",
        budget_amount=22_000.0,
        duration_days=20,
        age_min=20,
        age_max=40,
        expected_environment_types=frozenset(
            {"premium_mall_entry", "high_street_retail_corridor"}
        ),
        has_hard_exclusion=False,
        requires_weekend_weighting=True,
        min_required_environments=2,
        unresolved_capability_keywords=frozenset({"weekend", "weekday"}),
    ),
    AcceptanceScenario(
        brief_number=4,
        source_file="campaign_4.docx",
        campaign_title_contains="BASIL & BLOOM",
        company="Basil & Bloom Fast-Casual Kitchens",
        budget_amount=9_000.0,
        duration_days=15,
        age_min=18,
        age_max=35,
        expected_environment_types=frozenset({"hyperlocal_walking_radius"}),
        has_hard_exclusion=True,
        excluded_inventory_hints=("outside", "walking distance", "radius"),
        requires_walking_radius=True,
        min_required_environments=1,
        unresolved_capability_keywords=frozenset({"walking", "radius"}),
    ),
    AcceptanceScenario(
        brief_number=5,
        source_file="campaign_5.docx",
        campaign_title_contains="SKYNIMBUS",
        company="SkyNimbus Airlines Ltd.",
        budget_amount=35_000.0,
        duration_days=40,
        age_min=28,
        age_max=55,
        expected_environment_types=frozenset(
            {"airport_transit_corridor", "premium_business_core", "financial_district_node"}
        ),
        has_hard_exclusion=False,
        requires_frequency_split=True,
        min_required_environments=2,
        unresolved_capability_keywords=frozenset({"frequency"}),
    ),
    AcceptanceScenario(
        brief_number=6,
        source_file="campaign_6.docx",
        campaign_title_contains="LUMI",
        company="Lumi",
        budget_amount=20_000.0,
        duration_days=25,
        age_min=18,
        age_max=34,
        expected_environment_types=frozenset(
            {
                "mall_beauty_retail_entry",
                "high_street_retail_corridor",
                "central_metro_entry",
            }
        ),
        has_hard_exclusion=False,
        requires_weekend_weighting=True,
        min_required_environments=2,
        unresolved_capability_keywords=frozenset({"weekend"}),
    ),
)
