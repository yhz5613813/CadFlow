"""Build and render a detailed ceramic cup with CadFlow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadflow as cad


OUTPUT_DIR = Path("examples/out/cadflow_ceramic_cup")
STEP_PATH = OUTPUT_DIR / "ceramic_cup.step"
PNG_PATH = OUTPUT_DIR / "ceramic_cup.png"
METRICS_PATH = OUTPUT_DIR / "ceramic_cup_metrics.json"


def _tag(shape: Any, name: str) -> Any:
    cad.apply_tag(shape, name)
    return shape


def _ring(
    outer_radius: float,
    inner_radius: float,
    height: float,
    z: float,
    *,
    tag: str,
) -> Any:
    outer = cad.make_cylinder_rsolid(
        radius=outer_radius,
        height=height,
        bottom_face_center=(0.0, 0.0, z),
    )
    bore = cad.make_cylinder_rsolid(
        radius=inner_radius,
        height=height + 1.0,
        bottom_face_center=(0.0, 0.0, z - 0.5),
    )
    return _tag(cad.cut_rsolid(outer, bore), tag)


def _tube_between(start: tuple[float, float, float], end: tuple[float, float, float], radius: float) -> Any:
    vector = tuple(end[index] - start[index] for index in range(3))
    length = sum(component * component for component in vector) ** 0.5
    return cad.make_cylinder_rsolid(
        radius=radius,
        height=length,
        bottom_face_center=start,
        axis=vector,
    )


def build_cup() -> tuple[list[Any], dict[str, int]]:
    shapes: list[Any] = []
    counts: dict[str, int] = {}

    def add(shape: Any, tag: str) -> None:
        shapes.append(_tag(shape, tag))
        counts[tag] = counts.get(tag, 0) + 1

    # A gently tapered ceramic shell, hollowed from above while retaining a 6 mm base.
    outer = cad.make_cone_rsolid(
        bottom_radius=43.0,
        top_radius=39.5,
        height=70.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    inner = cad.make_cone_rsolid(
        bottom_radius=36.2,
        top_radius=34.5,
        height=68.5,
        bottom_face_center=(0.0, 0.0, 6.0),
    )
    add(cad.cut_rsolid(outer, inner), "cup.ceramic")

    # Thick rolled lip, visible both from the outside and through the open mouth.
    add(_ring(42.0, 34.2, 4.2, 67.0, tag="cup.rim"), "cup.rim")

    # Foot ring and two understated lower accent bands.
    add(_ring(35.5, 29.0, 4.5, -4.0, tag="cup.foot"), "cup.foot")
    add(_ring(43.1, 41.2, 2.5, 9.0, tag="cup.accent"), "cup.accent")
    add(_ring(41.7, 39.9, 2.2, 16.0, tag="cup.accent"), "cup.accent")

    # Reinforced handle made from overlapping circular tube segments and smooth joint beads.
    handle_points = (
        (37.5, 0.0, 53.0),
        (55.0, 0.0, 59.0),
        (70.0, 0.0, 51.0),
        (75.0, 0.0, 37.0),
        (70.0, 0.0, 22.0),
        (54.0, 0.0, 13.0),
        (37.5, 0.0, 19.0),
    )
    for start, end in zip(handle_points, handle_points[1:]):
        add(_tube_between(start, end, 5.2), "cup.handle")
    for point in handle_points[1:-1]:
        add(cad.make_sphere_rsolid(6.0, center=point), "cup.handle_joint")

    # Small ceramic collars make both handle-to-body connections read as designed features.
    for point in (handle_points[0], handle_points[-1]):
        add(
            cad.make_cylinder_rsolid(
                radius=7.0,
                height=5.0,
                bottom_face_center=(point[0] - 2.0, point[1], point[2]),
                axis=(1.0, 0.0, 0.0),
            ),
            "cup.handle_collar",
        )

    metrics = {
        "units": "millimeters",
        "solid_count": len(shapes),
        "groups": dict(sorted(counts.items())),
        "nominal_dimensions": {
            "height": 70.0,
            "body_outer_radius": 43.0,
            "body_inner_radius_at_base": 36.2,
            "handle_outer_span": 42.5,
        },
    }
    return shapes, metrics


def render_and_export(shapes: list[Any], metrics: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cad.export_step(shapes, str(STEP_PATH))
    from cadflow.inspect import brep

    brep.render_step_views_rpath(
        step_path=STEP_PATH,
        output_path=PNG_PATH,
        title="CadFlow ceramic cup",
        views=(
            (0.0, -90.0, "主视图"),
            (90.0, -90.0, "俯视图"),
            (0.0, 0.0, "侧视图"),
            (28.0, -45.0, "三维视图"),
        ),
        image_size=(18.0, 12.0),
        dpi=180,
        background_color=(1.0, 1.0, 1.0),
        font_file="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        show_brep_edges=True,
    )
    metrics["outputs"] = {
        "step": str(STEP_PATH.resolve()),
        "png": str(PNG_PATH.resolve()),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")


def main() -> None:
    shapes, metrics = build_cup()
    render_and_export(shapes, metrics)
    for path in (STEP_PATH, PNG_PATH, METRICS_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print("png", PNG_PATH.resolve(), PNG_PATH.stat().st_size)


if __name__ == "__main__":
    main()
