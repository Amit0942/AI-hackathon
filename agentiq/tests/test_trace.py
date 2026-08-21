"""Step 0.3 exit criteria: a trace of a stub end-to-end call renders as a
readable timeline (ordered steps, durations, inputs hash, fallbacks)."""

import time

from agentiq.observability import TraceRecorder


def test_stub_pipeline_produces_readable_timeline() -> None:
    recorder = TraceRecorder()

    with recorder.step("parse_brief", inputs={"raw_text": "30-day campaign, $50K"}) as rec:
        rec.outputs = {"budget": 50_000, "duration_days": 30}

    with recorder.step("score_relevance", inputs={"brief_id": "B1"}) as rec:
        time.sleep(0.001)
        rec.outputs = {"top_screen": "LH-SCR-000001", "score": 0.87}
        rec.tokens_used = 143

    with recorder.step("price_units", inputs={"screen_id": "LH-SCR-000001"}) as rec:
        rec.outputs = {"floor": 40.0, "target": 55.0, "cap": 70.0}
        rec.fallbacks_used.append("cohort_zone_type_position_size")

    trace = recorder.finish()

    assert len(trace.steps) == 3
    assert [s.name for s in trace.steps] == [
        "parse_brief",
        "score_relevance",
        "price_units",
    ]
    assert all(s.duration_ms >= 0 for s in trace.steps)
    assert all(len(s.inputs_hash) == 12 for s in trace.steps)
    assert trace.total_tokens == 143
    assert trace.steps[2].fallbacks_used == ("cohort_zone_type_position_size",)

    rendered = trace.to_dict()
    assert rendered["trace_id"] == trace.trace_id
    assert len(rendered["steps"]) == 3


def test_step_records_error_and_reraises() -> None:
    recorder = TraceRecorder()

    try:
        with recorder.step("broken_step", inputs={}):
            raise ValueError("boom")
    except ValueError:
        pass

    trace = recorder.finish()
    assert trace.steps[0].error == "boom"
