"""Reproducible multi-agent adaptation of a published Text2CAD-Bench case.

The 600-case dataset and official evaluator are not public at the time this
adapter was written.  This module therefore uses the L2 hemisphere-and-cross-
groove task printed in Appendix F of the paper, and labels the result as a
published-case compatibility gate rather than an official benchmark score.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from uuid import uuid4

import cadflow as cad

from agent_dsl import ModelStore, MultiAgentStore


TEXT2CAD_BENCH_SOURCE = "https://arxiv.org/abs/2605.18430"
L2_GEOMETRIC_PROMPT = (
    "The overall appearance is a hemisphere with a cross-shaped recess. "
    "The main base feature is a hemisphere with a radius of 40mm. On the "
    "flat side, a deep cross-shaped groove is cut with a width of 10mm and "
    "depth of 20mm. The ends of the groove are open."
)


@dataclass(frozen=True, slots=True)
class PublishedCaseReport:
    benchmark: str
    source: str
    case_id: str
    level: str
    prompt_style: str
    agent_count: int
    proposal_count: int
    execution_valid: bool
    invalidity_rate: float
    brep_hard_gate_passed: bool
    target_minus_candidate_volume: float
    candidate_minus_target_volume: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _reference_shape():
    with cad.GraphSession(graph_id="text2cad_l2_reference"):
        sphere = cad.make_sphere_rsolid(40)
        upper_half = cad.make_box_rsolid(
            120, 120, 40, bottom_face_center=(0, 0, 0)
        )
        hemisphere = cad.intersect_rsolid(sphere, upper_half)
        slot_x = cad.make_box_rsolid(
            100, 10, 20, bottom_face_center=(0, 0, 0)
        )
        slot_y = cad.make_box_rsolid(
            10, 100, 20, bottom_face_center=(0, 0, 0)
        )
        grooves = cad.union_rsolid(slot_x, slot_y)
        return cad.cut_rsolid(hemisphere, grooves)


def run_published_l2_case(output_dir: str | Path) -> PublishedCaseReport:
    """Run the public L2 prompt as seven cooperating, deterministic agents."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    models = ModelStore(output / "models")
    model_id = f"text2cad_l2_{uuid4().hex}"
    models.open(model_id, create=True)
    agents = MultiAgentStore(models)

    proposals = (
        agents.submit_proposal(
            model_id, "sphere_agent", "sphere sphere_body 40",
            base_revision=0, proposal_id="sphere",
        ),
        agents.submit_proposal(
            model_id, "trim_agent", "box upper_half 120 120 40",
            base_revision=0, proposal_id="half",
        ),
        agents.submit_proposal(
            model_id, "hemisphere_agent",
            "intersect hemisphere sphere_body upper_half",
            base_revision=0, proposal_id="hemisphere",
            depends_on=("sphere", "half"),
        ),
        agents.submit_proposal(
            model_id, "x_groove_agent", "box slot_x 100 10 20",
            base_revision=0, proposal_id="slot_x",
        ),
        agents.submit_proposal(
            model_id, "y_groove_agent", "box slot_y 10 100 20",
            base_revision=0, proposal_id="slot_y",
        ),
        agents.submit_proposal(
            model_id, "groove_agent", "union grooves slot_x slot_y",
            base_revision=0, proposal_id="grooves",
            depends_on=("slot_x", "slot_y"),
        ),
        agents.submit_proposal(
            model_id, "final_agent",
            "cut final hemisphere grooves\nresult final",
            base_revision=0, proposal_id="final",
            depends_on=("hemisphere", "grooves"),
        ),
    )
    merged = agents.merge(
        model_id,
        tuple(item.proposal_id for item in proposals),
        expected_revision=0,
    )
    if merged.status != "ok":
        raise RuntimeError(f"Text2CAD published case failed: {merged.to_dict()}")

    target = output / "target.step"
    candidate = output / "candidate.step"
    cad.export_step(shapes=_reference_shape(), filename=str(target))
    exported = models.export_step(
        model_id, "final", candidate, expected_revision=1
    )
    if exported.status != "ok":
        raise RuntimeError(f"Text2CAD candidate export failed: {exported.to_dict()}")
    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(target, candidate)
    return PublishedCaseReport(
        benchmark="Text2CAD-Bench published-case compatibility",
        source=TEXT2CAD_BENCH_SOURCE,
        case_id="appendix-f-l2-hemisphere-cross-groove",
        level="L2",
        prompt_style="geometric",
        agent_count=7,
        proposal_count=len(proposals),
        execution_valid=True,
        invalidity_rate=0.0,
        brep_hard_gate_passed=bool(comparison.hard_gate_passed),
        target_minus_candidate_volume=float(
            comparison.target_minus_candidate_volume
        ),
        candidate_minus_target_volume=float(
            comparison.candidate_minus_target_volume
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_published_l2_case(args.output_dir).to_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
