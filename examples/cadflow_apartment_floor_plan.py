"""Approximate 3D reconstruction of the apartment plan in the reference image.

The screenshot contains no readable dimensions, so the model is scaled to a
nominal 12.0 m by 8.1 m envelope and preserves the visible room proportions.
CadFlow units are millimetres.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadflow as cad


OUT = Path("examples/out/cadflow_apartment_floor_plan")
STEP_PATH = OUT / "apartment_floor_plan.step"
STL_PATH = OUT / "apartment_floor_plan.stl"
PNG_PATH = OUT / "apartment_floor_plan.png"
METRICS_PATH = OUT / "apartment_floor_plan_metrics.json"

SCALE = 1000.0
FLOOR_HEIGHT = 160.0
WALL_HEIGHT = 2800.0
OUTER_WALL = 180.0
INNER_WALL = 120.0
JOIN_Z = 120.0


def mm(value_m: float) -> float:
    return value_m * SCALE


def placed_box(
    model: cad.Model,
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    height: float,
) -> cad.Shape:
    shape = model.box(mm(width), mm(depth), height)
    return model.translate(shape, mm(x), mm(y), z)


def horizontal_wall(
    model: cad.Model,
    x1: float,
    x2: float,
    y: float,
    *,
    thickness: float,
    height: float = WALL_HEIGHT,
) -> cad.Shape:
    return placed_box(model, x1, y - thickness / 2000.0, JOIN_Z, x2 - x1, thickness / 1000.0, height)


def vertical_wall(
    model: cad.Model,
    x: float,
    y1: float,
    y2: float,
    *,
    thickness: float,
    height: float = WALL_HEIGHT,
) -> cad.Shape:
    return placed_box(model, x - thickness / 2000.0, y1, JOIN_Z, thickness / 1000.0, y2 - y1, height)


def add_door(
    model: cad.Model,
    body: cad.Shape,
    x: float,
    y: float,
    *,
    length: float = 0.78,
    angle: float = 45.0,
) -> cad.Shape:
    panel = model.box(mm(length), 45.0, 2050.0)
    panel = model.rotate(panel, degrees=angle, axis=(0.0, 0.0, 1.0))
    panel = model.translate(panel, mm(x), mm(y), JOIN_Z)
    return model.union(body, panel)


def add_bed(
    model: cad.Model,
    body: cad.Shape,
    x: float,
    y: float,
    *,
    width: float = 1.65,
    depth: float = 2.15,
) -> cad.Shape:
    items = (
        placed_box(model, x, y, JOIN_Z, width, depth, 440.0),
        placed_box(model, x - 0.05, y + depth - 0.10, JOIN_Z, width + 0.10, 0.12, 900.0),
        placed_box(model, x + 0.14, y + depth - 0.42, 545.0, width * 0.34, 0.28, 110.0),
        placed_box(model, x + width * 0.52, y + depth - 0.42, 545.0, width * 0.34, 0.28, 110.0),
    )
    for item in items:
        body = model.union(body, item)
    return body


def add_sofa(model: cad.Model, body: cad.Shape) -> cad.Shape:
    items = (
        placed_box(model, 6.05, 0.28, JOIN_Z, 2.35, 0.72, 440.0),
        placed_box(model, 6.05, 0.25, JOIN_Z, 2.35, 0.18, 850.0),
        placed_box(model, 5.92, 0.25, JOIN_Z, 0.18, 0.78, 650.0),
        placed_box(model, 8.35, 0.25, JOIN_Z, 0.18, 0.78, 650.0),
        placed_box(model, 6.18, 0.44, 540.0, 1.02, 0.46, 150.0),
        placed_box(model, 7.25, 0.44, 540.0, 1.02, 0.46, 150.0),
    )
    for item in items:
        body = model.union(body, item)
    return body


def add_dining_set(model: cad.Model, body: cad.Shape) -> cad.Shape:
    items = [placed_box(model, 6.35, 1.65, JOIN_Z, 1.25, 0.80, 740.0)]
    for x, y, w, d in (
        (6.48, 1.30, 0.38, 0.34),
        (7.08, 1.30, 0.38, 0.34),
        (6.48, 2.46, 0.38, 0.34),
        (7.08, 2.46, 0.38, 0.34),
    ):
        items.append(placed_box(model, x, y, JOIN_Z, w, d, 470.0))
    for item in items:
        body = model.union(body, item)
    return body


def build_model() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    stages: dict[str, Any] = {}

    with cad.Model() as model:
        # The stepped floor reproduces the left-side bay and the lower room wing.
        floor = placed_box(model, 2.55, 0.00, 0.0, 9.45, 4.55, FLOOR_HEIGHT)
        floor = model.union(floor, placed_box(model, 0.00, 1.55, 0.0, 4.20, 3.00, FLOOR_HEIGHT))
        floor = model.union(floor, placed_box(model, 2.20, 4.30, 0.0, 9.80, 3.80, FLOOR_HEIGHT))
        body = floor
        stages["floor"] = {
            "volume_mm3": body.volume,
            "bbox_mm": list(body.bbox),
            "topology": dict(body.topology),
        }

        walls: list[cad.Shape] = []

        # Outer wall segments. Shorter 900 mm sill segments mark window bays.
        walls.extend(
            (
                horizontal_wall(model, 2.55, 5.75, 0.09, thickness=OUTER_WALL),
                horizontal_wall(model, 5.75, 8.65, 0.09, thickness=OUTER_WALL, height=900.0),
                horizontal_wall(model, 8.65, 12.0, 0.09, thickness=OUTER_WALL),
                vertical_wall(model, 11.91, 0.0, 2.95, thickness=OUTER_WALL, height=900.0),
                vertical_wall(model, 11.91, 2.95, 8.10, thickness=OUTER_WALL),
                horizontal_wall(model, 8.95, 12.0, 8.01, thickness=OUTER_WALL),
                horizontal_wall(model, 5.65, 8.95, 8.01, thickness=OUTER_WALL, height=900.0),
                horizontal_wall(model, 2.20, 5.65, 8.01, thickness=OUTER_WALL),
                vertical_wall(model, 2.29, 4.45, 8.10, thickness=OUTER_WALL),
                horizontal_wall(model, 0.0, 2.25, 4.46, thickness=OUTER_WALL),
                vertical_wall(model, 0.09, 1.55, 4.55, thickness=OUTER_WALL),
                horizontal_wall(model, 0.0, 2.60, 1.64, thickness=OUTER_WALL),
                vertical_wall(model, 2.64, 0.0, 1.60, thickness=OUTER_WALL),
            )
        )

        # Internal partitions are split at door openings.
        walls.extend(
            (
                vertical_wall(model, 2.35, 1.65, 3.15, thickness=INNER_WALL),
                vertical_wall(model, 2.35, 3.95, 4.48, thickness=INNER_WALL),
                horizontal_wall(model, 2.30, 3.15, 3.55, thickness=INNER_WALL),
                horizontal_wall(model, 3.90, 5.10, 3.55, thickness=INNER_WALL),
                vertical_wall(model, 4.15, 3.55, 4.45, thickness=INNER_WALL),
                horizontal_wall(model, 2.28, 4.02, 4.42, thickness=INNER_WALL),
                horizontal_wall(model, 4.82, 7.18, 4.42, thickness=INNER_WALL),
                horizontal_wall(model, 7.96, 9.15, 4.42, thickness=INNER_WALL),
                vertical_wall(model, 5.25, 5.15, 8.02, thickness=INNER_WALL),
                vertical_wall(model, 7.45, 4.42, 5.24, thickness=INNER_WALL),
                vertical_wall(model, 7.45, 6.02, 8.02, thickness=INNER_WALL),
                vertical_wall(model, 9.05, 5.22, 8.02, thickness=INNER_WALL),
                horizontal_wall(model, 7.45, 9.05, 5.55, thickness=INNER_WALL),
                horizontal_wall(model, 7.45, 9.05, 6.70, thickness=INNER_WALL),
            )
        )

        for wall in walls:
            body = model.union(body, wall)
        stages["walls"] = {
            "count": len(walls),
            "volume_mm3": body.volume,
            "topology": dict(body.topology),
        }

        # Door leaves make the circulation pattern legible in the top view.
        for door in (
            (2.35, 3.16, 0.78, 90.0),
            (3.16, 3.55, 0.78, -45.0),
            (4.02, 4.42, 0.78, 45.0),
            (5.25, 5.15, 0.78, 90.0),
            (7.45, 5.24, 0.78, 90.0),
            (8.25, 4.42, 0.78, 45.0),
            (9.05, 5.22, 0.78, 90.0),
        ):
            body = add_door(model, body, door[0], door[1], length=door[2], angle=door[3])

        # Kitchen run and island in the upper-left portion of the main room.
        for item in (
            placed_box(model, 2.85, 0.25, JOIN_Z, 2.35, 0.62, 900.0),
            placed_box(model, 2.85, 0.82, JOIN_Z, 0.62, 1.00, 900.0),
            placed_box(model, 3.55, 0.40, 990.0, 0.65, 0.36, 65.0),
            placed_box(model, 4.38, 0.38, 990.0, 0.42, 0.40, 65.0),
            placed_box(model, 3.20, 2.62, JOIN_Z, 1.40, 0.62, 900.0),
        ):
            body = model.union(body, item)

        body = add_sofa(model, body)
        body = add_dining_set(model, body)

        # Living-room console and side chairs.
        for item in (
            placed_box(model, 6.35, 3.65, JOIN_Z, 1.75, 0.38, 520.0),
            placed_box(model, 5.35, 0.45, JOIN_Z, 0.48, 0.60, 620.0),
            placed_box(model, 8.70, 0.45, JOIN_Z, 0.48, 0.60, 620.0),
            placed_box(model, 5.85, 2.08, JOIN_Z, 0.60, 0.60, 430.0),
        ):
            body = model.union(body, item)

        # Left utility/bath bay.
        for item in (
            placed_box(model, 0.55, 1.92, JOIN_Z, 1.15, 0.70, 700.0),
            placed_box(model, 0.52, 3.72, JOIN_Z, 1.10, 0.48, 860.0),
            placed_box(model, 1.72, 3.68, JOIN_Z, 0.42, 0.42, 430.0),
            placed_box(model, 3.34, 3.78, JOIN_Z, 0.48, 0.48, 460.0),
        ):
            body = model.union(body, item)

        # Three sleeping zones and the compact centre-right washroom.
        body = add_bed(model, body, 2.65, 5.45, width=1.72, depth=2.20)
        body = add_bed(model, body, 5.50, 5.55, width=1.55, depth=2.10)
        body = add_bed(model, body, 9.55, 5.50, width=1.70, depth=2.18)
        for item in (
            placed_box(model, 4.48, 6.80, JOIN_Z, 0.48, 0.48, 520.0),
            placed_box(model, 7.72, 5.82, JOIN_Z, 0.46, 0.72, 690.0),
            placed_box(model, 8.34, 5.80, JOIN_Z, 0.42, 0.48, 430.0),
            placed_box(model, 9.15, 6.90, JOIN_Z, 0.32, 0.62, 520.0),
        ):
            body = model.union(body, item)

        final = body
        validation = final.validate().to_dict()
        topology = final.topology
        if topology["solids"] != 1:
            raise AssertionError(f"expected one connected model, got {topology}")
        if validation["status"] != "valid":
            raise AssertionError(validation)

        final.export_step(str(STEP_PATH))
        final.export_stl(str(STL_PATH), binary=True)
        mesh = final.mesh(deflection=35.0)
        metrics = {
            "units": "millimetres",
            "source": "proportional reconstruction from screenshot; not a measured construction drawing",
            "nominal_envelope_m": [12.0, 8.1],
            "wall_height_mm": WALL_HEIGHT,
            "outer_wall_mm": OUTER_WALL,
            "inner_wall_mm": INNER_WALL,
            "final": {
                "kind": final.kind,
                "volume_mm3": final.volume,
                "area_mm2": final.area,
                "bbox_mm": list(final.bbox),
                "topology": dict(topology),
                "mesh_vertices": len(mesh.get("vertices", [])) // 3,
                "mesh_triangles": len(mesh.get("triangles", [])) // 3,
            },
            "stages": stages,
            "outputs": {
                "step": str(STEP_PATH.resolve()),
                "stl": str(STL_PATH.resolve()),
                "png": str(PNG_PATH.resolve()),
            },
        }

    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return metrics


def render() -> None:
    from cadflow.inspect import brep

    brep.render_step_views_rpath(
        step_path=STEP_PATH,
        output_path=PNG_PATH,
        title="轴测几何",
        views=(
            (31.0, -52.0, ""),
            (90.0, -90.0, "俯视平面"),
        ),
        image_size=(18.0, 8.5),
        dpi=180,
        background_color=(0.965, 0.972, 0.980),
        font_file="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        linear_deflection=28.0,
        angular_deflection=0.20,
        show_brep_edges=True,
    )


def main() -> None:
    metrics = build_model()
    render()
    for path in (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")
    print("final", json.dumps(metrics["final"], sort_keys=True))
    for path in (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH):
        print("output", path.resolve(), path.stat().st_size)


if __name__ == "__main__":
    main()
