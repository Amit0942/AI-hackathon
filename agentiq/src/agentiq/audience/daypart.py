"""Shared daypart/time-block facts (`dim_slot`), reused by both D1 exposure models.

`night` maps to two blocks (1 and 6) — Step 1.4's proven, non-key relationship —
so this mapping, not `dim_slot.nearest_daypart` directly, is what every D1
function keys off when aligning a POI's `peak_daypart` or an event's daypart
to a specific `time_block_id`.
"""

from __future__ import annotations

from agentiq.domain.inventory import TIME_BLOCK_IDS

#: `dim_slot.time_block_id -> nearest_daypart` (Step 1.4 §... / data dictionary).
TIME_BLOCK_DAYPART: dict[int, str] = {
    1: "night",
    2: "morning",
    3: "midday",
    4: "afternoon",
    5: "evening",
    6: "night",
}

assert set(TIME_BLOCK_DAYPART) == set(TIME_BLOCK_IDS)

#: Step 1.6 §6's measured, normalised ridership daypart curve — the network-wide
#: default used only when a location/corridor has no ridership rows of its own
#: (e.g. a brand-new stop). Real per-location/per-corridor shares, computed from
#: `ridership_actuals` via `NetworkRepository`, are always preferred over this.
DEFAULT_DAYPART_SHARE: dict[str, dict[int, float]] = {
    "weekday": {1: 0.0, 2: 0.209, 3: 0.270, 4: 0.121, 5: 0.301, 6: 0.098},
    "weekend": {1: 0.0, 2: 0.091, 3: 0.241, 4: 0.314, 5: 0.257, 6: 0.098},
}
