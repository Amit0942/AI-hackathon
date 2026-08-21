"""FastAPI service entrypoint.

Phase 0 scope: a health-check endpoint only, so `make serve` is runnable
from the very first commit. Campaign endpoints land in Phase 4/8.
"""

from __future__ import annotations

from fastapi import FastAPI

from agentiq import __version__

app = FastAPI(title="AgentIQ", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
