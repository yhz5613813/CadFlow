"""Build and render a reinforced L-shaped mounting bracket with CadFlow."""

from __future__ import annotations

import json
from pathlib import Path

import cadflow as cad


OUTPUT_DIR = Path("examples/out/cadflow_complex_mounting_bracket")
STEP_PATH = OUTPUT_DIR / "complex_mounting_bracket.step"
STL_PATH = OUTPUT_DIR / "complex_mounting_bracket.stl"
PNG_PATH = OUTPUT_DIR / "complex_mounting_bracket.png"
METRICS_PATH = OUTPUT_DIR / "complex_mounting_bracket_metrics.json"


def _fuse(model: cad.Model, left: cad.Shape, right: cad.Shape, name: str) -> cad.Shape:
    result = model.union(left, right)
    print(name, result.kind, result.volume, result.bbox)
    return result


def _cut(model: cad.Model, body: cad.Shape, tool: cad.Shape, name: str) -> cad.Shape:
    result = model.cut(body, tool)
    print(name, result.kind, result.volume, result.bbox)
    return result


def build_part() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with cad.Model() as model:
        base = model.box(width=80.0, depth=50.0, height=8.0)
        print("base", base.kind, base.volume, base.bbox)

        back_plate = model.translate(
            model.box(width=80.0, depth=8.0, height=55.0),
            x=0.0,
            y=42.0,
            z=4.0,
        )
        bracket = _fuse(model, base, back_plate, "base_plus_back")

        gusset_wire = model.polyline(
            (
                (0.0, 8.0, 4.0),
                (0.0, 46.0, 4.0),
                (0.0, 46.0, 38.0),
            ),
            closed=True,
        )
        gusset_face = model.face(gusset_wire)
        gusset = model.extrude(gusset_face, x=8.0, y=0.0, z=0.0)
        left_gusset = model.translate(gusset, x=6.0, y=0.0, z=0.0)
        right_gusset = model.translate(gusset, x=66.0, y=0.0, z=0.0)
        bracket = _fuse(model, bracket, left_gusset, "left_gusset")
        bracket = _fuse(model, bracket, right_gusset, "right_gusset")

        boss = model.translate(
            model.cylinder(radius=14.0, height=14.0),
            x=40.0,
            y=25.0,
            z=6.0,
        )
        bracket = _fuse(model, bracket, boss, "central_boss")

        for index, (x, y) in enumerate(
            ((10.0, 10.0), (70.0, 10.0), (10.0, 40.0), (70.0, 40.0)),
            start=1,
        ):
            through_tool = model.translate(
                model.cylinder(radius=3.2, height=12.0),
                x=x,
                y=y,
                z=-2.0,
            )
            bracket = _cut(model, bracket, through_tool, f"base_hole_{index}")
            counterbore_tool = model.translate(
                model.cylinder(radius=5.0, height=3.5),
                x=x,
                y=y,
                z=5.0,
            )
            bracket = _cut(model, bracket, counterbore_tool, f"base_counterbore_{index}")

        boss_hole = model.translate(
            model.cylinder(radius=5.0, height=20.0),
            x=40.0,
            y=25.0,
            z=4.0,
        )
        bracket = _cut(model, bracket, boss_hole, "boss_through_hole")
        boss_counterbore = model.translate(
            model.cylinder(radius=8.0, height=4.0),
            x=40.0,
            y=25.0,
            z=16.5,
        )
        bracket = _cut(model, bracket, boss_counterbore, "boss_counterbore")

        for index, x in enumerate((20.0, 60.0), start=1):
            side_tool = model.rotate(
                model.cylinder(radius=4.0, height=14.0),
                degrees=90.0,
                axis=(1.0, 0.0, 0.0),
                origin=(0.0, 0.0, 0.0),
            )
            side_tool = model.translate(side_tool, x=x, y=52.0, z=35.0)
            bracket = _cut(model, bracket, side_tool, f"back_hole_{index}")

        final_part = bracket
        metrics = {
            "kind": final_part.kind,
            "volume": final_part.volume,
            "area": final_part.area,
            "center_of_mass": final_part.center_of_mass,
            "bbox": final_part.bbox,
            "topology": final_part.topology,
        }
        print("final_metrics", json.dumps(metrics, sort_keys=True))

        assert metrics["topology"]["solids"] == 1
        bbox = metrics["bbox"]
        assert bbox[0] <= 1.0e-5 and bbox[3] >= 79.0
        assert bbox[1] <= 1.0e-5 and bbox[4] >= 49.0
        assert bbox[2] <= 1.0e-5 and bbox[5] >= 58.0

        final_part.export_step(str(STEP_PATH))
        final_part.export_stl(str(STL_PATH), binary=True)

    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return metrics


def render_step() -> None:
    from cadflow.inspect import brep

    brep.render_step_views_rpath(
        step_path=STEP_PATH,
        output_path=PNG_PATH,
        title="CadFlow reinforced mounting bracket",
        image_size=(18.0, 12.0),
        dpi=180,
        show_brep_edges=True,
    )


def main() -> None:
    metrics = build_part()
    render_step()
    outputs = (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH)
    for path in outputs:
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")
    print("outputs")
    for path in outputs:
        print(path.resolve(), path.stat().st_size)
    print("solid_count", metrics["topology"]["solids"])


if __name__ == "__main__":
    main()
