# C4 Model — AgentIQ (Step 2.4, drafted; finalised in Phase 10)

Three levels, each as a Mermaid diagram rendered directly from this
repository's real module tree — not hand-drawn boxes that can drift from the
code. Re-check these against `src/agentiq/` whenever a module is added,
renamed, or moved.

- [`context.mmd`](context.mmd) — who/what talks to AgentIQ.
- [`container.mmd`](container.mmd) — the deployable units.
- [`component.mmd`](component.mmd) — the five engines + orchestrator, drawn from `src/agentiq/*`.

## Rendering

Any Mermaid-aware renderer works (GitHub natively, `mmdc` CLI, VS Code
Mermaid extension). For the submission's required PDF/image export:

```
npx -y @mermaid-js/mermaid-cli -i docs/c4/context.mmd   -o docs/c4/context.png
npx -y @mermaid-js/mermaid-cli -i docs/c4/container.mmd -o docs/c4/container.png
npx -y @mermaid-js/mermaid-cli -i docs/c4/component.mmd -o docs/c4/component.png
```

## What's still a draft vs. what's real

Component boundaries and engine names are real (they are the actual
`src/agentiq/*` package names). Some elements — the LLM provider, the UI, and
individual agent tools inside D5 — describe the *target* shape from
`solution_plan.md` and are marked `(planned)` below since Phases 3–9 have not
been built yet. Update the `(planned)` tags to solid as each phase lands
so this document never silently drifts ahead of the code (Step 10.2 finalisation).
