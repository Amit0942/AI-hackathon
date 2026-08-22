"""D5 — Agentic Orchestration (Phase 8).

Public entrypoint: `run_brief_to_recommendation()` — a five-call
planner-executor over Phase 4's resolver and D1-D4, not a new engine. See
`docs/decisions/0006-d5-orchestrator-scope.md` for the reasoning behind
every design choice here, in particular why relevance pre-shortlists the
optimizer's candidate set (decision 3) and why narrative composition is
deterministic, not an LLM call (decision 4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentiq.agents.narrative import compose_narrative, validate_narrative_matches_recommendation
from agentiq.audience import AudienceProfileEngine
from agentiq.data.briefs import derive_fields, extract_docx_paragraphs, parse_brief
from agentiq.data.repositories import InMemoryRepositories
from agentiq.data.resolution import ResolvedBrief, resolve_brief
from agentiq.domain.recommendation import Recommendation
from agentiq.observability.trace import TraceRecorder
from agentiq.optimizer import OptimizerEngine
from agentiq.pricing import PricingEngine
from agentiq.relevance import RelevanceEngine

__all__ = ["resolve_entities", "run_brief_to_recommendation"]

#: Used only when a brief states no daypart preference at all (ADR-0006
#: decision 2) — `dim_slot`'s "midday" block, a network-neutral default.
_DEFAULT_TIME_BLOCK_ID = 3

#: How many top-ranked screens (Step 5's shortlist) D4 is asked to optimize
#: over, rather than repricing the whole network per brief (ADR-0006 §3).
_DEFAULT_SHORTLIST_SIZE = 200


def resolve_entities(
    docx_path: Path,
    repos: InMemoryRepositories,
    *,
    brief_id: str | None = None,
) -> ResolvedBrief:
    """`parse_brief` + `resolve_entities`, Phase 4's two tools, run together.

    Exposed separately from `run_brief_to_recommendation` so a caller (D6's
    UI, or a rep-facing clarification loop) can inspect the
    `ClarificationQuestion`s *before* committing to a full recommendation
    run — `Recommendation` itself carries no clarification field
    (ADR-0006 decision 5).
    """
    docx_path = Path(docx_path)
    document = parse_brief(extract_docx_paragraphs(docx_path), source_file=docx_path.name)
    derived = derive_fields(document)
    return resolve_brief(document, derived, repos, brief_id=brief_id or docx_path.stem)


def run_brief_to_recommendation(
    docx_path: Path,
    *,
    repos: InMemoryRepositories | None = None,
    audience_engine: AudienceProfileEngine | None = None,
    relevance_engine: RelevanceEngine | None = None,
    pricing_engine: PricingEngine | None = None,
    optimizer_engine: OptimizerEngine | None = None,
    trace_recorder: TraceRecorder | None = None,
    shortlist_size: int = _DEFAULT_SHORTLIST_SIZE,
) -> Recommendation:
    """The full Phase 8 chain: a raw `.docx` in, a complete `Recommendation` out.

    Every engine is optional and default-constructed from *repos* if not
    supplied — the same pattern D1-D4 all use — so a caller running many
    briefs against one shared `repos` can build the engines once and reuse
    them, while a single-brief caller (e.g. the acceptance tests) can just
    supply the path.
    """
    docx_path = Path(docx_path)
    repos = repos or InMemoryRepositories()
    audience_engine = audience_engine or AudienceProfileEngine(repos)
    pricing_engine = pricing_engine or PricingEngine(repos, audience_engine=audience_engine)
    relevance_engine = relevance_engine or RelevanceEngine(repos, audience_engine=audience_engine)
    optimizer_engine = optimizer_engine or OptimizerEngine(repos, audience_engine, pricing_engine)
    recorder = trace_recorder or TraceRecorder()

    with recorder.step("parse_brief", inputs={"source": docx_path.name}) as rec:
        document = parse_brief(extract_docx_paragraphs(docx_path), source_file=docx_path.name)
        derived = derive_fields(document)
        rec.outputs = {"title": document.title, "sections": len(document.sections)}

    with recorder.step("resolve_entities", inputs={"source": docx_path.name}) as rec:
        resolved = resolve_brief(document, derived, repos, brief_id=docx_path.stem)
        brief = resolved.brief
        rec.outputs = {
            "industry_vertical": brief.industry_vertical.value,
            "objective": brief.objective.value,
            "budget": brief.budget,
        }
        rec.fallbacks_used = [q.question for q in resolved.clarifications if q.blocking]

    with recorder.step("score_relevance", inputs={"brief_id": brief.brief_id}) as rec:
        ranked = relevance_engine.rank(brief, require_environment_match=True)
        shortlist = ranked[:shortlist_size]
        candidate_screens = tuple(
            screen
            for screen in (repos.screens.get(rs.screen_id) for rs in shortlist)
            if screen is not None
        )
        relevance_by_screen = {rs.screen_id: rs for rs in shortlist}
        rec.outputs = {"ranked": len(ranked), "shortlisted": len(shortlist)}

    time_block_id = brief.time_block_ids[0] if brief.time_block_ids else _DEFAULT_TIME_BLOCK_ID
    with recorder.step(
        "optimize_package",
        inputs={"brief_id": brief.brief_id, "time_block_id": time_block_id},
    ) as rec:
        package = optimizer_engine.allocate(
            brief,
            time_block_id=time_block_id,
            relevance_scores=relevance_by_screen,
            candidate_screens=candidate_screens or None,
        )
        rec.outputs = {
            "package_id": package.package_id,
            "lines": len(package.lines),
            "unique_reach": package.reach.unique_reach,
        }

    with recorder.step("compose_recommendation", inputs={"package_id": package.package_id}) as rec:
        narrative = compose_narrative(brief, package)
        recommendation = Recommendation(
            recommendation_id=f"REC-{uuid4().hex[:12]}",
            brief=brief,
            packages=(package,),
            primary_package_id=package.package_id,
            narrative=narrative,
            trace_id=recorder.trace_id,
            generated_at=datetime.now(UTC),
        )
        validate_narrative_matches_recommendation(recommendation)
        rec.outputs = {"narrative_length": len(narrative)}

    return recommendation
