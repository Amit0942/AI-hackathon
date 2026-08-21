# ADR 0001: Deterministic core, agentic edge

## Status

Accepted

## Context

AgentIQ combines classical models (pricing, scoring, optimisation) with
LLM agents (brief parsing, semantic labelling, orchestration, narrative
composition). Judging criterion 1 ("AI & Agentic Architecture") explicitly
scores the *soundness* of how ML, OR, and agentic orchestration combine
into one coherent system — and criterion 4 ("Explainability & Trust")
scores whether the system can justify its pricing and inventory choices.
An architecture where an LLM can silently produce or adjust a price, score,
or reach figure undermines both: outputs become unreproducible, hard to
test, and hard to trust in front of a judge or a real sales rep.

## Decision

We draw a hard boundary:

1. **Deterministic core** — pricing math, relevance-scoring math, the
   impressions/reach model, and the optimizer are pure functions over
   typed inputs. Same inputs -> same outputs, always. Fully unit-testable
   without mocking an LLM.
2. **Agentic edge** — LLM agents are used only where the problem is
   genuinely fuzzy: parsing unstructured campaign briefs, assigning
   semantic audience/environment labels from a controlled vocabulary,
   bounded re-ranking within a fixed band, orchestration/routing decisions,
   and composing narrative prose from already-computed numbers.
3. **No LLM-authored numerics.** Any number that appears in output to a
   user must trace back to a deterministic engine. Narrative composition
   (Phase 8.4) is validated post-hoc against the structured payload it was
   given; a mismatch fails the response rather than surfacing an invented
   figure.

## Consequences

- Every scored/priced/ranked value can carry a full, reproducible
  `Explanation` (ADR-backed by Step 2.2) — this is what makes
  Explainability a structural property instead of a prose afterthought.
- Testing strategy splits cleanly: numeric invariants get exact unit
  tests; LLM outputs get schema/grounding checks. No flaky
  exact-string-match tests against a live model.
- Semantic engines (Phase 3.3, Phase 5.3) must be precomputed/cached
  offline wherever possible, since they cannot sit on a latency-critical
  deterministic path — this also directly serves the Performance &
  Scalability criterion.
- Constrains agent design: the Phase 8 orchestrator is a planner-executor
  over typed tools, not a free-form chat loop that could reach into
  arithmetic.

## Alternatives considered

- **LLM computes prices/scores directly from context.** Rejected — not
  reproducible, not testable, and erodes the trust story the problem
  statement explicitly asks for ("no one knows if the price is right").
- **No LLM involvement at all, pure rules/ML.** Rejected — the deliverables
  (D1, D2, D5) explicitly call for AI Agent techniques, and a rules-only
  system cannot infer semantic audience fit or handle a genuinely
  unstructured brief.
