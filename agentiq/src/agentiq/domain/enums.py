"""Closed vocabularies shared across every engine (Step 2.1).

Every value here is measured, not invented — it mirrors a `category_columns`
entry in `agentiq.data.catalog` or a `config/taxonomy.yaml` list. An engine
that needs a value outside these enums has found a real gap (add it to the
catalogue/taxonomy and regenerate), not a reason to fall back to a bare string.
"""

from __future__ import annotations

from enum import StrEnum


class MarketTier(StrEnum):
    PREMIUM = "premium"
    STANDARD = "standard"
    VALUE = "value"


class TransitDensity(StrEnum):
    DENSE = "dense"
    MIXED = "mixed"
    SPRAWLING = "sprawling"


class ScreenType(StrEnum):
    METRO_STATION = "metro_station"
    BUS_STOP = "bus_stop"
    METRO_RAIL_COACH = "metro_rail_coach"
    BUS = "bus"

    @property
    def is_static(self) -> bool:
        return self in (ScreenType.METRO_STATION, ScreenType.BUS_STOP)

    @property
    def is_mobile(self) -> bool:
        return not self.is_static


class MountPosition(StrEnum):
    PLATFORM = "platform"
    ENTRANCE_EXIT = "entrance_exit"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BACK = "back"


class ScreenSize(StrEnum):
    S = "S"
    M = "M"
    L = "L"


class LocationType(StrEnum):
    BUS_STOP = "bus_stop"
    METRO_STATION = "metro_station"


class RotationType(StrEnum):
    SINGLE_ROTATION = "single_rotation"
    PARTIAL_ROTATION = "partial_rotation"
    FULL_EXCLUSIVITY = "full_exclusivity"


class BookingStatus(StrEnum):
    """completed = settled training data; active/upcoming = committed occupancy."""

    COMPLETED = "completed"
    ACTIVE = "active"
    UPCOMING = "upcoming"


class CampaignObjective(StrEnum):
    AWARENESS = "awareness"
    CONVERSION = "conversion"
    FREQUENCY = "frequency"
    REACH = "reach"


class IndustryVertical(StrEnum):
    AUTO = "auto"
    CPG = "cpg"
    EDUCATION = "education"
    ENTERTAINMENT = "entertainment"
    FINANCE = "finance"
    GOVERNMENT = "government"
    HEALTHCARE = "healthcare"
    HOSPITALITY = "hospitality"
    NONPROFIT = "nonprofit"
    REAL_ESTATE = "real_estate"
    RETAIL = "retail"
    TECHNOLOGY = "technology"
    TELECOM = "telecom"


class ClientTier(StrEnum):
    LOCAL_BUSINESS = "local_business"
    REGIONAL_CHAIN = "regional_chain"
    NATIONAL_CHAIN = "national_chain"


class NegotiationLeverage(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DayType(StrEnum):
    WEEKDAY = "weekday"
    WEEKEND = "weekend"


class Confidence(StrEnum):
    """How much to trust a figure. Always paired with a stated reason (Step 2.2)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 3, "medium": 2, "low": 1}[self.value]


class ColdStartRung(StrEnum):
    """The Step 6.5 fallback ladder, ordered strongest evidence first."""

    SCREEN_OWN_HISTORY = "screen_own_history"
    PEER_SCREENS_SAME_LOCATION_OR_CORRIDOR = "peer_screens_same_location_or_corridor"
    COHORT_ZONE_TYPE_POSITION_SIZE = "cohort_zone_type_position_size"
    CITY_SCREEN_TYPE_BASELINE = "city_screen_type_baseline"
    GLOBAL_RATE_CARD = "global_rate_card"

    @property
    def default_confidence(self) -> Confidence:
        return {
            ColdStartRung.SCREEN_OWN_HISTORY: Confidence.HIGH,
            ColdStartRung.PEER_SCREENS_SAME_LOCATION_OR_CORRIDOR: Confidence.MEDIUM,
            ColdStartRung.COHORT_ZONE_TYPE_POSITION_SIZE: Confidence.MEDIUM,
            ColdStartRung.CITY_SCREEN_TYPE_BASELINE: Confidence.LOW,
            ColdStartRung.GLOBAL_RATE_CARD: Confidence.LOW,
        }[self]
