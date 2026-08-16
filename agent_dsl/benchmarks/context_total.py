"""Measure total context for a real multi-revision CadFlow DSL session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Callable, Sequence

import cadflow as cad

from agent_dsl import AgentModel, compare_conversations


DSL_REQUESTS = (
    "box base 40 24 8 at 0 0 0\nresult base",
    "cylinder hole 3 12 at 10 12 -2\ncut drilled base hole\nresult drilled",
    "translate final drilled 2 1 0\nresult final",
    "tag final role.finished\nresult final",
    "inspect final volume bbox topology tags limit=4",
)


def _python_request(operations: Sequence[str], *, effect: str = "") -> str:
    body = "\n".join(f"    {operation}" for operation in operations)
    suffix = f"\n{effect}" if effect else ""
    return (
        "import cadflow as cad\n"
        'with cad.GraphSession(graph_id="context_total") as session:\n'
        f"{body}\n"
        "    session.capture_result(value=final)\n"
        "    model_json = cad.export_model_json(session=session)"
        f"{suffix}"
    )


def _stateless_python_requests(
    inspection_path: Path, export_path: Path
) -> tuple[str, ...]:
    base = "base = cad.make_box_rsolid(40, 24, 8, bottom_face_center=(0, 0, 0))"
    hole = "hole = cad.make_cylinder_rsolid(3, 12, bottom_face_center=(10, 12, -2))"
    cut = "drilled = cad.cut_rsolid(base, hole)"
    move = "final = cad.translate_shape(drilled, (2, 1, 0))"
    tag = 'final = cad.apply_tag(final, "role.finished")'
    return (
        _python_request((base, "final = base")),
        _python_request((base, hole, cut, "final = drilled")),
        _python_request((base, hole, cut, move)),
        _python_request((base, hole, cut, move, tag)),
        _python_request(
            (base, hole, cut, move, tag),
            effect=(
                f'cad.export_step(shapes=final, filename="{inspection_path}")\n'
                "report = cad.inspect.brep.inspect_step_rbrepinspection("
                f'"{inspection_path}")\n'
                "facts = {\"volume\": report.volume, "
                "\"bbox\": report.bounding_box, \"topology\": report.counts, "
                "\"tags\": cad.list_tags(final)}"
            ),
        ),
        _python_request(
            (base, hole, cut, move, tag),
            effect=f'cad.export_step(shapes=final, filename="{export_path}")',
        ),
    )


def _build_public_api_reference(path: Path) -> None:
    with cad.GraphSession(graph_id="context_total_public") as session:
        base = cad.make_box_rsolid(
            40, 24, 8, bottom_face_center=(0, 0, 0)
        )
        hole = cad.make_cylinder_rsolid(
            3, 12, bottom_face_center=(10, 12, -2)
        )
        drilled = cad.cut_rsolid(base, hole)
        final = cad.translate_shape(drilled, (2, 1, 0))
        final = cad.apply_tag(final, "role.finished")
        session.capture_result(value=final)
        model_json = cad.export_model_json(session=session)
    replayed = cad.replay_model_json(model_json, strict=True)
    if len(replayed) != 1:
        raise RuntimeError("public API benchmark replay returned the wrong count")
    cad.export_step(shapes=replayed[0], filename=str(path))


def run_benchmark(
    output_dir: str | Path | None = None,
    *,
    token_counter: Callable[[str], int] | None = None,
    token_metric: str = "dependency-free lexical proxy",
) -> dict[str, object]:
    """Execute the DSL session and return whole-conversation measurements."""
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if output_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="cadflow-context-total-")
        output = Path(temporary.name)
    else:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
    dsl_export = output / "dsl-final.step"
    python_export = output / "python-final.step"
    python_inspection = output / "python-inspection.step"
    dsl_requests = (*DSL_REQUESTS, f"export final step {dsl_export}")

    model = AgentModel("context_total")
    responses: list[str] = []
    for request in dsl_requests:
        response = model.apply(request)
        if response.status != "ok":
            raise RuntimeError(response.compact_json())
        responses.append(response.compact_json())
    if not dsl_export.is_file() or dsl_export.stat().st_size == 0:
        raise RuntimeError("DSL benchmark did not create its STEP export")

    _build_public_api_reference(python_export)
    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(
        python_export, dsl_export
    )
    if not comparison.hard_gate_passed:
        raise RuntimeError(
            "benchmark geometries differ: "
            + json.dumps(comparison.to_dict(), sort_keys=True)
        )

    baseline_requests = _stateless_python_requests(
        python_inspection, python_export
    )
    compare_kwargs = {}
    if token_counter is not None:
        compare_kwargs["token_counter"] = token_counter
    report = compare_conversations(
        baseline_requests,
        dsl_requests,
        baseline_responses=responses,
        dsl_responses=responses,
        **compare_kwargs,
    ).to_dict()
    report["scope"] = {
        "turns": len(dsl_requests),
        "baseline": "stateless public Python rebuilt through the current revision",
        "responses": "actual compact JSON returned by AgentModel",
        "token_metric": token_metric,
        "fixed_system_context": "excluded; add the same S tokens to each model call",
        "geometry_hard_gate_passed": comparison.hard_gate_passed,
        "target_minus_candidate_volume": comparison.target_minus_candidate_volume,
        "candidate_minus_target_volume": comparison.candidate_minus_target_volume,
    }
    if temporary is not None:
        temporary.cleanup()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--tokenizer",
        help="optional tiktoken encoding, for example o200k_base",
    )
    args = parser.parse_args()
    token_counter = None
    token_metric = "dependency-free lexical proxy"
    if args.tokenizer:
        try:
            import tiktoken
        except ImportError as exc:
            parser.error(
                "--tokenizer requires optional tiktoken outside CadFlow's dependencies"
            )
            raise AssertionError from exc
        encoding = tiktoken.get_encoding(args.tokenizer)
        token_counter = lambda text: len(encoding.encode(text))
        token_metric = f"tiktoken {args.tokenizer}"
    print(
        json.dumps(
            run_benchmark(
                args.output_dir,
                token_counter=token_counter,
                token_metric=token_metric,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
