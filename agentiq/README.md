# AgentIQ — Urban Media Commercial Intelligence Platform

Hack Days 2026: The AgentIQ Frontier.

Turns a messy campaign brief into the best-fit screens, right slots,
optimal pricing, and a credible projected audience reach — with a clear
reasoning for every choice.

See [`../Hack Days 2026 Problem Statement.md`](<../Hack Days 2026 Problem Statement.md>)
for the problem this solves and [`../solution_plan.md`](../solution_plan.md)
for the full phased build plan. [`CLAUDE.md`](CLAUDE.md) documents the
architecture and conventions for AI-assisted development in this repo.

## Status

Phase 0 (foundation & scaffolding) complete: repository skeleton, config
scaffolding, observability spine, and a health-check API. Phases 1+
(data discovery, engines, agents, UI) are tracked in `solution_plan.md`.

## Prerequisites

- Python 3.11+
- The 14 raw CSVs in `data/raw/`. These are git-ignored (large files) —
  copy them in from the original `Data Sets/Urban Media Datasets/` source
  before running the data pipeline.

## Setup

```bash
make install
```

This creates a `.venv`, installs pinned dependencies from
`requirements.txt`, and installs the `agentiq` package in editable mode.

If you prefer not to use `make` (e.g. on plain Windows PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .
```

## Running

```bash
make serve
```

Starts the FastAPI app on `http://localhost:8000` with auto-reload.
Verify it's up:

```bash
curl http://localhost:8000/health
# {"status": "ok", "version": "0.1.0"}
```

## Testing

```bash
make test        # pytest
make lint        # ruff
make typecheck    # mypy
```

## Data pipeline

```bash
make data         # sanity-check raw CSVs are present (expects 14 files)
make profile       # regenerate docs/data_dictionary.md from data/raw (Phase 1)
make build         # build precomputed artifacts into data/artifacts (Phase 1+)
```

`make profile` and `make build` are not yet implemented — they are Phase 1
deliverables per `solution_plan.md`.

## Project layout

```
config/            city profiles, scoring weights, pricing guardrails, taxonomy
data/raw/           14 source CSVs (read-only)
data/artifacts/     precomputed parquet artifacts (git-ignored)
src/agentiq/        application code (domain, data, audience, relevance,
                    pricing, optimizer, agents, api, observability)
ui/                 frontend (Phase 9)
notebooks/          exploratory data analysis (Phase 1 only)
docs/               data dictionary, C4 diagrams, ADRs
tests/
```

## Design principles

1. Deterministic core, agentic edge — LLMs never author a price, score,
   or reach number (see `docs/decisions/0001-deterministic-core.md`).
2. Every number carries its provenance (the `Explanation` contract).
3. Config over code for anything city-specific.
4. Deep modules, thin interfaces.
5. Offline precompute vs. online request path.
6. Graceful degradation is designed, not accidental (cold-start fallback ladder).
7. Reproducibility — pinned deps, fixed seeds, one-command rebuild.
8. Test the maths, validate the prose.

Full detail in `../solution_plan.md` §2.
