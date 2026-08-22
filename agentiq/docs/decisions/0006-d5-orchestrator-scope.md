# ADR 0006: D5 (Agentic Orchestration) build scope

## Status

Accepted

## Context

Phase 8's tool chain is `parse_brief -> resolve_entities -> profile_lookup
-> score_relevance -> forecast_demand -> price_units -> optimize_package
-> compose_recommendation`, and `HANDOFF.md`'s own recommended build order
calls D5 "a thin wrapper over 1-4." With Phase 4 now built (ADR-0005), every
tool in that chain has a real implementation to call:

| Plan tool | Real implementation |
|---|---|
| `parse_brief` | `agentiq.data.briefs.{extract_docx_paragraphs,parse_brief,derive_fields}` |
| `resolve_entities` | `agentiq.data.resolution.resolve_brief` |
| `profile_lookup` | `AudienceProfileEngine` (D1) |
| `score_relevance` | `RelevanceEngine.rank()` (D2) |
| `forecast_demand` + `price_units` | `PricingEngine.price()` (D3) — already called once per candidate *inside* `OptimizerEngine._generate_candidates`, so D5 does not call D3 directly |
| `optimize_package` | `OptimizerEngine.allocate()` (D4) |
| `compose_recommendation` | new: deterministic narrative composition (this ADR) |

So D5 genuinely is thin — a five-call sequence, not a new engine. This ADR
records the judgment calls that sequence still required.

## Decisions

### 1. Public entrypoint matches the acceptance tests exactly

`agentiq.agents.run_brief_to_recommendation(docx_path) -> Recommendation` —
this exact name and signature is what `tests/acceptance/test_brief_scenarios.py`
already imports (`from agentiq.agents import run_brief_to_recommendation`),
written before D5 existed. Matching it rather than inventing a different
shape is what lets those tests be completed rather than rewritten.

### 2. Single time block per run — D4's own scope, inherited honestly

`OptimizerEngine.allocate()` optimizes one `time_block_id` per call
(ADR-0004 decision 4; multi-block joint allocation is its own deferred fast-
follow). D5 picks **one** block per brief: the first block in
`brief.time_block_ids` if the resolver found one (ADR-0005 §8's keyword
table), else a config-declared default. This is not a new limitation D5
introduces — it is D4's existing, already-documented scope, and D5 does not
paper over it with a fake multi-block loop that would silently produce
several disconnected `Package`s sharing one budget (which Step 7.1
explicitly says a bundle must not be — "reasoned about as one deal").

### 3. Relevance pre-shortlists the optimizer's candidate set — a real, checked cross-engine fix

The acceptance scenarios (`tests/acceptance/fixtures.py`) assert that every
recommended screen's audience profile carries at least one of the brief's
`expected_environment_types`. But `environment_poi_fit` is a **weighted**
Step 5.2 signal (25-35% of the blended score per `config/scoring.yaml`),
and `OptimizerEngine` has no environment-awareness of its own — it
optimizes reach over whatever eligible candidates it's given, so nothing in
the existing D2/D4 wiring *guaranteed* this property, even though every
individual engine was built correctly to its own spec.

Fixed with two small, additive, backward-compatible extensions (both
default to prior behaviour when unused, verified by the existing D2/D4 test
suites still passing unchanged):

- `RelevanceEngine.rank(..., require_environment_match=True)`
  (`relevance/__init__.py`) — restricts the ranked output to screens whose
  `AudienceProfile.environment_labels` overlaps `brief.requested_environment_types`,
  **falling back to the unfiltered ranking if the strict filter would
  return zero screens** (the documented case: `airport_transit_corridor`
  and `auto_retail_arterial_corridor` ground in no real POI type, so a
  brief requesting only those would otherwise get nothing — graceful
  degradation, not a crash).
- `OptimizerEngine.allocate(..., candidate_screens=...)`
  (`optimizer/__init__.py`) — restricts candidate generation to a supplied
  screen set instead of the whole network.

D5 calls `RelevanceEngine.rank(brief, require_environment_match=True)`,
takes the ranked screens (already sorted by the same score `RelevanceScore`
carries), and passes both the resulting screen tuple and the
`{screen_id: RelevanceScore}` dict into `OptimizerEngine.allocate()`. This
is the architecturally correct reading of the plan's own pipeline — D2's
job is to produce a shortlist ("score screens... to produce a ranked list"),
D4's is to optimize allocation *within* that shortlist ("optimize screen-
slot allocation"), not to search the whole network independently of D2's
ranking.

### 4. Narrative composition: deterministic, not an LLM call — same reasoning as D1 §3.3

CLAUDE.md permits an LLM for narrative composition (Step 8.4) but forbids
it from authoring any number. **No LLM endpoint is configured in this
environment** — the identical situation D1's `audience/semantic.py`
already documented and resolved the same way. `agentiq.agents.narrative`
builds prose with an f-string template reading only `Package`/
`CampaignBrief` fields, so every number in the narrative is trivially
sourced from the structured payload (not independently guessed).

The ADR-0001 hard rule — "a validation pass checks every figure quoted in
`narrative` against the numbers in `packages` and fails the response on any
mismatch" — is still implemented as a real, standalone function
(`validate_narrative_matches_recommendation`), even though this
deterministic template cannot currently diverge from its own inputs.
Building the check now, not skipped as "trivially true," is what lets a
real LLM be swapped in later (mirroring D1's own stated intent: "swapping
in a real LLM later means replacing this module's internals... the
guardrail stays identical") without the safety net being an afterthought.

### 5. Clarifications are attached, never block the pipeline

Per ADR-0005 decision 9, `resolve_brief()` never blocks — every judgment
call produces a `ClarificationQuestion` alongside a usable `CampaignBrief`.
D5 carries these through unchanged: `Recommendation` itself has no field
for them (Phase 2's domain type is frozen and out of this ADR's scope to
extend for a UI concern with no current consumer), so
`run_brief_to_recommendation` returns the `Recommendation` and the caller
who wants the clarifications reads them off the `ResolvedBrief` it can
obtain by calling `resolve_entities` directly — documented in the
function's own docstring, not hidden.

### 6. Trace: wired, one recorder per run, discarded after `trace_id` unless the caller wants it

`TraceRecorder` (Phase 0, built standalone, never wired into an engine
before this) now wraps every step (`parse_brief`, `resolve_entities`,
`score_relevance`, `optimize_package`, `compose_recommendation`).
`run_brief_to_recommendation` accepts an optional `trace_recorder`
parameter — if the caller supplies one, they can call `.finish()`
themselves afterward and inspect it; if not, one is created internally and
only its `trace_id` survives onto `Recommendation.trace_id`. Matches the
optional-caller-supplied-object pattern already used throughout D1/D2/D3/D4
(`audience_engine`, `pricing_engine`, `config`, etc.).

### 7. Completing the five placeholder acceptance tests, not leaving them red

`tests/acceptance/test_brief_scenarios.py`'s five `xfail(strict=True)`
Phase-8 tests were written with bodies that **unconditionally**
`raise AssertionError("Phase 8 not implemented")` after calling
`run_brief_to_recommendation` — a deliberate placeholder for whoever built
D5 to fill in with real assertions, per the file's own comment ("collected
here... so the definition of done is visible before the code exists").
This pass replaces each placeholder body with the real assertion its
docstring already promised, and removes `xfail` from whichever now
genuinely pass against real data — required by this repo's own stated
convention (`HANDOFF.md`: "`strict=True` means these fail the suite the
moment they start passing without the marker being removed... a live,
enforced definition of done").

## Consequences

- `agentiq/agents/__init__.py` is the D5 entrypoint;
  `agentiq/agents/narrative.py` holds the deterministic composition +
  validator, split out the same way D1-D4 split entrypoint from pure logic.
- `RelevanceEngine.rank()` and `OptimizerEngine.allocate()` both gained one
  new optional, default-off/default-None parameter each — verified
  backward-compatible by re-running their full existing test suites
  unchanged (34/34 passed) before adding any D5-specific test.
- A brief whose `requested_environment_types` never grounds in real POI
  data (documented for `airport_transit_corridor`,
  `auto_retail_arterial_corridor`) still produces a `Package` — via the
  environment-filter's fallback — rather than failing to find any
  candidate, consistent with design principle 6 ("graceful degradation is
  designed, not accidental").
- Multi-block joint allocation, bundle pricing (7.3), and the efficient
  frontier (7.4) remain deferred exactly as ADR-0004 already stated; D5
  does not attempt to work around those gaps.
