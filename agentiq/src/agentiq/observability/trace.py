"""Observability spine (Phase 0, Step 0.3).

Every engine and agent step writes one `TraceStep` into a `TraceRecorder`.
This is deliberately independent of any specific engine so it can be wired
in from Phase 3 onward without redesign, and it is what later powers:

- the UI's "why did you do this" live trace panel (Phase 9, Step 9.1.3),
- the latency numbers quoted in Step 10.1,
- the demo narrative in Step 10.5.

Kept dependency-free (stdlib only) so it never becomes a bottleneck or a
source of flakiness in the request path.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


def _stable_hash(value: Any) -> str:
    """Deterministic short hash of a JSON-serialisable input, for trace correlation."""
    try:
        payload = json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        payload = repr(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class TraceStep:
    """One recorded step in an agent/engine run.

    Fields mirror exactly what Step 0.3 specifies: step name, duration,
    inputs hash, outputs, tokens used, fallbacks triggered.
    """

    step_id: str
    name: str
    started_at: float
    duration_ms: float
    inputs_hash: str
    outputs: Any
    tokens_used: int = 0
    fallbacks_used: tuple[str, ...] = ()
    error: str | None = None


@dataclass
class Trace:
    """A full run (one campaign brief -> recommendation), as an ordered list of steps."""

    trace_id: str
    steps: list[TraceStep] = field(default_factory=list)

    @property
    def total_duration_ms(self) -> float:
        return sum(s.duration_ms for s in self.steps)

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens_used for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_duration_ms": self.total_duration_ms,
            "total_tokens": self.total_tokens,
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "started_at": s.started_at,
                    "duration_ms": s.duration_ms,
                    "inputs_hash": s.inputs_hash,
                    "outputs": s.outputs,
                    "tokens_used": s.tokens_used,
                    "fallbacks_used": list(s.fallbacks_used),
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


class TraceRecorder:
    """Records steps for a single trace. One instance per request/run.

    Usage:
        recorder = TraceRecorder()
        with recorder.step("score_relevance", inputs={"brief_id": "..."}) as rec:
            result = do_work()
            rec.outputs = result
            rec.tokens_used = 120
        trace = recorder.finish()
    """

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or str(uuid.uuid4())
        self._steps: list[TraceStep] = []

    @contextmanager
    def step(self, name: str, inputs: Any = None) -> Iterator[_StepRecording]:
        rec = _StepRecording(name=name, inputs_hash=_stable_hash(inputs))
        start = time.perf_counter()
        started_at = time.time()
        try:
            yield rec
        except Exception as exc:  # noqa: BLE001 — re-raised after recording
            rec.error = str(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._steps.append(
                TraceStep(
                    step_id=str(uuid.uuid4()),
                    name=name,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    inputs_hash=rec.inputs_hash,
                    outputs=rec.outputs,
                    tokens_used=rec.tokens_used,
                    fallbacks_used=tuple(rec.fallbacks_used),
                    error=rec.error,
                )
            )

    def finish(self) -> Trace:
        return Trace(trace_id=self.trace_id, steps=list(self._steps))


@dataclass
class _StepRecording:
    name: str
    inputs_hash: str
    outputs: Any = None
    tokens_used: int = 0
    fallbacks_used: list[str] = field(default_factory=list)
    error: str | None = None
