"""Rebuild a Text2CAD feature sequence and render the resulting workpiece.

The selected Text2CAD sample (0000/00003775) describes a cylindrical body
with one axial bore and two radial cut features.  The minimal JSON expresses
the units in a normalized 0..1 coordinate frame, so this script applies one
uniform scale factor at the input boundary and keeps all CadFlow dimensions
in millimetres.

This is a feature-sequence reconstruction, not a claim that the two cut tools
are independent physical parts.  The output is useful as a deterministic
CadFlow rendering and as a starting point for the real-time GLB preview path.
"""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import cadflow as cad
from cadflow.inspect import brep


DATASET_UID = "0000/00003775"
DATASET_JSON = Path(
    "/data/yihongzhu/Text2CAD-data/text2cad_v1.1/misc/minimal_json/"
    "minimal_json_0000_0099.zip"
)
DATASET_MEMBER = "0000/00003775/minimal_json/00003775.json"
SCALE_MM = 100.0
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "text2cad_00003775"


def load_source_dimensions() -> dict[str, float]:
    """Read the selected feature dimensions from the local Text2CAD archive."""

    with zipfile.ZipFile(DATASET_JSON) as archive:
        source = json.loads(archive.read(DATASET_MEMBER))

    parts = source["parts"]
    operations = [parts[f"part_{index}"]["extrusion"]["operation"] for index in range(1, 4)]
    expected = [
        "NewBodyFeatureOperation",
        "CutFeatureOperation",
        "CutFeatureOperation",
    ]
    if operations != expected:
        raise ValueError(f"unexpected Text2CAD feature sequence: {operations}")

    part_1 = parts["part_1"]
    part_2 = parts["part_2"]
    part_3 = parts["part_3"]
    dimensions = {
        "outer_radius": part_1["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"],
        "height": part_1["extrusion"]["extrude_depth_towards_normal"],
        "axial_bore_radius": part_1["sketch"]["face_1"]["loop_2"]["circle_1"]["Radius"],
        "part_2_radius": part_2["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"],
        "part_2_depth": part_2["extrusion"]["extrude_depth_opposite_normal"],
        "part_2_z": part_2["coordinate_system"]["Translation Vector"][2],
        "part_3_radius": part_3["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"],
        "part_3_depth": part_3["extrusion"]["extrude_depth_opposite_normal"],
        "part_3_z": part_3["coordinate_system"]["Translation Vector"][2],
    }
    return {name: float(value) for name, value in dimensions.items()}


def build_workpiece(
    model: cad.Model, source: dict[str, float]
) -> tuple[cad.Shape, dict[str, float]]:
    """Rebuild part_1 plus the two Text2CAD cut features in one CadFlow model."""

    # part_1: outer circle, inner circle, and a 0.75-normal extrusion.
    body = model.cylinder(
        radius=source["outer_radius"] * SCALE_MM,
        height=source["height"] * SCALE_MM,
    )
    axial_bore = model.cylinder(
        radius=source["axial_bore_radius"] * SCALE_MM,
        height=source["height"] * SCALE_MM + 2.0,
    )
    axial_bore = model.translate(axial_bore, x=0.0, y=0.0, z=-1.0)
    body = model.cut(body, axial_bore)

    # part_2: radius 0.0281, opposite-normal cut.  Its placement puts the
    # hole on the X radial direction at the normalized z=0.2445 level.
    radial_tool_length = 2.0 * source["outer_radius"] * SCALE_MM + 2.0
    x_hole = model.cylinder(
        radius=source["part_2_radius"] * SCALE_MM,
        height=radial_tool_length,
    )
    x_hole = model.rotate(x_hole, degrees=90.0, axis=(0.0, 1.0, 0.0))
    x_hole = model.translate(
        x_hole,
        x=-(source["outer_radius"] * SCALE_MM + 1.0),
        y=0.0,
        z=source["part_2_z"] * SCALE_MM,
    )
    body = model.cut(body, x_hole)

    # part_3: the same cut tool on the Y radial direction at z=0.1339.
    y_hole = model.cylinder(
        radius=source["part_3_radius"] * SCALE_MM,
        height=radial_tool_length,
    )
    y_hole = model.rotate(y_hole, degrees=-90.0, axis=(1.0, 0.0, 0.0))
    y_hole = model.translate(
        y_hole,
        x=0.0,
        y=-(source["outer_radius"] * SCALE_MM + 1.0),
        z=source["part_3_z"] * SCALE_MM,
    )
    body = model.cut(body, y_hole)

    metrics = {f"{name}_mm": value * SCALE_MM for name, value in source.items()}
    return body, metrics


def _png_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0 or len(data) <= 100:
        raise ValueError(f"invalid PNG payload: {path}")
    return {"width": width, "height": height, "bytes": len(data)}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_png = OUTPUT_DIR / "workpiece.png"
    output_step = OUTPUT_DIR / "workpiece.step"
    output_stl = OUTPUT_DIR / "workpiece.stl"
    output_report = OUTPUT_DIR / "report.json"

    source = load_source_dimensions()
    with cad.Model() as model:
        body, source_metrics = build_workpiece(model, source)
        validation = body.validate().to_dict()
        if not validation.get("ok", False):
            raise RuntimeError(f"CadFlow validation failed: {validation}")
        if body.topology.get("solids") != 1 or body.volume <= 0.0:
            raise RuntimeError(
                f"unexpected topology or volume: {body.topology}, {body.volume}"
            )

        measured = {
            "topology": body.topology,
            "volume_mm3": body.volume,
            "area_mm2": body.area,
            "bbox_mm": body.bbox,
        }
        body.export_step(str(output_step))
        body.export_stl(str(output_stl), binary=True)

    # The current frontend owns the geometry session.  Reloading the checked
    # STEP through this public inspection API keeps rendering independent.
    brep.render_step_views_rpath(
        output_step,
        output_png,
        views=((28.0, -45.0, "isometric"),),
        image_size=(12.0, 9.0),
        dpi=100,
        background_color=(0.94, 0.95, 0.97),
        show_brep_edges=True,
    )
    png = _png_info(output_png)

    report = {
        "dataset": {
            "uid": DATASET_UID,
            "minimal_json_archive": str(DATASET_JSON),
            "member": DATASET_MEMBER,
            "license": "CC BY-NC-SA 4.0 (Text2CAD v1.1)",
            "source_parts": {
                "part_1": "NewBodyFeatureOperation: outer circle + axial inner loop",
                "part_2": "CutFeatureOperation: radial circle, radius 0.0281",
                "part_3": "CutFeatureOperation: radial circle, radius 0.0281",
            },
        },
        "units": "millimetres (normalized Text2CAD coordinates x 100)",
        "reconstruction_assumptions": [
            "part_2 and part_3 are interpreted as mutually perpendicular radial cuts",
            "radial cutters are extended through the body to make both holes explicit",
        ],
        "validation": validation,
        **measured,
        "source_dimensions": source_metrics,
        "files": {
            "png": {"path": str(output_png), **png},
            "step": {"path": str(output_step), "bytes": output_step.stat().st_size},
            "stl": {"path": str(output_stl), "bytes": output_stl.stat().st_size},
        },
    }
    output_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
