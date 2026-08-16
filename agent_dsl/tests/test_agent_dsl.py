from __future__ import annotations

import json
from pathlib import Path

import pytest

import cadflow as cad
from agent_dsl import AgentModel, DSLParseError, estimate_tokens, measure_compression, parse


DSL_MODEL = """
box base 40 24 8 at 0 0 0
cylinder hole 3 12 at 10 12 -2
cut drilled base hole
translate final drilled 2 1 0
tag final role.finished
inspect final volume bbox topology tags limit=4
result final
"""


def _baseline_step(path: Path) -> str:
    with cad.GraphSession(graph_id="baseline") as session:
        base = cad.make_box_rsolid(40, 24, 8, bottom_face_center=(0, 0, 0))
        hole = cad.make_cylinder_rsolid(3, 12, bottom_face_center=(10, 12, -2))
        drilled = cad.cut_rsolid(base, hole)
        final = cad.translate_shape(drilled, (2, 1, 0))
        final = cad.apply_tag(final, "role.finished")
        session.capture_result(value=final)
        payload = cad.export_model_json(session=session)
    replayed = cad.replay_model_json(payload, strict=True)
    assert len(replayed) == 1
    cad.export_step(shapes=replayed[0], filename=str(path))
    return payload


def test_parser_is_restricted_and_supports_compact_options():
    instructions = parse("box base 2 3 4 at 0 0 0\ninspect base volume bbox limit=3")
    assert instructions[0].op == "box"
    assert instructions[1].args[2] == 3
    with pytest.raises(DSLParseError):
        parse("python bad __import__('os').system('touch /tmp/no')")
    with pytest.raises(DSLParseError):
        parse("box bad nan 2 3")
    with pytest.raises(DSLParseError):
        parse("box bad 2 3 4 axis 0 0 1")
    with pytest.raises(DSLParseError):
        parse("sphere bad 2 at 0 0 0 at 1 1 1")


def test_runtime_revisions_checkpoint_and_bounded_response(tmp_path: Path):
    model = AgentModel("revision_test")
    first = model.apply("box base 20 10 4\nresult base\ncheckpoint base")
    assert first.status == "ok"
    assert first.revision == 1
    assert first.created == ("base",)
    assert "model_json" not in first.to_dict()
    second = model.apply("translate moved base 5 0 0\nresult moved")
    assert second.status == "ok"
    assert second.created == ("moved",)
    rolled_back = model.apply("rollback base")
    assert rolled_back.status == "ok"
    assert rolled_back.revision == 3
    assert rolled_back.result is not None
    assert rolled_back.result["bbox"] == pytest.approx([-10, -5, 0, 10, 5, 4])
    assert model.snapshot()["commands"][-1] == "checkpoint base"


def test_model_json_replays_and_dsl_exports(tmp_path: Path):
    candidate = tmp_path / "candidate.step"
    model = AgentModel("parity")
    response = model.apply(DSL_MODEL.replace("result final", f"export final step {candidate}\nresult final"))
    assert response.status == "ok", response.to_dict()
    assert candidate.is_file() and candidate.stat().st_size > 0
    replayed = cad.replay_model_json(model.model_json, strict=True)
    assert len(replayed) == 1
    assert replayed[0].get_volume() == pytest.approx(response.result["volume"], rel=1e-9)
    payload = json.loads(model.model_json)
    allowed_ops = set(payload["canonical_contract"]["core_op_set"]) | set(
        payload["canonical_contract"]["semantic_op_set"]
    )
    assert all(node["op"] in allowed_ops for node in payload["graph"]["nodes"])


def test_dsl_geometry_is_strictly_brep_equal_to_public_api(tmp_path: Path):
    baseline = tmp_path / "baseline.step"
    candidate = tmp_path / "candidate.step"
    _baseline_step(baseline)
    model = AgentModel("strict_parity")
    response = model.apply(DSL_MODEL.replace("result final", f"export final step {candidate}\nresult final"))
    assert response.status == "ok", response.to_dict()
    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(baseline, candidate)
    assert comparison.hard_gate_passed, comparison.to_dict()
    assert comparison.target_minus_candidate_volume == pytest.approx(0.0, abs=1e-9)
    assert comparison.candidate_minus_target_volume == pytest.approx(0.0, abs=1e-9)


def test_context_reduction_exceeds_twenty_percent():
    public_python = """
import cadflow as cad
with cad.GraphSession(graph_id="context_demo") as session:
    base = cad.make_box_rsolid(40, 24, 8, bottom_face_center=(0, 0, 0))
    hole = cad.make_cylinder_rsolid(
        3, 12, bottom_face_center=(10, 12, -2)
    )
    drilled = cad.cut_rsolid(base, hole)
    final = cad.translate_shape(drilled, (2, 1, 0))
    final = cad.apply_tag(final, "role.finished")
    session.capture_result(value=final)
    model_json = cad.export_model_json(session=session)
"""
    dsl = DSL_MODEL
    report = measure_compression(public_python, dsl)
    byte_reduction = 1.0 - len(dsl.encode("utf-8")) / len(
        public_python.encode("utf-8")
    )
    print(json.dumps(report.to_dict(), sort_keys=True))
    assert report.meets_twenty_percent_target, report.to_dict()
    assert report.reduction_ratio >= 0.20
    assert byte_reduction >= 0.20
    assert estimate_tokens(report.to_dict().__repr__()) > 0
