# AI-hackathon

**AgentIQ — Urban Media Commercial Intelligence Platform**, built for Hack Days 2026: The AgentIQ Frontier.

## Contents

- [`Hack Days 2026 Problem Statement.md`](<Hack Days 2026 Problem Statement.md>) /
  [`.pdf`](<Hack Days 2026 Problem Statement.pdf>) — the original problem statement.
- [`solution_plan.md`](solution_plan.md) — the full phased build plan (Phase 0–10).
- [`agentiq/`](agentiq/) — the application: source code, config, tests, docs, and the
  [README](agentiq/README.md) with setup/run instructions.

## Quick start

```bash
cd agentiq
make install
make serve
```

See [`agentiq/README.md`](agentiq/README.md) for full setup, prerequisites (including
where to source the raw dataset CSVs, which are git-ignored due to size), and the
project's design principles.

## Raw data

The source dataset (14 CSVs across geography/network/inventory/context/commercial
layers, plus 6 sample campaign briefs) is not committed to this repo — some files
exceed GitHub's size limits. Source it from the original `Data Sets/` folder and
place the CSVs into `agentiq/data/raw/` before running the data pipeline.
