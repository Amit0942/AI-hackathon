"""Scenario-driven acceptance tests (Step 2.5).

Each of the six supplied campaign briefs becomes one acceptance scenario
with hand-checked expectations, derived by reading the brief text directly
(see `docs/decisions/1.8_brief_gold_parses.md` — the gold parse). These
double as the demo script (Step 10.5) and as the Phase 8 exit criterion:
"All Step 2.5 acceptance scenarios pass end-to-end."

Two layers are tested separately, matching how far the codebase has been
built:

* **Structural expectations** (this phase) — the brief parses correctly and
  its stated constraints resolve onto the real `config/taxonomy.yaml`
  vocabulary. These run and pass today.
* **End-to-end expectations** (Phase 8) — the full `parse_brief -> ... ->
  compose_recommendation` pipeline honours each brief's hard constraints
  (e.g. the hyper-local brief returns only screens inside its walking
  radius). These are collected as `xfail(strict=True, reason="Phase 8 not
  built yet")` per Step 2.5 ("failing acceptance tests committed — our
  definition of done"): once Phase 8 lands, removing the `xfail` marker
  from a scenario that now passes is how "done" gets proven, and a
  strict-xfail that *starts unexpectedly passing* before that is itself a
  signal to investigate, not a free pass.
"""
