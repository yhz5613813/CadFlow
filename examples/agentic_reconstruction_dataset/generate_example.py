"""Generate and execute one tool-rich Agentic CAD training trajectory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import cadflow as cad
from cadflow.inspect import brep

from brep_adapter import heal_same_domain_rsolid
from fusion_adapter import (
    FusionReconstructionDesign,
    CadFlowFusionAdapter,
    json_safe,
)
from tool_contracts import TOOL_SCHEMAS


HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("CADFLOW_AGENT_OUTPUT", HERE / "out")).resolve()
SOURCE_DIR = Path(
    "/data/yihongzhu/Fusion360GalleryDataset/reconstruction/"
    "r1.0.1/r1.0.1/reconstruction"
)
SAMPLE_ID = os.environ.get("CADFLOW_SAMPLE_ID", "118433_f14b7df9_0000")
SOURCE_JSON = SOURCE_DIR / f"{SAMPLE_ID}.json"
TARGET_STEP = SOURCE_DIR / f"{SAMPLE_ID}.step"
TARGET_PNG = SOURCE_DIR / f"{SAMPLE_ID}.png"
CANDIDATE_RAW_STEP = OUT / f"{SAMPLE_ID}.raw.step"
CANDIDATE_STEP = OUT / f"{SAMPLE_ID}.candidate.step"
CANDIDATE_RENDER = OUT / f"{SAMPLE_ID}.candidate.views.png"
MODEL_JSON = OUT / f"{SAMPLE_ID}.model.json"
EVALUATION_JSON = OUT / f"{SAMPLE_ID}.evaluation.json"
TRAJECTORY_JSONL = OUT / "agentic_reconstruction_sample.jsonl"
TOOLS_JSON = OUT / "tool_schemas.json"


class TraceRecorder:
    """Record executable calls in an OpenAI-compatible messages structure."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def tool_call(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        invoke: Callable[[], Any],
    ) -> Any:
        call_id = f"call_{len(self.calls) + 1:03d}"
        self.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            }
        )
        try:
            raw_result = invoke()
            result = json_safe(raw_result)
            status = "ok"
        except Exception as exc:
            result = {"error_type": type(exc).__name__, "message": str(exc)}
            status = "error"
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
        self.calls.append(
            {
                "id": call_id,
                "name": name,
                "arguments": arguments,
                "result": result,
                "status": status,
            }
        )
        if status == "error":
            raise RuntimeError(f"Tool {name} failed: {result}")
        return raw_result


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    recorder = TraceRecorder()
    recorder.add_message(
        "system",
        (
            "You are a CAD reconstruction agent. Use only the supplied tools, keep "
            "Fusion source units in cm, inspect after every boolean feature, and "
            "finish with replay plus B-Rep evaluation. Tool observations are evidence; "
            "do not invent geometry outside the selected source profiles."
        ),
    )
    recorder.add_message(
        "user",
        (
            f"Reconstruct Fusion Gallery sample {SAMPLE_ID} as a replayable "
            "CadFlow model and compare it with the supplied target STEP."
        ),
    )

    design = FusionReconstructionDesign(SOURCE_JSON)
    source_summary = recorder.tool_call(
        name="reconstruction_read_sample",
        arguments={"source_json": str(SOURCE_JSON)},
        invoke=design.summary,
    )
    target_summary = recorder.tool_call(
        name="brep_inspect_step",
        arguments={"step_path": str(TARGET_STEP)},
        invoke=lambda: brep.inspect_step_rsummary(path=TARGET_STEP),
    )

    runtime_holder: dict[str, CadFlowFusionAdapter] = {}

    @cad.model(graph_id=f"fusion_reconstruction_{SAMPLE_ID}")
    def build_from_agent_tools() -> Any:
        runtime = CadFlowFusionAdapter(design)
        runtime_holder["runtime"] = runtime
        for feature_index, feature in enumerate(design.feature_plan(), start=1):
            feature_handles = []
            for profile_index, profile_ref in enumerate(feature["profile_refs"], start=1):
                profile_result = recorder.tool_call(
                    name="cad_create_profile",
                    arguments=profile_ref,
                    invoke=lambda profile_ref=profile_ref: runtime.create_profile(
                        sketch_id=profile_ref["sketch_id"],
                        profile_id=profile_ref["profile_id"],
                    ),
                )
                profile_handle = profile_result["profile_handle"]
                solid_handle = f"feature_solid_{feature_index}_{profile_index}"
                feature_handles.append(solid_handle)
                recorder.tool_call(
                    name="cad_extrude_profile",
                    arguments={
                        "profile_handle": profile_handle,
                        "solid_handle": solid_handle,
                        "distance_cm": feature["distance_cm"],
                        "extent_type": feature["extent_type"],
                    },
                    invoke=lambda feature=feature, profile_handle=profile_handle, solid_handle=solid_handle: runtime.extrude_profile(
                        profile_handle=profile_handle,
                        solid_handle=solid_handle,
                        distance_cm=feature["distance_cm"],
                        extent_type=feature["extent_type"],
                    ),
                )
            recorder.tool_call(
                name="cad_apply_feature",
                arguments={
                    "feature_handle": feature_handles[0]
                    if len(feature_handles) == 1
                    else feature_handles,
                    "operation": feature["operation"],
                },
                invoke=lambda feature=feature, feature_handles=feature_handles: runtime.apply_feature(
                    feature_handle=feature_handles,
                    operation=feature["operation"],
                ),
            )
            recorder.tool_call(
                name="cad_inspect_model",
                arguments={},
                invoke=runtime.inspect_current,
            )
        body = runtime.require_current()
        cad.capture_result(value=body)
        return body

    model_result = build_from_agent_tools()
    runtime = runtime_holder["runtime"]

    export_result = recorder.tool_call(
        name="cad_export_artifacts",
        arguments={
            "step_path": str(CANDIDATE_RAW_STEP),
            "model_json_path": str(MODEL_JSON),
        },
        invoke=lambda: _export_and_replay(model_result),
    )
    recorder.tool_call(
        name="cad_heal_same_domain",
        arguments={
            "input_step": str(CANDIDATE_RAW_STEP),
            "output_step": str(CANDIDATE_STEP),
            "linear_tolerance_mm": 1.0e-6,
        },
        invoke=lambda: _heal_and_export(
            runtime=runtime,
            input_step=CANDIDATE_RAW_STEP,
            output_step=CANDIDATE_STEP,
            linear_tolerance_mm=1.0e-6,
        ),
    )
    evaluation = recorder.tool_call(
        name="brep_evaluate_reconstruction",
        arguments={
            "target_step": str(TARGET_STEP),
            "candidate_step": str(CANDIDATE_STEP),
        },
        invoke=lambda: brep.evaluate_reconstruction_rdescriptor(
            target=TARGET_STEP,
            current=CANDIDATE_STEP,
            replay_succeeded=bool(export_result["replay_succeeded"]),
            require_strict_brep=True,
        ),
    )
    evaluation["acceptance"] = _acceptance_summary(evaluation)
    brep.render_step_views_rpath(
        step_path=CANDIDATE_STEP,
        output_path=CANDIDATE_RENDER,
        title=f"CadFlow reconstruction: {SAMPLE_ID}",
    )
    _write_json(EVALUATION_JSON, evaluation)
    _write_json(TOOLS_JSON, TOOL_SCHEMAS)

    final_inspection = runtime.inspect_current()
    acceptance = evaluation["acceptance"]
    recorder.add_message(
        "assistant",
        (
            "Reconstruction complete. The operation graph replayed successfully; "
            f"the candidate has volume {final_inspection['volume_cm3']:.9f} cm^3, "
            f"{final_inspection['face_count']} faces after same-domain healing. "
            f"Standard geometric acceptance is {acceptance['standard_geometry_passed']}; "
            f"the separate exact B-Rep hard gate is "
            f"{acceptance['strict_brep_passed']}."
        ),
    )
    record = {
        "schema_version": "agentic-cad-tool-trajectory-v0.1",
        "sample_id": SAMPLE_ID,
        "source": {
            "dataset": "Autodesk Fusion 360 Gallery Reconstruction r1.0.1",
            "json": str(SOURCE_JSON),
            "target_step": str(TARGET_STEP),
            "target_png": str(TARGET_PNG),
            "units": source_summary["units"],
        },
        "tools": TOOL_SCHEMAS,
        "messages": recorder.messages,
        "execution": {
            "all_tools_succeeded": all(call["status"] == "ok" for call in recorder.calls),
            "tool_call_count": len(recorder.calls),
            "calls": recorder.calls,
            "acceptance": acceptance,
            "target_summary": json_safe(target_summary),
            "artifacts": {
                "raw_replayable_step": str(CANDIDATE_RAW_STEP),
                "candidate_step": str(CANDIDATE_STEP),
                "candidate_render": str(CANDIDATE_RENDER),
                "model_json": str(MODEL_JSON),
                "evaluation_json": str(EVALUATION_JSON),
            },
        },
    }
    TRAJECTORY_JSONL.write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "trajectory": str(TRAJECTORY_JSONL),
                "tool_calls": len(recorder.calls),
                "candidate_step": str(CANDIDATE_STEP),
                "candidate_render": str(CANDIDATE_RENDER),
                "model_json": str(MODEL_JSON),
                "evaluation": str(EVALUATION_JSON),
            },
            indent=2,
        )
    )


