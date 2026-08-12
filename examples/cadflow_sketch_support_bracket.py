"""Reconstruct the dimensioned support bracket from the supplied hand sketch.

Coordinate frame:
    X: horizontal direction in the sketch
    Y: part thickness, extruded away from the sketch plane
    Z: vertical direction in the sketch

All dimensions are millimetres. The slot's lower centre X coordinate and the
part thickness are not explicitly dimensioned in the sketch, so both are
recorded as modelling assumptions in the generated metrics file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import cadflow as cad


OUTPUT_DIR = Path("examples/out/cadflow_sketch_support_bracket")
STEP_PATH = OUTPUT_DIR / "sketch_support_bracket.step"
STL_PATH = OUTPUT_DIR / "sketch_support_bracket.stl"
PNG_PATH = OUTPUT_DIR / "sketch_support_bracket_views.png"
METRICS_PATH = OUTPUT_DIR / "sketch_support_bracket_metrics.json"

# Dimensions read from the sketch.
BASE_WIDTH = 69.0
BASE_HEIGHT = 9.0
PART_THICKNESS = 6.0
HEAD_CENTER = (45.0, 69.0)
HEAD_RADIUS = 18.0
BORE_RADIUS = 9.0
WEB_RIGHT_X = 57.0
BASE_OVERHANG = 6.0
PROFILE_BLEND_RADIUS = 3.0
SLOT_RADIUS = 4.3
SLOT_CENTRE_DISTANCE = 15.0
SLOT_LOWER_CENTRE = (25.0, BASE_HEIGHT + 12.0)

QUERY_TOLERANCE = 0.1
BOOLEAN_OVERLAP = 0.25


def _circular_prism(
    model: cad.Model,
    *,
    radius: float,
    center_x: float,
    center_z: float,
    start_y: float,
    depth: float,
) -> cad.Shape:
    """Create a circular prism normal to the X-Z sketch plane."""
    profile = model.circle_profile(
        radius,
        center=(center_x, start_y, center_z),
        normal=(0.0, 1.0, 0.0),
    )
    return model.extrude(model.face(profile), x=0.0, y=depth, z=0.0)


def _profile_prism(
    model: cad.Model,
    points_xz: tuple[tuple[float, float], ...],
    *,
    start_y: float,
    depth: float,
) -> cad.Shape:
    wire = model.polyline(
        tuple((x, start_y, z) for x, z in points_xz),
        closed=True,
    )
    return model.extrude(model.face(wire), x=0.0, y=depth, z=0.0)


def _record(shape: cad.Shape) -> dict[str, Any]:
    return {
        "kind": shape.kind,
        "volume_mm3": shape.volume,
        "area_mm2": shape.area,
        "bbox_mm": list(shape.bbox),
        "topology": dict(shape.topology),
    }


def _left_tangent_point() -> tuple[float, float]:
    """Return the upper-left tangent from the base corner to the R18 head."""
    px, pz = 0.0, BASE_HEIGHT
    cx, cz = HEAD_CENTER
    vx, vz = px - cx, pz - cz
    distance_sq = vx * vx + vz * vz
    radial_scale = HEAD_RADIUS * HEAD_RADIUS / distance_sq
    tangent_scale = HEAD_RADIUS * math.sqrt(distance_sq - HEAD_RADIUS**2) / distance_sq
    return (
        cx + radial_scale * vx + tangent_scale * vz,
        cz + radial_scale * vz - tangent_scale * vx,
    )


def _blend_geometry() -> tuple[tuple[float, float], tuple[float, float]]:
    """Solve the R3 arc centre and its tangency point on the R18 head."""
    cx, cz = HEAD_CENTER
    blend_cx = WEB_RIGHT_X - PROFILE_BLEND_RADIUS
    centre_distance = HEAD_RADIUS + PROFILE_BLEND_RADIUS
    dx = blend_cx - cx
    blend_cz = cz - math.sqrt(centre_distance**2 - dx**2)
    scale = HEAD_RADIUS / centre_distance
    tangent = (cx + scale * dx, cz + scale * (blend_cz - cz))
    return (blend_cx, blend_cz), tangent


def _inset_toward_head(point: tuple[float, float]) -> tuple[float, float]:
    cx, cz = HEAD_CENTER
    vx, vz = cx - point[0], cz - point[1]
    length = math.hypot(vx, vz)
    return (
        point[0] + BOOLEAN_OVERLAP * vx / length,
        point[1] + BOOLEAN_OVERLAP * vz / length,
    )


def _make_slot_tool(model: cad.Model) -> tuple[cad.Shape, tuple[float, float]]:
    lower_x, lower_z = SLOT_LOWER_CENTRE
    head_dx = HEAD_CENTER[0] - lower_x
    head_dz = HEAD_CENTER[1] - lower_z
    direction_length = math.hypot(head_dx, head_dz)
    ux, uz = head_dx / direction_length, head_dz / direction_length
    upper = (
        lower_x + SLOT_CENTRE_DISTANCE * ux,
        lower_z + SLOT_CENTRE_DISTANCE * uz,
    )
    nx, nz = -uz * SLOT_RADIUS, ux * SLOT_RADIUS

    start_y = -1.0
    depth = PART_THICKNESS + 2.0
    connector = _profile_prism(
        model,
        (
            (lower_x + nx, lower_z + nz),
            (upper[0] + nx, upper[1] + nz),
            (upper[0] - nx, upper[1] - nz),
            (lower_x - nx, lower_z - nz),
        ),
        start_y=start_y,
        depth=depth,
    )
    lower_end = _circular_prism(
        model,
        radius=SLOT_RADIUS,
        center_x=lower_x,
        center_z=lower_z,
        start_y=start_y,
        depth=depth,
    )
    upper_end = _circular_prism(
        model,
        radius=SLOT_RADIUS,
        center_x=upper[0],
        center_z=upper[1],
        start_y=start_y,
        depth=depth,
    )
    slot_with_lower_end = model.union(connector, lower_end)
    return model.union(slot_with_lower_end, upper_end), upper


def build_part() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stages: dict[str, Any] = {}

    left_tangent = _left_tangent_point()
    blend_center, head_blend_tangent = _blend_geometry()
    left_overlap = _inset_toward_head(left_tangent)
    blend_overlap = _inset_toward_head(head_blend_tangent)

    with cad.Model() as model:
        stages["capabilities"] = model.capabilities()

        base = model.box(BASE_WIDTH, PART_THICKNESS, BASE_HEIGHT)
        stages["01_base"] = _record(base)

        # The two inset points give the web/head boolean a small positive-area
        # overlap while the visible outline remains governed by the R18 head.
        web = _profile_prism(
            model,
            (
                (0.0, BASE_HEIGHT),
                (WEB_RIGHT_X, BASE_HEIGHT),
                (WEB_RIGHT_X, blend_center[1]),
                blend_center,
                blend_overlap,
                left_overlap,
            ),
            start_y=0.0,
            depth=PART_THICKNESS,
        )
        body_with_web = model.union(base, web)
        stages["02_base_plus_web"] = _record(body_with_web)
        if body_with_web.topology["solids"] != 1 or body_with_web.volume <= base.volume:
            raise AssertionError("base/web union did not produce one larger solid")

        head = _circular_prism(
            model,
            radius=HEAD_RADIUS,
            center_x=HEAD_CENTER[0],
            center_z=HEAD_CENTER[1],
            start_y=0.0,
            depth=PART_THICKNESS,
        )
        body_with_head = model.union(body_with_web, head)
        stages["03_plus_r18_head"] = _record(body_with_head)
        if body_with_head.topology["solids"] != 1 or body_with_head.volume <= body_with_web.volume:
            raise AssertionError("web/head union did not produce one larger solid")

        transition = _circular_prism(
            model,
            radius=PROFILE_BLEND_RADIUS,
            center_x=blend_center[0],
            center_z=blend_center[1],
            start_y=0.0,
            depth=PART_THICKNESS,
        )
        outer_body = model.union(body_with_head, transition)
        stages["04_plus_r3_transition"] = _record(outer_body)
        if outer_body.topology["solids"] != 1 or outer_body.volume <= body_with_head.volume:
            raise AssertionError("R3 transition union did not produce one larger solid")

        bore_tool = _circular_prism(
            model,
            radius=BORE_RADIUS,
            center_x=HEAD_CENTER[0],
            center_z=HEAD_CENTER[1],
            start_y=-1.0,
            depth=PART_THICKNESS + 2.0,
        )
        body_with_bore = model.cut(outer_body, bore_tool)
        stages["05_r9_bore_cut"] = _record(body_with_bore)

        slot_tool, slot_upper_centre = _make_slot_tool(model)
        final_part = model.cut(body_with_bore, slot_tool)
        stages["06_slot_cut"] = _record(final_part)

        validation = final_part.validate().to_dict()
        final_metrics = _record(final_part)
        mesh = final_part.mesh(deflection=0.12)
        vertex_values = mesh.get("vertices", [])
        triangle_indices = mesh.get("triangles", [])
        final_metrics["mesh"] = {
            "vertices": len(vertex_values) // 3,
            "triangles": len(triangle_indices) // 3,
            "deflection_mm": 0.12,
        }

        bbox = final_part.bbox
        expected_bbox = (0.0, 0.0, 0.0, BASE_WIDTH, PART_THICKNESS, 87.0)
        for actual, expected in zip(bbox, expected_bbox):
            if abs(actual - expected) > QUERY_TOLERANCE:
                raise AssertionError(f"bbox mismatch: actual={bbox}, expected={expected_bbox}")
        if final_part.topology["solids"] != 1:
            raise AssertionError(f"expected one solid: {final_part.topology}")
        if validation["status"] != "valid":
            raise AssertionError(f"CadFlow validation failed: {validation}")

        final_part.export_step(str(STEP_PATH))
        final_part.export_stl(str(STL_PATH), binary=True)

    metrics: dict[str, Any] = {
        "units": "millimetres",
        "coordinate_frame": {
            "origin": "left-bottom-front corner of base",
            "x": "sketch horizontal / base width",
            "y": "part thickness",
            "z": "sketch vertical",
        },
        "dimensions": {
            "base_width": BASE_WIDTH,
            "base_height": BASE_HEIGHT,
            "part_thickness_assumed": PART_THICKNESS,
            "head_center": list(HEAD_CENTER),
            "head_outer_radius": HEAD_RADIUS,
            "head_bore_radius": BORE_RADIUS,
            "web_right_x": WEB_RIGHT_X,
            "base_overhang": BASE_OVERHANG,
            "profile_blend_radius": PROFILE_BLEND_RADIUS,
            "slot_end_radius": SLOT_RADIUS,
            "slot_centre_distance": SLOT_CENTRE_DISTANCE,
            "slot_lower_centre_assumed": list(SLOT_LOWER_CENTRE),
            "slot_upper_centre": list(slot_upper_centre),
        },
        "construction": {
            "left_head_tangent": list(left_tangent),
            "r3_blend_center": list(blend_center),
            "r18_r3_tangent": list(head_blend_tangent),
            "boolean_overlap_mm": BOOLEAN_OVERLAP,
        },
        "assumptions": [
            "The unlabelled part thickness is 6 mm, matching the repeated 6 mm sketch dimension.",
            "The slot lower centre X coordinate is 25 mm; its Z coordinate is fixed by the shown 12 mm dimension.",
            "The slot axis points from its lower centre toward the R18 head centre.",
            "The lower-right R3 callout is interpreted as a profile transition tangent to the R18 head and X=57 web edge.",
        ],
        "validation": validation,
        "final": final_metrics,
        "stages": stages,
        "outputs": {
            "step": str(STEP_PATH.resolve()),
            "stl": str(STL_PATH.resolve()),
            "png": str(PNG_PATH.resolve()),
            "metrics": str(METRICS_PATH.resolve()),
        },
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return metrics


def render_views() -> None:
    from cadflow.inspect import brep

    brep.render_step_views_rpath(
        step_path=STEP_PATH,
        output_path=PNG_PATH,
        title="轴测图",
        views=(
            (28.0, -45.0, ""),
            (0.0, -90.0, "主视图 / X-Z"),
            (90.0, -90.0, "俯视图 / X-Y"),
            (0.0, 0.0, "右视图 / Y-Z"),
        ),
        image_size=(18.0, 12.0),
        dpi=180,
        background_color=(0.96, 0.97, 0.98),
        font_file="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        linear_deflection=0.08,
        angular_deflection=0.16,
        show_brep_edges=False,
    )


def main() -> None:
    metrics = build_part()
    render_views()
    for path in (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")

    print("final", json.dumps(metrics["final"], sort_keys=True))
    for path in (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH):
        print("output", path.resolve(), path.stat().st_size)


if __name__ == "__main__":
    main()
