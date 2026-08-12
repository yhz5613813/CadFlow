"""Model the flexible short-sleeve jumpsuit shown in the design sheet.

The source is a proportion drawing without measurements. This reconstruction
uses nominal women's sample-garment dimensions in millimetres. Flexible cloth
is represented by hollow, high-segment ruled lofts: each circumferential
segment and each section interval remains an explicit BREP face.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

import cadflow as cad


OUT = Path("examples/out/cadflow_flexible_jumpsuit")
STEP_PATH = OUT / "flexible_jumpsuit.step"
STL_PATH = OUT / "flexible_jumpsuit.stl"
PNG_PATH = OUT / "flexible_jumpsuit_views.png"
METRICS_PATH = OUT / "flexible_jumpsuit_metrics.json"

CLOTH_THICKNESS = 5.0
BOOLEAN_OVERLAP = 4.0
TAU = 2.0 * math.pi


def _ellipse_wire_z(
    model: cad.Model,
    *,
    z: float,
    center_x: float,
    radius_x: float,
    radius_y: float,
    segments: int,
    ripple: float,
    phase: float,
) -> cad.Shape:
    points = []
    for index in range(segments):
        angle = TAU * index / segments
        fold = 1.0 + ripple * (
            0.62 * math.sin(6.0 * angle + phase)
            + 0.38 * math.sin(10.0 * angle - phase * 0.7)
        )
        points.append(
            (
                center_x + radius_x * fold * math.cos(angle),
                radius_y * fold * math.sin(angle),
                z,
            )
        )
    return model.polyline(points, closed=True)


def _hollow_vertical_loft(
    model: cad.Model,
    sections: Sequence[tuple[float, float, float, float]],
    *,
    segments: int,
    ripple: float,
    phase_step: float = 0.42,
    thickness: float = CLOTH_THICKNESS,
) -> cad.Shape:
    """Create an open-ended thin cloth shell along the Z axis.

    Section tuples are (z, center_x, radius_x, radius_y).
    """
    outer_profiles = [
        _ellipse_wire_z(
            model,
            z=z,
            center_x=center_x,
            radius_x=radius_x,
            radius_y=radius_y,
            segments=segments,
            ripple=ripple,
            phase=index * phase_step,
        )
        for index, (z, center_x, radius_x, radius_y) in enumerate(sections)
    ]
    outer = model.loft(outer_profiles, solid=True, ruled=True)

    inner_sections = list(sections)
    inner_sections[0] = (
        inner_sections[0][0] - 12.0,
        inner_sections[0][1],
        inner_sections[0][2],
        inner_sections[0][3],
    )
    inner_sections[-1] = (
        inner_sections[-1][0] + 12.0,
        inner_sections[-1][1],
        inner_sections[-1][2],
        inner_sections[-1][3],
    )
    inner_profiles = [
        _ellipse_wire_z(
            model,
            z=z,
            center_x=center_x,
            radius_x=radius_x - thickness,
            radius_y=radius_y - thickness,
            segments=segments,
            ripple=ripple,
            phase=index * phase_step,
        )
        for index, (z, center_x, radius_x, radius_y) in enumerate(inner_sections)
    ]
    inner = model.loft(inner_profiles, solid=True, ruled=True)
    return model.cut(outer, inner)


def _ellipse_wire_x(
    model: cad.Model,
    *,
    x: float,
    center_z: float,
    radius_y: float,
    radius_z: float,
    segments: int,
    ripple: float,
    phase: float,
) -> cad.Shape:
    points = []
    for index in range(segments):
        angle = TAU * index / segments
        fold = 1.0 + ripple * math.sin(7.0 * angle + phase)
        points.append(
            (
                x,
                radius_y * fold * math.cos(angle),
                center_z + radius_z * fold * math.sin(angle),
            )
        )
    return model.polyline(points, closed=True)


def _hollow_sleeve(
    model: cad.Model,
    sections: Sequence[tuple[float, float, float, float]],
    *,
    segments: int = 28,
    thickness: float = CLOTH_THICKNESS,
) -> cad.Shape:
    """Create one open-ended sleeve along X.

    Section tuples are (x, center_z, radius_y, radius_z).
    """
    outer_profiles = [
        _ellipse_wire_x(
            model,
            x=x,
            center_z=center_z,
            radius_y=radius_y,
            radius_z=radius_z,
            segments=segments,
            ripple=0.018,
            phase=index * 0.55,
        )
        for index, (x, center_z, radius_y, radius_z) in enumerate(sections)
    ]
    outer = model.loft(outer_profiles, solid=True, ruled=True)

    direction = 1.0 if sections[-1][0] > sections[0][0] else -1.0
    inner_sections = list(sections)
    inner_sections[0] = (
        inner_sections[0][0] - direction * 12.0,
        *inner_sections[0][1:],
    )
    inner_sections[-1] = (
        inner_sections[-1][0] + direction * 12.0,
        *inner_sections[-1][1:],
    )
    inner_profiles = [
        _ellipse_wire_x(
            model,
            x=x,
            center_z=center_z,
            radius_y=radius_y - thickness,
            radius_z=radius_z - thickness,
            segments=segments,
            ripple=0.018,
            phase=index * 0.55,
        )
        for index, (x, center_z, radius_y, radius_z) in enumerate(inner_sections)
    ]
    inner = model.loft(inner_profiles, solid=True, ruled=True)
    return model.cut(outer, inner)


def _xz_prism(
    model: cad.Model,
    points: Sequence[tuple[float, float]],
    *,
    front_y: float,
    depth: float,
) -> cad.Shape:
    wire = model.polyline(tuple((x, front_y, z) for x, z in points), closed=True)
    return model.extrude(model.face(wire), x=0.0, y=depth, z=0.0)


def _box(
    model: cad.Model,
    *,
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    height: float,
) -> cad.Shape:
    return model.translate(model.box(width, depth, height), x=x, y=y, z=z)


def _collect(model: cad.Model, shapes: Sequence[cad.Shape]) -> cad.Shape:
    combined = shapes[0]
    for shape in shapes[1:]:
        combined = model.union(combined, shape)
    return combined


def _record(shape: cad.Shape) -> dict[str, Any]:
    return {
        "kind": shape.kind,
        "volume_mm3": shape.volume,
        "area_mm2": shape.area,
        "bbox_mm": list(shape.bbox),
        "topology": dict(shape.topology),
    }


def build_garment() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    stages: dict[str, Any] = {}

    with cad.Model() as model:
        torso = _hollow_vertical_loft(
            model,
            (
                (982.0, 0.0, 244.0, 140.0),
                (1025.0, 0.0, 282.0, 158.0),
                (1100.0, 0.0, 315.0, 170.0),
                (1260.0, 0.0, 330.0, 178.0),
                (1415.0, 0.0, 341.0, 181.0),
                (1515.0, 0.0, 326.0, 172.0),
                (1575.0, 0.0, 235.0, 142.0),
                (1610.0, 0.0, 132.0, 96.0),
            ),
            segments=36,
            ripple=0.022,
        )
        stages["torso_shell"] = _record(torso)

        pelvis = _hollow_vertical_loft(
            model,
            (
                (750.0, 0.0, 266.0, 158.0),
                (820.0, 0.0, 286.0, 166.0),
                (900.0, 0.0, 282.0, 162.0),
                (975.0, 0.0, 260.0, 151.0),
                (1022.0, 0.0, 246.0, 143.0),
            ),
            segments=36,
            ripple=0.018,
            phase_step=0.33,
        )
        stages["pelvis_shell"] = _record(pelvis)

        left_leg = _hollow_vertical_loft(
            model,
            (
                (28.0, -214.0, 202.0, 132.0),
                (105.0, -210.0, 199.0, 136.0),
                (330.0, -194.0, 184.0, 145.0),
                (580.0, -176.0, 166.0, 151.0),
                (720.0, -158.0, 143.0, 154.0),
                (810.0, -142.0, 139.0, 157.0),
                (910.0, -132.0, 153.0, 157.0),
                (1010.0, -124.0, 158.0, 146.0),
            ),
            segments=34,
            ripple=0.026,
            phase_step=0.58,
        )
        right_leg = _hollow_vertical_loft(
            model,
            (
                (28.0, 214.0, 202.0, 132.0),
                (105.0, 210.0, 199.0, 136.0),
                (330.0, 194.0, 184.0, 145.0),
                (580.0, 176.0, 166.0, 151.0),
                (720.0, 158.0, 143.0, 154.0),
                (810.0, 142.0, 139.0, 157.0),
                (910.0, 132.0, 153.0, 157.0),
                (1010.0, 124.0, 158.0, 146.0),
            ),
            segments=34,
            ripple=0.026,
            phase_step=0.58,
        )
        stages["left_leg_shell"] = _record(left_leg)
        stages["right_leg_shell"] = _record(right_leg)

        left_sleeve = _hollow_sleeve(
            model,
            (
                (-246.0, 1490.0, 152.0, 104.0),
                (-310.0, 1470.0, 158.0, 114.0),
                (-390.0, 1415.0, 166.0, 126.0),
                (-485.0, 1350.0, 172.0, 120.0),
            ),
        )
        right_sleeve = _hollow_sleeve(
            model,
            (
                (246.0, 1490.0, 152.0, 104.0),
                (310.0, 1470.0, 158.0, 114.0),
                (390.0, 1415.0, 166.0, 126.0),
                (485.0, 1350.0, 172.0, 120.0),
            ),
        )
        stages["left_sleeve_shell"] = _record(left_sleeve)
        stages["right_sleeve_shell"] = _record(right_sleeve)
        stages["shell_distances_mm"] = {
            "torso_to_pelvis": torso.distance_to(pelvis),
            "torso_to_left_sleeve": torso.distance_to(left_sleeve),
            "torso_to_right_sleeve": torso.distance_to(right_sleeve),
            "pelvis_to_left_leg": pelvis.distance_to(left_leg),
            "pelvis_to_right_leg": pelvis.distance_to(right_leg),
            "left_leg_to_right_leg": left_leg.distance_to(right_leg),
        }
        print("shell_distances", json.dumps(stages["shell_distances_mm"], sort_keys=True))

        waistband = _hollow_vertical_loft(
            model,
            (
                (970.0, 0.0, 254.0, 150.0),
                (1005.0, 0.0, 248.0, 146.0),
                (1040.0, 0.0, 252.0, 149.0),
            ),
            segments=36,
            ripple=0.035,
            phase_step=0.70,
            thickness=8.0,
        )

        collar = _hollow_vertical_loft(
            model,
            (
                (1582.0, 0.0, 140.0, 101.0),
                (1625.0, 0.0, 126.0, 93.0),
                (1682.0, 0.0, 112.0, 84.0),
            ),
            segments=32,
            ripple=0.006,
            phase_step=0.20,
            thickness=6.0,
        )

        # Front details overlap the front cloth surface by a few millimetres.
        zipper = _box(
            model,
            x=-7.0,
            y=-184.0,
            z=1032.0,
            width=14.0,
            depth=14.0,
            height=514.0,
        )
        pocket = _xz_prism(
            model,
            ((72.0, 1260.0), (218.0, 1260.0), (218.0, 1450.0), (72.0, 1450.0)),
            front_y=-184.0,
            depth=13.0,
        )
        pocket_flap = _xz_prism(
            model,
            ((64.0, 1440.0), (226.0, 1440.0), (212.0, 1472.0), (78.0, 1472.0)),
            front_y=-187.0,
            depth=15.0,
        )
        left_lapel = _xz_prism(
            model,
            ((-124.0, 1594.0), (-20.0, 1524.0), (-92.0, 1435.0), (-166.0, 1530.0)),
            front_y=-177.0,
            depth=16.0,
        )
        right_lapel = _xz_prism(
            model,
            ((124.0, 1594.0), (20.0, 1524.0), (92.0, 1435.0), (166.0, 1530.0)),
            front_y=-177.0,
            depth=16.0,
        )

        # Belt knot and two hanging ties reproduce the strong blue waist detail.
        belt_knot = _box(
            model,
            x=-38.0,
            y=-174.0,
            z=975.0,
            width=76.0,
            depth=34.0,
            height=64.0,
        )
        left_tie = _xz_prism(
            model,
            ((-30.0, 1002.0), (-2.0, 996.0), (-62.0, 755.0), (-112.0, 798.0)),
            front_y=-172.0,
            depth=24.0,
        )
        right_tie = _xz_prism(
            model,
            ((8.0, 996.0), (38.0, 1002.0), (84.0, 815.0), (42.0, 772.0)),
            front_y=-172.0,
            depth=24.0,
        )

        # Narrow diagonal welt pockets on the trouser front.
        left_welt = _xz_prism(
            model,
            ((-228.0, 905.0), (-208.0, 917.0), (-260.0, 735.0), (-278.0, 724.0)),
            front_y=-165.0,
            depth=18.0,
        )
        right_welt = _xz_prism(
            model,
            ((228.0, 905.0), (208.0, 917.0), (260.0, 735.0), (278.0, 724.0)),
            front_y=-165.0,
            depth=18.0,
        )

        # Back waist elastic blocks add the gathered detail visible in the rear view.
        back_elastic_left = _box(
            model,
            x=-218.0,
            y=139.0,
            z=982.0,
            width=180.0,
            depth=24.0,
            height=58.0,
        )
        back_elastic_right = _box(
            model,
            x=38.0,
            y=139.0,
            z=982.0,
            width=180.0,
            depth=24.0,
            height=58.0,
        )

        parts = (
            torso,
            pelvis,
            left_leg,
            right_leg,
            left_sleeve,
            right_sleeve,
            waistband,
            collar,
            zipper,
            pocket,
            pocket_flap,
            left_lapel,
            right_lapel,
            belt_knot,
            left_tie,
            right_tie,
            left_welt,
            right_welt,
            back_elastic_left,
            back_elastic_right,
        )
        final = _collect(model, parts)
        validation = final.validate().to_dict()
        mesh = final.mesh(deflection=2.5)
        final_metrics = _record(final)
        final_metrics["mesh"] = {
            "deflection_mm": 2.5,
            "vertices": len(mesh.get("vertices", [])) // 3,
            "triangles": len(mesh.get("triangles", [])) // 3,
        }

        bbox = final.bbox
        if bbox[3] - bbox[0] < 950.0 or bbox[5] - bbox[2] < 1640.0:
            raise AssertionError(f"unexpected garment envelope: {bbox}")
        if final.topology["faces"] < 900:
            raise AssertionError(f"flexible model has too few faces: {final.topology}")
        if not 1 <= final.topology["solids"] <= 6:
            raise AssertionError(f"unexpected sewn-shell count: {final.topology}")
        if validation["status"] != "valid":
            raise AssertionError(validation)

        final.export_step(str(STEP_PATH))
        final.export_stl(str(STL_PATH), binary=True)

    metrics: dict[str, Any] = {
        "units": "millimetres",
        "coordinate_frame": {
            "x": "wearer's left/right",
            "y": "front/back; negative Y is front",
            "z": "vertical; floor at Z=0",
        },
        "source_interpretation": "proportional reconstruction from an undimensioned fashion design sheet",
        "nominal_measurements": {
            "garment_height": 1682.0,
            "approximate_chest_circumference": 1040.0,
            "approximate_waist_circumference": 790.0,
            "approximate_hip_circumference": 1000.0,
            "short_sleeve_span": 970.0,
            "cloth_thickness": CLOTH_THICKNESS,
        },
        "flexible_surface_strategy": {
            "construction": "open-ended hollow ruled lofts with rippled polygon sections",
            "torso_segments": 36,
            "trouser_leg_segments": 34,
            "sleeve_segments": 28,
            "reason": "preserve many explicit panels/faces for a flexible-cloth appearance",
            "sewn_shell_policy": "retain touching shells instead of adding rigid internal bridges",
        },
        "feature_sequence": [
            "hollow torso shell",
            "hollow pelvis and two wide trouser legs",
            "two hollow short sleeves",
            "gathered waistband and stand/fold collar",
            "front zipper, chest pocket, pocket flap and lapels",
            "belt knot, hanging ties and trouser welt pockets",
            "rear elastic gathering blocks",
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
        title="前轴测",
        views=(
            (12.0, -62.0, ""),
            (0.0, -90.0, "正面"),
            (12.0, 118.0, "后轴测"),
            (0.0, 90.0, "背面"),
        ),
        image_size=(18.0, 12.0),
        dpi=180,
        background_color=(0.965, 0.972, 0.980),
        font_file="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        linear_deflection=2.2,
        angular_deflection=0.18,
        show_brep_edges=True,
    )


def main() -> None:
    metrics = build_garment()
    render_views()
    for path in (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")
    print("final", json.dumps(metrics["final"], sort_keys=True))
    for path in (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH):
        print("output", path.resolve(), path.stat().st_size)


if __name__ == "__main__":
    main()