def _export_and_replay(model_result: cad.ModelResult) -> dict[str, Any]:
    cad.export_step(shapes=model_result.value, filename=str(CANDIDATE_RAW_STEP))
    MODEL_JSON.write_text(model_result.model_json, encoding="utf-8")
    replayed = model_result.replay(strict=True)
    replay_volume = sum(shape.get_volume() for shape in replayed) / 1000.0
    return {
        "raw_replayable_step": str(CANDIDATE_RAW_STEP),
        "model_json": str(MODEL_JSON),
        "replay_succeeded": True,
        "replay_result_count": len(replayed),
        "replay_volume_cm3": replay_volume,
        "backend_calls": ["export_step", "ModelResult.model_json", "ModelResult.replay"],
    }


def _heal_and_export(
    *,
    runtime: CadFlowFusionAdapter,
    input_step: str | Path,
    output_step: str | Path,
    linear_tolerance_mm: float,
) -> dict[str, Any]:
    input_path = Path(input_step).resolve()
    input_solid = cad.Solid(
        brep.load_step_rshape(
            input_path,
            require_single_root=True,
            require_valid=True,
        )
    )
    healed, report = heal_same_domain_rsolid(
        solid=input_solid,
        linear_tolerance_mm=linear_tolerance_mm,
        output_step=output_step,
    )
    runtime.current = healed
    report["input_step"] = str(input_path)
    report["adapter_input_backend_calls"] = ["brep.load_step_rshape"]
    return report


def _acceptance_summary(evaluation: dict[str, Any]) -> dict[str, Any]:
    checks = evaluation["checks"]
    standard_checks = {
        name: bool(value)
        for name, value in checks.items()
        if name != "strict_brep_hard_gate"
    }
    standard_passed = all(standard_checks.values())
    strict_passed = bool(checks.get("strict_brep_hard_gate", False))
    return {
        "standard_geometry_passed": standard_passed,
        "strict_brep_passed": strict_passed,
        "classification": (
            "geometry_equivalent_source_precision_limited_brep"
            if standard_passed and not strict_passed
            else ("strict_brep_match" if strict_passed else "reconstruction_failed")
        ),
        "standard_checks": standard_checks,
        "strict_gate_note": (
            "The strict gate uses a 1e-6 mm3 absolute material tolerance and exact "
            "geometry-labelled incidence descriptors. The source JSON contains "
            "float32-like sketch coordinates, so it cannot reproduce every target "
            "STEP surface parameter exactly even when topology and material checks match."
        ),
    }


if __name__ == "__main__":
    main()
