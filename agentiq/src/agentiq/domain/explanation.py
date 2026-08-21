"""The `Explanation` contract (Step 2.2) — explainability as a type, not prose.

Every public engine output a user or judge might see (a score, a price, a
reach estimate, a package) carries one `Explanation`. This is what lets
Criterion 4 ("clarity with which the system justifies its pricing and
inventory recommendations") be satisfied *structurally*: the UI renders any
`Explanation` generically, and no engine can return a bare number.

Hard rule (ADR-0001, CLAUDE.md): an LLM may compose narrative prose *from*
an `Explanation`, but may never author the numbers inside one. Every
`Contribution.magnitude` and every `EvidenceRef` must trace back to a
deterministic computation or a real row in the data lake.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentiq.domain.enums import Confidence

Direction = Literal["positive", "negative", "neutral"]


class EvidenceRef(BaseModel):
    """A pointer to the real data behind a claim — table + row key(s) + the value used.

    This is what makes a `Contribution` falsifiable: a judge (or a test) can
    look up `table`/`row_key` in the raw data and see the cited `value` is real.
    """

    model_config = ConfigDict(frozen=True)

    table: str = Field(description="Catalogue table name, e.g. 'bookings', 'points_of_interest'.")
    row_key: dict[str, str | int] = Field(
        description="Primary-key column(s) -> value identifying the cited row(s)."
    )
    field: str = Field(description="Column the cited value came from.")
    value: Any = Field(description="The actual value read, at the time of computation.")
    note: str = ""


class Contribution(BaseModel):
    """One signal's contribution to a computed number.

    `weight` and `magnitude` are both required so a UI can render either a
    relative bar chart (`weight`) or an absolute effect (`magnitude`, in the
    same unit as the parent output — dollars, score points, reach count).
    """

    model_config = ConfigDict(frozen=True)

    signal: str = Field(description="Human-readable signal name, e.g. 'commute_peak_time_block'.")
    direction: Direction
    weight: float = Field(ge=0.0, le=1.0, description="Relative share of the total effect, 0-1.")
    magnitude: float = Field(description="Absolute effect, in the parent output's own unit.")
    evidence: tuple[EvidenceRef, ...] = ()
    detail: str = ""

    @model_validator(mode="after")
    def _direction_matches_magnitude(self) -> Contribution:
        if self.direction == "positive" and self.magnitude < 0:
            raise ValueError("direction='positive' but magnitude is negative")
        if self.direction == "negative" and self.magnitude > 0:
            raise ValueError("direction='negative' but magnitude is positive")
        if self.direction == "neutral" and self.magnitude != 0:
            raise ValueError("direction='neutral' requires magnitude == 0")
        return self


class Explanation(BaseModel):
    """Why a score/price/reach figure is what it is.

    ```
    Explanation
    ├─ headline: str                  # one-line human reason
    ├─ contributions: [Contribution]  # signal, direction, weight, magnitude
    ├─ evidence: [EvidenceRef]        # table + row keys + values used
    ├─ confidence: Confidence         # high | medium | low + why
    └─ fallbacks_used: [str]          # which defaults kicked in
    ```
    (Step 2.2, solution_plan.md)
    """

    model_config = ConfigDict(frozen=True)

    headline: str = Field(min_length=1, description="One-line human-readable reason.")
    contributions: tuple[Contribution, ...] = Field(default_factory=tuple)
    evidence: tuple[EvidenceRef, ...] = Field(
        default_factory=tuple,
        description="Evidence not already attached to a specific contribution.",
    )
    confidence: Confidence
    confidence_reason: str = Field(
        min_length=1, description="Why this confidence level, not another."
    )
    fallbacks_used: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Which cold-start rungs, defaults, or overrides fired, if any.",
    )

    @property
    def all_evidence(self) -> tuple[EvidenceRef, ...]:
        return self.evidence + tuple(ref for c in self.contributions for ref in c.evidence)

    @property
    def is_fallback(self) -> bool:
        return len(self.fallbacks_used) > 0

    def top_contributions(self, n: int = 3) -> tuple[Contribution, ...]:
        return tuple(sorted(self.contributions, key=lambda c: c.weight, reverse=True)[:n])


def merge_confidence(*levels: Confidence) -> Confidence:
    """Combine several sub-explanations' confidence into one: weakest link wins.

    Used when a parent output (e.g. a package) composes several children
    (e.g. per-line prices) — the package is never more confident than its
    least-confident component.
    """
    if not levels:
        raise ValueError("merge_confidence requires at least one Confidence")
    return min(levels, key=lambda c: c.rank)
