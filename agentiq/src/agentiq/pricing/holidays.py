"""US federal holiday calendar — closes Step 6.2's previously-stated gap
("no future holiday calendar exists in the raw data").

All three cities' configured timezones (`config/cities/*.yaml`:
`America/New_York`, `America/Denver`, `America/Chicago`) are real US zones,
so the US federal calendar is applied uniformly across LH/DAT/ACS — a
stated assumption (these are fictional cities with no distinct state/city
calendar to model), not a measured fact. Computed programmatically
(nth-weekday-of-month rules) rather than a per-year lookup table, so any
future forecast window is covered without maintenance.

Holidays are dated to their **actual calendar date**, not the
Friday/Monday-shifted "observed" date federal offices use for a day off —
transit ridership responds to the real date, which is what
`docs/decisions/1.8_holiday_ridership_effect.md` measured against.
"""

from __future__ import annotations

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """*weekday*: Monday=0 ... Sunday=6. *n*: 1-based occurrence in the month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def us_federal_holidays(year: int) -> tuple[date, ...]:
    """The 11 US federal holidays for *year*, actual calendar dates."""
    return (
        date(year, 1, 1),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday (Presidents Day)
        _last_weekday(year, 5, 0),  # Memorial Day
        date(year, 6, 19),  # Juneteenth
        date(year, 7, 4),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        date(year, 11, 11),  # Veterans Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        date(year, 12, 25),  # Christmas Day
    )


def is_us_federal_holiday(day: date) -> bool:
    return day in us_federal_holidays(day.year)


__all__ = ["is_us_federal_holiday", "us_federal_holidays"]
