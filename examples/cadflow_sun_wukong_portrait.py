"""Build and render a detailed geometric portrait of Sun Wukong."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import cadflow as cad


OUTPUT_DIR = Path("examples/out/cadflow_sun_wukong_portrait")
STEP_PATH = OUTPUT_DIR / "sun_wukong_portrait.step"
STL_PATH = OUTPUT_DIR / "sun_wukong_portrait.stl"
PNG_PATH = OUTPUT_DIR / "sun_wukong_portrait.png"
METRICS_PATH = OUTPUT_DIR / "sun_wukong_portrait_metrics.json"


def _ground(shape: cad.Shape, label: str) -> None:
    print(
        label,
        json.dumps(
            {
                "kind": shape.kind,
                "volume": shape.volume,
                "bbox": shape.bbox,
            },
            sort_keys=True,
        ),
    )


def _union(model: cad.Model, body: cad.Shape, feature: cad.Shape, label: str) -> cad.Shape:
    result = model.union(body, feature)
    _ground(result, label)
    return result


def _cut(model: cad.Model, body: cad.Shape, tool: cad.Shape, label: str) -> cad.Shape:
    result = model.cut(body, tool)
    _ground(result, label)
    return result


def _oriented_cone(
    model: cad.Model,
    *,
    radius1: float,
    radius2: float,
    height: float,
    position: tuple[float, float, float],
    tilt_axis: tuple[float, float, float] = (0.0, 1.0, 0.0),
    tilt_degrees: float = 0.0,
) -> cad.Shape:
    shape = model.cone(radius1=radius1, radius2=radius2, height=height)
    shape = model.translate(
        shape,
        x=position[0],
        y=position[1],
        z=position[2],
    )
    if tilt_degrees:
        shape = model.rotate(
            shape,
            degrees=tilt_degrees,
            axis=tilt_axis,
            origin=position,
        )
    return shape


def _ear(
    model: cad.Model,
    *,
    side: float,
    outer: bool,
) -> cad.Shape:
    sign = 1.0 if side > 0 else -1.0
    if outer:
        x_values = (sign * 27.0, sign * 34.0, sign * 39.0)
        radii = (9.0, 13.0, 8.0)
    elif sign < 0:
        x_values = (-39.5, -35.5, -32.0)
        radii = (5.0, 8.5, 5.0)
    else:
        x_values = (32.0, 35.5, 39.5)
        radii = (5.0, 8.5, 5.0)
    profiles = tuple(
        model.circle_profile(
            radius=radius,
            center=(x_value, -1.0, 38.0),
            normal=(1.0, 0.0, 0.0),
        )
        for x_value, radius in zip(x_values, radii)
    )
    return model.loft(profiles, solid=True, ruled=False)


def _make_headband(model: cad.Model) -> cad.Shape:
    profile = model.polyline(
        (
            (25.0, 0.0, 57.0),
            (32.0, 0.0, 57.0),
            (32.0, 0.0, 63.0),
            (25.0, 0.0, 63.0),
        ),
        closed=True,
    )
    face = model.face(profile)
    return model.revolve(
        face,
        degrees=360.0,
        axis=(0.0, 0.0, 1.0),
        origin=(0.0, 0.0, 0.0),
    )


def _make_hair_tufts(model: cad.Model) -> list[cad.Shape]:
    tufts: list[cad.Shape] = []
    for index in range(12):
        angle = math.radians(index * 30.0)
        radius = 25.0 + (1.0 if index % 2 else 0.0)
        position = (
            radius * math.cos(angle),
            radius * math.sin(angle),
            57.0,
        )
        tilt = 11.0 * math.sin(angle)
        tuft = _oriented_cone(
            model,
            radius1=4.2 if index % 3 else 4.8,
            radius2=0.75,
            height=13.0 + (index % 3),
            position=position,
            tilt_axis=(0.0, 1.0, 0.0),
            tilt_degrees=tilt,
        )
        tufts.append(tuft)
    return tufts


def _make_feather(
    model: cad.Model,
    *,
    position: tuple[float, float, float],
    height: float,
    tilt: float,
) -> cad.Shape:
    return _oriented_cone(
        model,
        radius1=4.2,
        radius2=0.35,
        height=height,
        position=position,
        tilt_axis=(0.0, 1.0, 0.0),
        tilt_degrees=tilt,
    )


def build_portrait() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    feature_stages: list[str] = []

    with cad.Model() as model:
        skull_profiles = tuple(
            model.circle_profile(
                radius=radius,
                center=(0.0, center_y, z_value),
                normal=(0.0, 0.0, 1.0),
            )
            for z_value, radius, center_y in (
                (4.0, 23.0, 1.0),
                (18.0, 31.0, 0.0),
                (43.0, 32.0, 0.0),
                (64.0, 25.0, 2.0),
            )
        )
        head = model.loft(skull_profiles, solid=True, ruled=False)
        feature_stages.append("skull_loft")
        _ground(head, "skull_loft")

        cheeks = (
            model.translate(model.sphere(radius=12.5), x=-14.0, y=-18.0, z=20.0),
            model.translate(model.sphere(radius=12.5), x=14.0, y=-18.0, z=20.0),
        )
        for index, cheek in enumerate(cheeks, start=1):
            head = _union(model, head, cheek, f"cheek_{index}")
        feature_stages.append("cheek_volumes")

        muzzle = model.translate(
            model.sphere(radius=11.5),
            x=0.0,
            y=-23.5,
            z=17.0,
        )
        head = _union(model, head, muzzle, "muzzle")
        feature_stages.append("muzzle")

        # Cut each inner-ear recess before attaching the outer ear to the skull.
        left_outer = _ear(model, side=-1.0, outer=True)
        right_outer = _ear(model, side=1.0, outer=True)
        left_recess = _ear(model, side=-1.0, outer=False)
        right_recess = _ear(model, side=1.0, outer=False)
        left_ear = model.cut(left_outer, left_recess)
        right_ear = model.cut(right_outer, right_recess)
        head = _union(model, head, left_ear, "left_ear")
        head = _union(model, head, right_ear, "right_ear")
        feature_stages.append("ears_with_inner_recesses")

        for side, x_value in (("left", -12.0), ("right", 12.0)):
            brow = model.translate(
                model.box(width=14.0, depth=6.0, height=4.5),
                x=x_value - 7.0,
                y=-31.0,
                z=35.5,
            )
            brow = model.rotate(
                brow,
                degrees=8.0 if x_value < 0 else -8.0,
                axis=(0.0, 1.0, 0.0),
                origin=(x_value, -28.0, 37.5),
            )
            head = _union(model, head, brow, f"{side}_brow")
        feature_stages.append("brow_ridges")

        nose_bridge = _oriented_cone(
            model,
            radius1=6.0,
            radius2=4.0,
            height=12.0,
            position=(0.0, -25.0, 27.0),
            tilt_axis=(1.0, 0.0, 0.0),
            tilt_degrees=90.0,
        )
        head = _union(model, head, nose_bridge, "nose_bridge")
        nose_tip = model.translate(
            model.sphere(radius=5.0),
            x=0.0,
            y=-34.0,
            z=23.0,
        )
        head = _union(model, head, nose_tip, "nose_tip")
        for side, x_value in (("left", -4.3), ("right", 4.3)):
            wing = model.translate(
                model.sphere(radius=4.5),
                x=x_value,
                y=-30.5,
                z=22.5,
            )
            head = _union(model, head, wing, f"{side}_nose_wing")
        feature_stages.append("nose_bridge_tip_wings")

        upper_lip = model.translate(
            model.box(width=15.0, depth=4.0, height=3.0),
            x=-7.5,
            y=-33.0,
            z=10.5,
        )
        lower_lip = model.translate(
            model.box(width=13.0, depth=4.0, height=3.0),
            x=-6.5,
            y=-32.0,
            z=6.5,
        )
        head = _union(model, head, upper_lip, "upper_lip")
        head = _union(model, head, lower_lip, "lower_lip")
        feature_stages.append("lips")

        goatee = _oriented_cone(
            model,
            radius1=5.0,
            radius2=0.8,
            height=12.0,
            position=(0.0, -25.0, 12.0),
            tilt_axis=(1.0, 0.0, 0.0),
            tilt_degrees=180.0,
        )
        head = _union(model, head, goatee, "central_goatee")
        for index, (x_value, height) in enumerate(
            ((-11.0, 8.0), (-6.0, 10.0), (6.0, 10.0), (11.0, 8.0)),
            start=1,
        ):
            beard_tuft = _oriented_cone(
                model,
                radius1=3.2,
                radius2=0.5,
                height=height,
                position=(x_value, -23.0, 11.0),
                tilt_axis=(1.0, 0.0, 0.0),
                tilt_degrees=180.0,
            )
            head = _union(model, head, beard_tuft, f"beard_tuft_{index}")
        feature_stages.append("five_point_beard")

        for index, x_value in enumerate((-11.5, 11.5), start=1):
            socket = model.translate(
                model.sphere(radius=6.2),
                x=x_value,
                y=-27.5,
                z=30.0,
            )
            head = _cut(model, head, socket, f"eye_socket_{index}")
        for index, x_value in enumerate((-3.8, 3.8), start=1):
            nostril = model.rotate(
                model.cylinder(radius=2.0, height=7.0),
                degrees=-90.0,
                axis=(1.0, 0.0, 0.0),
                origin=(0.0, 0.0, 0.0),
            )
            nostril = model.translate(nostril, x=x_value, y=-37.0, z=22.0)
            head = _cut(model, head, nostril, f"nostril_{index}")
        mouth_slot = model.translate(
            model.box(width=14.0, depth=8.0, height=1.5),
            x=-7.0,
            y=-36.0,
            z=9.0,
        )
        head = _cut(model, head, mouth_slot, "mouth_slot")
        feature_stages.append("eye_sockets_nostrils_mouth_slot")

        for index, x_value in enumerate((-11.5, 11.5), start=1):
            eye = model.translate(
                model.sphere(radius=5.0),
                x=x_value,
                y=-30.0,
                z=30.0,
            )
            head = _union(model, head, eye, f"eye_ball_{index}")
            iris = model.translate(
                model.sphere(radius=2.2),
                x=x_value,
                y=-34.0,
                z=30.0,
            )
            head = _union(model, head, iris, f"iris_{index}")
        feature_stages.append("eyes_and_iris")

        headband = _make_headband(model)
        head = _union(model, head, headband, "headband")
        plate_wire = model.polyline(
            (
                (-7.0, -30.0, 58.0),
                (0.0, -30.0, 65.0),
                (7.0, -30.0, 58.0),
                (0.0, -30.0, 52.0),
            ),
            closed=True,
        )
        headband_plate = model.extrude(
            model.face(plate_wire),
            x=0.0,
            y=-5.0,
            z=0.0,
        )
        head = _union(model, head, headband_plate, "headband_front_plate")
        feature_stages.append("headband_and_front_plate")

        for index, (side, z_value, tilt) in enumerate(
            (
                (-1.0, 46.0, -75.0),
                (-1.0, 38.0, -68.0),
                (-1.0, 30.0, -62.0),
                (1.0, 46.0, 75.0),
                (1.0, 38.0, 68.0),
                (1.0, 30.0, 62.0),
            ),
            start=1,
        ):
            sideburn = _oriented_cone(
                model,
                radius1=3.8,
                radius2=0.5,
                height=10.0,
                position=(side * 25.0, -13.0, z_value),
                tilt_axis=(0.0, 1.0, 0.0),
                tilt_degrees=tilt,
            )
            head = _union(model, head, sideburn, f"sideburn_tuft_{index}")
        feature_stages.append("six_sideburn_tufts")

        for index, tuft in enumerate(_make_hair_tufts(model), start=1):
            head = _union(model, head, tuft, f"hair_tuft_{index:02d}")
        feature_stages.append("twelve_directional_hair_tufts")

        for label, position, height, tilt in (
            ("left_feather", (-8.0, -24.0, 61.0), 24.0, -13.0),
            ("center_feather", (0.0, -25.0, 61.0), 38.0, 0.0),
            ("right_feather", (8.0, -24.0, 61.0), 24.0, 13.0),
        ):
            feather = _make_feather(
                model,
                position=position,
                height=height,
                tilt=tilt,
            )
            head = _union(model, head, feather, label)
        feature_stages.append("three_feathers")

        final_part = head
        mesh = final_part.mesh(deflection=0.18)
        metrics: dict[str, Any] = {
            "units": "mm",
            "kind": final_part.kind,
            "volume": final_part.volume,
            "area": final_part.area,
            "center_of_mass": final_part.center_of_mass,
            "bbox": final_part.bbox,
            "topology": final_part.topology,
            "mesh": {
                "vertex_count": len(mesh.get("vertices", [])) // 3,
                "triangle_count": len(mesh.get("triangles", [])) // 3,
                "triangle_index_count": len(mesh.get("triangles", [])),
            },
            "feature_stages": feature_stages,
        }
        print("final_metrics", json.dumps(metrics, sort_keys=True))
        assert metrics["topology"]["solids"] >= 1
        bbox = metrics["bbox"]
        assert bbox[0] <= -38.0 and bbox[3] >= 38.0
        assert bbox[1] <= -34.0 and bbox[4] >= 20.0
        assert bbox[2] <= 0.5 and bbox[5] <= 106.0 and bbox[5] >= 95.0

        final_part.export_step(str(STEP_PATH))
        final_part.export_stl(str(STL_PATH), binary=True)

    return metrics


def validate_and_render(metrics: dict[str, Any]) -> None:
    from cadflow.inspect import brep

    step_summary = brep.inspect_step_rsummary(STEP_PATH)
    step_bbox = step_summary["bounding_box"]
    assert step_summary["valid"]
    assert step_summary["root_shape_type"] == "Solid"
    assert step_summary["material_body_count"] == 1
    assert abs(step_bbox["min"][0] + step_bbox["max"][0]) <= 0.1
    assert 77.0 <= step_bbox["size"][0] <= 79.0
    assert 70.0 <= step_bbox["size"][1] <= 73.0
    assert 98.0 <= step_bbox["size"][2] <= 101.0

    metrics["exported_step_validation"] = {
        "valid": step_summary["valid"],
        "root_shape_type": step_summary["root_shape_type"],
        "body_count": step_summary["body_count"],
        "material_body_count": step_summary["material_body_count"],
        "volume": step_summary["volume"],
        "surface_area": step_summary["surface_area"],
        "centroid": step_summary["centroid"],
        "bounding_box": step_bbox,
        "face_count": step_summary["face_count"],
        "edge_count": step_summary["edge_count"],
        "vertex_count": step_summary["vertex_count"],
        "surface_type_statistics": step_summary["surface_type_statistics"],
        "curve_type_statistics": step_summary["curve_type_statistics"],
        "x_symmetry_error": abs(step_bbox["min"][0] + step_bbox["max"][0]),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")

    brep.render_step_views_rpath(
        step_path=STEP_PATH,
        output_path=PNG_PATH,
        title="CadFlow Sun Wukong portrait",
        views=(
            (0.0, -90.0, "主视图"),
            (90.0, -90.0, "俯视图"),
            (0.0, 0.0, "侧视图"),
            (28.0, -45.0, ""),
        ),
        image_size=(18.0, 12.0),
        dpi=180,
        background_color=(1.0, 1.0, 1.0),
        font_file="/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        show_brep_edges=True,
    )


def main() -> None:
    metrics = build_portrait()
    validate_and_render(metrics)
    outputs = (STEP_PATH, STL_PATH, PNG_PATH, METRICS_PATH)
    for path in outputs:
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")
    print("outputs")
    for path in outputs:
        print(path.resolve(), path.stat().st_size)
    print("feature_stage_count", len(metrics["feature_stages"]))


if __name__ == "__main__":
    main()
