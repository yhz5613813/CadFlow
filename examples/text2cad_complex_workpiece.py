"""Build a complex mechanical workpiece from local Text2CAD components.

The drivetrain geometry comes from Text2CAD sample 0015/00150738 (gear shaft,
hexagonal hub, flange, stepped cylinders, and keyway).  The mounting-hole
pattern comes from sample 0069/00694843.  Text2CAD stores normalized geometry;
all source dimensions are converted once at the input boundary to millimetres.

The source annotations do not define a complete assembly constraint system.
This script therefore documents the placement assumptions while retaining the
source component sizes and feature counts wherever they are unambiguous.
"""

from __future__ import annotations

import json
import math
import struct
import zipfile
from pathlib import Path

import cadflow as cad
from cadflow.inspect import brep


DATASET_ARCHIVE = Path(
    "/data/yihongzhu/Text2CAD-data/text2cad_v1.1/misc/minimal_json/"
    "minimal_json_0000_0099.zip"
)
DRIVETRAIN_MEMBER = "0015/00150738/minimal_json/00150738.json"
PATTERN_MEMBER = "0069/00694843/minimal_json/00694843.json"
SCALE_MM = 100.0
OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "text2cad_complex_workpiece"
)


def _read_json(member: str) -> dict[str, object]:
    with zipfile.ZipFile(DATASET_ARCHIVE) as archive:
        return json.loads(archive.read(member))


