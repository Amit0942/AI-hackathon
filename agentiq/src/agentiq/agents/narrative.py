"""Step 8.4 — narrative composition, deterministic (ADR-0006 decision 4).

No LLM endpoint is configured in this environment — the same situation
`audience/semantic.py` (D1, Step 3.3) already documented and resolved the
same way. `compose_narrative` builds prose from an f-string template
reading only `CampaignBrief`/`Package` fields, so every number in it is
trivially sourced from the structured payload. `validate_narrative_matches_recommendation`
is the ADR-0001 hard rule as a real, standalone check — built now so a real
LLM can be swapped into `compose_narrative` later without the safety net
being an afterthought.
"""

from __future__ import annotations

import re

from agentiq.domain.campaign import CampaignBrief
from agentiq.domain.optimizer import Package
from agentiq.domain.recommendation import Recommendation

__all__ = ["compose_narrative", "validate_narrative_matches_recommendation"]

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")
#: Hyphenated alphanumeric IDs (package_id, screen_id, brief_id, ...) contain
#: digit runs that are not "quoted numbers" in the validator's sense — strip
#: them before scanning, or e.g. "PKG-04af5b981d17" wrongly registers "04",
#: "981" etc. as unmatched figures.
_ID_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]+-[A-Za-z0-9-]+\b")
#: Precisions the narrative template legitimately rounds to (percentages at
#: 1 decimal, money/frequency at 2, impressions/reach at 0). A quoted number
#: is accepted if it equals an allowed value rounded to ANY of these — not a
#: flat tolerance, which would be too tight for 0-decimal rounding on a
#: 6-figure impressions count and too loose for a small percentage, and
#: could hide a genuinely wrong number either way.
_ROUND_PRECISIONS: tuple[int, ...] = (0, 1, 2, 3, 4)
_ROUNDING_EPSILON = 1e-6


def compose_narrative(brief: CampaignBrief, package: Package) -> str:
    """Client-ready prose, composed *from* already-computed numbers only.

    Every figure quoted here is read directly off *brief*/*package* — never
    independently computed or guessed — which is what lets
    `validate_narrative_matches_recommendation` check it.
    """
    screens = ", ".join(package.screen_ids[:5])
    if len(package.screen_ids) > 5:
        screens += f", and {len(package.screen_ids) - 5} more"

    budget_pct = (
        package.total_budget_used / brief.budget * 100 if brief.budget > 0 else 0.0
    )
    fallback_note = ""
    if package.explanation.is_fallback:
        fallback_note = (
            " Note: " + "; ".join(package.explanation.fallbacks_used) + "."
        )

    return (
        f"For {brief.company}'s {brief.industry_vertical.value} campaign "
        f"({brief.objective.value}, {brief.duration_days}-day flight, "
        f"${brief.budget:,.2f} budget), we recommend package {package.package_id} "
        f"({package.label}): {len(package.lines)} screen-slot line(s) across "
        f"{len(package.screen_ids)} screen(s) [{screens}], using "
        f"${package.total_budget_used:,.2f} ({budget_pct:.1f}% of budget). "
        f"Projected {package.reach.unique_reach:,.0f} unique reach from "
        f"{package.reach.gross_impressions:,.0f} gross impressions "
        f"({package.reach.frequency:.2f}x average frequency), selected via "
        f"{package.optimizer_strategy} ({package.optimizer_guarantee})."
        f"{fallback_note}"
    )


def _allowed_numbers(brief: CampaignBrief, package: Package) -> set[float]:
    """Every number the template is permitted to quote — the ground truth
    `validate_narrative_matches_recommendation` checks the rendered prose
    against."""
    allowed: set[float] = {
        brief.budget,
        float(brief.duration_days),
        package.total_budget_used,
        float(len(package.lines)),
        float(len(package.screen_ids)),
        package.reach.unique_reach,
        package.reach.gross_impressions,
        package.reach.frequency,
    }
    if brief.budget > 0:
        allowed.add(package.total_budget_used / brief.budget * 100)
    if len(package.screen_ids) > 5:
        allowed.add(float(len(package.screen_ids) - 5))
    return allowed


def _extract_numbers(text: str) -> list[float]:
    text = _ID_TOKEN_RE.sub(" ", text)
    numbers: list[float] = []
    for match in _NUMBER_RE.findall(text):
        cleaned = match.replace(",", "")
        try:
            numbers.append(float(cleaned))
        except ValueError:  # pragma: no cover - defensive; regex only matches numerics
            continue
    return numbers


def validate_narrative_matches_recommendation(recommendation: Recommendation) -> None:
    """ADR-0001's hard rule: every figure quoted in `narrative` must trace
    back to a real number in `recommendation.packages`. Raises `ValueError`
    on any mismatch rather than returning a bool, so a caller cannot
    silently ignore the result — matching `PriceQuote`/`Package`'s own
    fail-at-construction convention for invariants that must always hold.
    """
    package = recommendation.primary_package
    allowed = _allowed_numbers(recommendation.brief, package)

    # The optimizer's guarantee/strategy text ("(1 - 1/e) / 2 ~= 0.316 of
    # optimal...") is algorithm metadata quoted verbatim, not a claim about
    # this specific campaign's figures — excluded from the scan, same
    # reasoning as stripping ID tokens.
    text = recommendation.narrative
    for metadata in (package.optimizer_guarantee, package.optimizer_strategy):
        if metadata:
            text = text.replace(metadata, " ")

    unmatched: list[float] = []
    for number in _extract_numbers(text):
        if not any(
            abs(number - round(value, precision)) <= _ROUNDING_EPSILON
            for value in allowed
            for precision in _ROUND_PRECISIONS
        ):
            unmatched.append(number)

    if unmatched:
        raise ValueError(
            f"narrative for {recommendation.recommendation_id!r} quotes number(s) "
            f"{unmatched} that do not match any figure in the structured package "
            f"{package.package_id!r} — ADR-0001's hard rule was violated."
        )