def load_components() -> dict[str, object]:
    """Extract source dimensions and ordered features from both JSON samples."""

    drivetrain = _read_json(DRIVETRAIN_MEMBER)
    pattern = _read_json(PATTERN_MEMBER)
    drive_parts = drivetrain["parts"]
    pattern_parts = pattern["parts"]

    drive_ops = [
        drive_parts[f"part_{index}"]["extrusion"]["operation"]
        for index in range(1, 8)
    ]
    if len(drive_ops) != 7:
        raise ValueError(f"unexpected drivetrain feature count: {drive_ops}")

    flange = drive_parts["part_1"]
    hex_hub = drive_parts["part_2"]
    collar = drive_parts["part_3"]
    keyway = drive_parts["part_4"]
    shaft = drive_parts["part_5"]
    tip = drive_parts["part_6"]

    hex_loop = hex_hub["sketch"]["face_1"]["loop_1"]
    raw_hex_points = [edge["Start Point"] for edge in hex_loop.values()]
    min_x = min(point[0] for point in raw_hex_points)
    max_x = max(point[0] for point in raw_hex_points)
    min_y = min(point[1] for point in raw_hex_points)
    max_y = max(point[1] for point in raw_hex_points)
    center_x = 0.5 * (min_x + max_x)
    center_y = 0.5 * (min_y + max_y)
    hex_points_mm = [
        ((point[0] - center_x) * SCALE_MM, (point[1] - center_y) * SCALE_MM)
        for point in raw_hex_points
    ]

    small_hole_parts = [
        part
        for name, part in pattern_parts.items()
        if name != "part_1"
        and part["extrusion"]["operation"] == "CutFeatureOperation"
        and part["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"] < 0.1
    ]
    small_hole_radii = [
        part["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        for part in small_hole_parts
    ]
    if not small_hole_radii:
        raise ValueError("the Text2CAD mounting-hole pattern is empty")

    return {
        "flange_tip_radius_mm": flange["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "flange_inner_radius_mm": flange["sketch"]["face_1"]["loop_2"]["circle_1"]["Radius"]
        * SCALE_MM,
        "flange_thickness_mm": flange["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "hex_points_mm": hex_points_mm,
        "hex_height_mm": hex_hub["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "collar_radius_mm": 0.5 * collar["description"]["length"] * SCALE_MM,
        "collar_height_mm": collar["description"]["height"] * SCALE_MM,
        "keyway_length_mm": keyway["description"]["length"] * SCALE_MM,
        "keyway_width_mm": keyway["description"]["width"] * SCALE_MM,
        "keyway_depth_mm": keyway["description"]["height"] * SCALE_MM,
        "shaft_radius_mm": shaft["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "shaft_length_mm": shaft["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "tip_radius_mm": tip["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "tip_length_mm": tip["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "mounting_hole_radius_mm": sum(small_hole_radii)
        / len(small_hole_radii)
        * SCALE_MM,
        "mounting_hole_count": len(small_hole_radii),
        "pattern_body_radius_mm": pattern_parts["part_1"]["sketch"]["face_1"]
        ["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "drivetrain_operations": drive_ops,
    }


def _check_shape(
    shape: cad.Shape, label: str, diagnostics: list[dict[str, object]]
) -> cad.Shape:
    validation = shape.validate().to_dict()
    topology = shape.topology
    if not validation["ok"] or topology.get("solids") != 1 or shape.volume <= 0.0:
        raise RuntimeError(
            f"{label} failed validation: {validation}, {topology}, {shape.volume}"
        )
    diagnostics.append(
        {
            "feature": label,
            "ok": True,
            "solids": topology["solids"],
            "volume_mm3": shape.volume,
        }
    )
    return shape


def _union_checked(
    model: cad.Model,
    body: cad.Shape,
    addition: cad.Shape,
    label: str,
    diagnostics: list[dict[str, object]],
) -> cad.Shape:
    before = body.volume
    result = model.union(body, addition)
    if result.volume <= before:
        raise RuntimeError(f"{label} did not add material")
    return _check_shape(result, label, diagnostics)


def _cut_checked(
    model: cad.Model,
    body: cad.Shape,
    tool: cad.Shape,
    label: str,
    diagnostics: list[dict[str, object]],
) -> cad.Shape:
    before = body.volume
    result = model.cut(body, tool)
    if result.volume >= before - 1e-6:
        raise RuntimeError(f"{label} did not remove material")
    return _check_shape(result, label, diagnostics)


def build_workpiece(
    model: cad.Model, source: dict[str, object]
) -> tuple[cad.Shape, list[dict[str, object]], dict[str, float]]:
    """Assemble the drivetrain features into one Z-axis mechanical part."""

    diagnostics: list[dict[str, object]] = []
    tip_radius = float(source["flange_tip_radius_mm"])
    flange_thickness = float(source["flange_thickness_mm"])
    root_radius = 0.78 * tip_radius
    gear_height = max(8.0, flange_thickness)
    tooth_count = 18
    tooth_width = 0.17 * tip_radius
    tooth_length = tip_radius - root_radius + 1.5

    body = model.cylinder(radius=root_radius, height=gear_height)
    body = _check_shape(body, "gear root", diagnostics)

    # The Text2CAD model is named a gear shaft but does not specify tooth
    # geometry.  Eighteen involute-like rectangular lugs make that component
    # explicit while preserving its source outer radius.
    for index in range(tooth_count):
        tooth = model.box(
            width=tooth_length,
            depth=tooth_width,
            height=gear_height,
        )
        tooth = model.translate(
            tooth,
            x=root_radius - 1.0,
            y=-0.5 * tooth_width,
            z=0.0,
        )
        tooth = model.rotate(
            tooth,
            degrees=index * 360.0 / tooth_count,
            axis=(0.0, 0.0, 1.0),
        )
        body = _union_checked(
            model, body, tooth, f"gear tooth {index + 1}", diagnostics
        )

    hex_z = gear_height - 0.5
    hex_wire = model.polyline(
        [(x, y, hex_z) for x, y in source["hex_points_mm"]],
        closed=True,
    )
    hex_face = model.face(hex_wire)
    hex_hub = model.extrude(
        hex_face,
        x=0.0,
        y=0.0,
        z=float(source["hex_height_mm"]),
    )
    body = _union_checked(model, body, hex_hub, "hexagonal hub", diagnostics)

    collar_z = hex_z + float(source["hex_height_mm"]) - 0.5
    collar = model.cylinder(
        radius=float(source["collar_radius_mm"]),
        height=float(source["collar_height_mm"]),
    )
    collar = model.translate(collar, x=0.0, y=0.0, z=collar_z)
    body = _union_checked(model, body, collar, "shaft collar", diagnostics)

    shaft_z = collar_z + float(source["collar_height_mm"]) - 0.5
    shaft = model.cylinder(
        radius=float(source["shaft_radius_mm"]),
        height=float(source["shaft_length_mm"]),
    )
    shaft = model.translate(shaft, x=0.0, y=0.0, z=shaft_z)
    body = _union_checked(model, body, shaft, "main shaft", diagnostics)

    tip_z = shaft_z + float(source["shaft_length_mm"]) - 0.5
    tip = model.cylinder(
        radius=float(source["tip_radius_mm"]),
        height=float(source["tip_length_mm"]),
    )
    tip = model.translate(tip, x=0.0, y=0.0, z=tip_z)
    body = _union_checked(model, body, tip, "stepped shaft tip", diagnostics)

    bolt_radius = float(source["mounting_hole_radius_mm"])
    bolt_count = int(source["mounting_hole_count"])
    bolt_circle_radius = 0.66 * root_radius
    for index in range(bolt_count):
        angle = 2.0 * math.pi * index / bolt_count
        bolt_hole = model.cylinder(radius=bolt_radius, height=gear_height + 2.0)
        bolt_hole = model.translate(
            bolt_hole,
            x=bolt_circle_radius * math.cos(angle),
            y=bolt_circle_radius * math.sin(angle),
            z=-1.0,
        )
        body = _cut_checked(
            model,
            body,
            bolt_hole,
            f"mounting hole {index + 1}",
            diagnostics,
        )

    axial_bore_radius = min(
        0.55 * float(source["tip_radius_mm"]),
        0.38 * float(source["flange_inner_radius_mm"]),
    )
    overall_height = tip_z + float(source["tip_length_mm"])
    axial_bore = model.cylinder(
        radius=axial_bore_radius,
        height=overall_height + 2.0,
    )
    axial_bore = model.translate(axial_bore, x=0.0, y=0.0, z=-1.0)
    body = _cut_checked(model, body, axial_bore, "axial bore", diagnostics)

    keyway_depth = float(source["keyway_depth_mm"])
    keyway_width = float(source["keyway_width_mm"])
    keyway_length = min(
        float(source["keyway_length_mm"]),
        float(source["shaft_length_mm"]) - 4.0,
    )
    shaft_radius = float(source["shaft_radius_mm"])
    keyway_tool = model.box(
        width=keyway_depth + 2.0,
        depth=keyway_width,
        height=keyway_length,
    )
    keyway_tool = model.translate(
        keyway_tool,
        x=shaft_radius - keyway_depth,
        y=-0.5 * keyway_width,
        z=shaft_z + 2.0,
    )
    body = _cut_checked(model, body, keyway_tool, "longitudinal keyway", diagnostics)

    pin_radius = bolt_radius
    pin_hole = model.cylinder(
        radius=pin_radius,
        height=2.0 * shaft_radius + 2.0,
    )
    pin_hole = model.rotate(pin_hole, degrees=90.0, axis=(0.0, 1.0, 0.0))
    pin_hole = model.translate(
        pin_hole,
        x=-(shaft_radius + 1.0),
        y=0.0,
        z=shaft_z + 0.72 * float(source["shaft_length_mm"]),
    )
    body = _cut_checked(model, body, pin_hole, "radial pin hole", diagnostics)

    assembly_dimensions = {
        "gear_tip_radius_mm": tip_radius,
        "gear_root_radius_mm": root_radius,
        "gear_height_mm": gear_height,
        "tooth_count": float(tooth_count),
        "mounting_hole_count": float(bolt_count),
        "mounting_hole_radius_mm": bolt_radius,
        "bolt_circle_radius_mm": bolt_circle_radius,
        "axial_bore_radius_mm": axial_bore_radius,
        "overall_height_mm": overall_height,
    }
    return body, diagnostics, assembly_dimensions


def _png_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0 or len(data) <= 100:
        raise ValueError(f"invalid PNG payload: {path}")
    return {"width": width, "height": height, "bytes": len(data)}


def _stl_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    triangle_count = struct.unpack("<I", data[80:84])[0]
    if len(data) != 84 + 50 * triangle_count:
        raise ValueError(f"invalid binary STL length: {path}")
    return {"triangles": triangle_count, "bytes": len(data)}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_png = OUTPUT_DIR / "complex_workpiece.png"
    output_step = OUTPUT_DIR / "complex_workpiece.step"
    output_stl = OUTPUT_DIR / "complex_workpiece.stl"
    output_glb = OUTPUT_DIR / "complex_workpiece.glb"
    output_report = OUTPUT_DIR / "report.json"

    source = load_components()
    with cad.Model() as model:
        body, diagnostics, assembly_dimensions = build_workpiece(model, source)
        validation = body.validate().to_dict()
        measured = {
            "topology": body.topology,
            "volume_mm3": body.volume,
            "area_mm2": body.area,
            "bbox_mm": body.bbox,
        }
        if not validation["ok"] or measured["topology"].get("solids") != 1:
            raise RuntimeError(f"final validation failed: {validation}, {measured}")
        body.export_step(str(output_step))
        body.export_stl(str(output_stl), binary=True)
        body.export_preview_glb(str(output_glb), deflection=0.18)

    brep.render_step_views_rpath(
        output_step,
        output_png,
        views=((28.0, -45.0, "isometric"), (86.0, -90.0, "top")),
        image_size=(16.0, 8.0),
        dpi=110,
        background_color=(0.94, 0.95, 0.97),
        show_brep_edges=True,
        title="Text2CAD drivetrain workpiece",
    )
    png = _png_info(output_png)
    stl = _stl_info(output_stl)
    glb = output_glb.read_bytes()
    if glb[:4] != b"glTF" or len(glb) <= 100:
        raise ValueError(f"invalid GLB: {output_glb}")

    report = {
        "dataset": {
            "archive": str(DATASET_ARCHIVE),
            "license": "CC BY-NC-SA 4.0 (Text2CAD v1.1)",
            "sources": {
                "0015/00150738": "gear shaft, flange, hex hub, stepped shaft, keyway",
                "0069/00694843": "circular mounting-hole pattern",
            },
            "members": [DRIVETRAIN_MEMBER, PATTERN_MEMBER],
        },
        "units": "millimetres (normalized Text2CAD coordinates x 100)",
        "reconstruction_assumptions": [
            "The source annotations omit assembly constraints, so components share a Z axis.",
            "The gear label is realized as 18 rectangular teeth at the source outer radius.",
            "The annotation says seven holes, but eight small CutFeatureOperation "
            "entries are present; the JSON count is used.",
            "The axial bore is reduced to fit inside the smallest shaft stage.",
        ],
        "validation": validation,
        "feature_diagnostics": diagnostics,
        "source_dimensions": source,
        "assembly_dimensions": assembly_dimensions,
        **measured,
        "files": {
            "png": {"path": str(output_png), **png},
            "step": {
                "path": str(output_step),
                "bytes": output_step.stat().st_size,
            },
            "stl": {"path": str(output_stl), **stl},
            "glb": {"path": str(output_glb), "bytes": len(glb)},
        },
    }
    output_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
