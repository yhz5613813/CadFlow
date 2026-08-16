"""Build a Text2CAD-derived connector and drive-shaft workpiece.

This example uses dimensions from Text2CAD's L-bracket, gear-shaft, and
mounting-hole samples, then assembles them into a larger connected fixture.
The source dataset has feature dimensions but no assembly constraints, so the
placement assumptions are explicit and the final part is validated as one
kernel solid after every boolean operation.
"""

from __future__ import annotations

import json
import math
import struct
import zipfile
from pathlib import Path

import cadflow as cad
from cadflow.inspect import brep


ARCHIVE = Path(
    "/data/yihongzhu/Text2CAD-data/text2cad_v1.1/misc/minimal_json/"
    "minimal_json_0000_0099.zip"
)
BRACKET_MEMBER = "0074/00743657/minimal_json/00743657.json"
DRIVE_MEMBER = "0015/00150738/minimal_json/00150738.json"
PATTERN_MEMBER = "0069/00694843/minimal_json/00694843.json"
SCALE_MM = 100.0
OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "text2cad_connector_workpiece"
)


def _read(member: str) -> dict[str, object]:
    with zipfile.ZipFile(ARCHIVE) as archive:
        return json.loads(archive.read(member))


def load_source_dimensions() -> dict[str, object]:
    """Read the source dimensions needed by the connected assembly."""

    bracket = _read(BRACKET_MEMBER)["parts"]["part_1"]
    drive = _read(DRIVE_MEMBER)["parts"]
    pattern = _read(PATTERN_MEMBER)["parts"]
    flange = drive["part_1"]
    hex_hub = drive["part_2"]
    keyway = drive["part_4"]
    shaft = drive["part_5"]
    tip = drive["part_6"]
    hole_parts = [
        part
        for name, part in pattern.items()
        if name != "part_1"
        and part["extrusion"]["operation"] == "CutFeatureOperation"
    ]
    small_holes = [
        part["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        for part in hole_parts
        if "circle_1" in part["sketch"]["face_1"]["loop_1"]
        and part["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"] < 0.1
    ]
    raw_hex = [
        edge["Start Point"]
        for edge in hex_hub["sketch"]["face_1"]["loop_1"].values()
    ]
    cx = (min(point[0] for point in raw_hex) + max(point[0] for point in raw_hex)) / 2
    cy = (min(point[1] for point in raw_hex) + max(point[1] for point in raw_hex)) / 2
    hex_points = [
        ((point[0] - cx) * SCALE_MM, (point[1] - cy) * SCALE_MM)
        for point in raw_hex
    ]
    return {
        "bracket_length_mm": bracket["description"]["length"] * 220.0,
        "bracket_width_mm": bracket["description"]["width"] * 220.0,
        "bracket_thickness_mm": bracket["description"]["height"] * 220.0,
        "gear_radius_mm": flange["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "flange_bore_radius_mm": flange["sketch"]["face_1"]["loop_2"]["circle_1"]["Radius"]
        * SCALE_MM,
        "hex_points_mm": hex_points,
        "hex_height_mm": hex_hub["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
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
        "mounting_hole_radius_mm": sum(small_holes) / len(small_holes) * SCALE_MM,
        "mounting_hole_count": len(small_holes),
    }


def _valid(shape: cad.Shape, label: str, events: list[dict[str, object]]) -> cad.Shape:
    validation = shape.validate().to_dict()
    topology = shape.topology
    if not validation["ok"] or topology.get("solids") != 1 or shape.volume <= 0:
        raise RuntimeError(f"{label}: {validation}, {topology}, {shape.volume}")
    events.append(
        {
            "feature": label,
            "ok": True,
            "solids": topology["solids"],
            "volume_mm3": shape.volume,
        }
    )
    return shape


def _union(
    model: cad.Model,
    body: cad.Shape,
    addition: cad.Shape,
    label: str,
    events: list[dict[str, object]],
) -> cad.Shape:
    before = body.volume
    result = model.union(body, addition)
    if result.volume <= before:
        raise RuntimeError(f"{label} did not add material")
    return _valid(result, label, events)


def _cut(
    model: cad.Model,
    body: cad.Shape,
    tool: cad.Shape,
    label: str,
    events: list[dict[str, object]],
) -> cad.Shape:
    before = body.volume
    result = model.cut(body, tool)
    if result.volume >= before - 1e-6:
        raise RuntimeError(f"{label} did not remove material")
    return _valid(result, label, events)


def _axis_cylinder(
    model: cad.Model,
    radius: float,
    length: float,
    base: tuple[float, float, float],
    axis: str,
) -> cad.Shape:
    shape = model.cylinder(radius=radius, height=length)
    if axis == "x":
        shape = model.rotate(shape, degrees=90.0, axis=(0.0, 1.0, 0.0))
    elif axis == "y":
        shape = model.rotate(shape, degrees=-90.0, axis=(1.0, 0.0, 0.0))
    elif axis != "z":
        raise ValueError(f"unsupported axis {axis}")
    return model.translate(shape, x=base[0], y=base[1], z=base[2])


def _hex_prism_z(
    model: cad.Model,
    radius: float,
    height: float,
    center: tuple[float, float],
    z: float,
) -> cad.Shape:
    points = [
        (center[0] + radius * math.cos(i * math.pi / 3),
         center[1] + radius * math.sin(i * math.pi / 3), z)
        for i in range(6)
    ]
    return model.extrude(model.face(model.polyline(points, closed=True)), 0.0, 0.0, height)


def _hex_prism_x(
    model: cad.Model,
    radius: float,
    length: float,
    center: tuple[float, float],
    x: float,
) -> cad.Shape:
    points = [
        (x, center[0] + radius * math.cos(i * math.pi / 3),
         center[1] + radius * math.sin(i * math.pi / 3))
        for i in range(6)
    ]
    return model.extrude(model.face(model.polyline(points, closed=True)), length, 0.0, 0.0)


def _tri_prism_y(
    model: cad.Model,
    points_xz: list[tuple[float, float]],
    y: float,
    depth: float,
) -> cad.Shape:
    points = [(x, y, z) for x, z in points_xz]
    return model.extrude(model.face(model.polyline(points, closed=True)), 0.0, depth, 0.0)


def build_workpiece(
    model: cad.Model, source: dict[str, object]
) -> tuple[cad.Shape, list[dict[str, object]], dict[str, float]]:
    events: list[dict[str, object]] = []
    base_x = 180.0
    base_y = 120.0
    base_t = max(12.0, float(source["bracket_thickness_mm"]))
    body = model.box(base_x, base_y, base_t)
    body = model.translate(body, x=-base_x / 2, y=-base_y / 2, z=0.0)
    body = _valid(body, "base plate", events)

    # Four base mounting holes with counterbores are the first connection layer.
    base_hole_radius = 2.0 * float(source["mounting_hole_radius_mm"])
    counterbore_radius = 1.65 * base_hole_radius
    for index, (x, y) in enumerate(((-72, -42), (72, -42), (-72, 42), (72, 42)), 1):
        through = _axis_cylinder(
            model, base_hole_radius, base_t + 2.0, (x, y, -1.0), "z"
        )
        body = _cut(model, body, through, f"base through hole {index}", events)
        counterbore = _axis_cylinder(
            model, counterbore_radius, 4.0, (x, y, base_t - 3.0), "z"
        )
        body = _cut(model, body, counterbore, f"base counterbore {index}", events)

    tower_w = 24.0
    tower_d = 72.0
    tower_h = 86.0
    tower_z = base_t - 0.5
    tower_centers = (-60.0, 60.0)
    for index, center_x in enumerate(tower_centers, 1):
        tower = model.box(tower_w, tower_d, tower_h)
        tower = model.translate(tower, x=center_x - tower_w / 2, y=-tower_d / 2, z=tower_z)
        body = _union(model, body, tower, f"support tower {index}", events)

    # A transverse bore receives the main shaft; it is cut before the shaft is fused.
    shaft_axis_z = 76.0
    tower_bore = _axis_cylinder(
        model,
        11.5,
        base_x + 20.0,
        (-base_x / 2 - 10.0, 0.0, shaft_axis_z),
        "x",
    )
    body = _cut(model, body, tower_bore, "support shaft bore", events)

    # Four triangular gussets tie the supports to the base.
    for index, center_x in enumerate((-60.0, 60.0), 1):
        outer = center_x - tower_w / 2 if center_x < 0 else center_x + tower_w / 2
        sign = -1.0 if center_x < 0 else 1.0
        tri = _tri_prism_y(
            model,
            [(outer, tower_z), (outer + sign * 30.0, tower_z),
             (outer, tower_z + 34.0)],
            -tower_d / 2 - 8.0,
            8.0,
        )
        body = _union(model, body, tri, f"front gusset {index}", events)
        tri_back = _tri_prism_y(
            model,
            [(outer, tower_z), (outer + sign * 30.0, tower_z),
             (outer, tower_z + 34.0)],
            tower_d / 2,
            8.0,
        )
        body = _union(model, body, tri_back, f"rear gusset {index}", events)

    # Upper connecting beam and a front tie rod form two distinct connection paths.
    beam = model.box(144.0, 18.0, 10.0)
    beam = model.translate(beam, x=-72.0, y=-9.0, z=88.0)
    body = _union(model, body, beam, "upper connecting beam", events)
    tie_rod = _axis_cylinder(model, 4.0, 150.0, (-75.0, -27.0, 41.0), "x")
    body = _union(model, body, tie_rod, "front tie rod", events)

    # Main shaft, its end collars, and the Text2CAD-derived drive gear are fused.
    shaft_r = float(source["shaft_radius_mm"])
    main_shaft = _axis_cylinder(model, shaft_r + 1.0, 180.0, (-90.0, 0.0, shaft_axis_z), "x")
    body = _union(model, body, main_shaft, "transverse main shaft", events)
    for index, x in enumerate((-86.0, 78.0), 1):
        collar = _axis_cylinder(model, 19.0, 8.0, (x, 0.0, shaft_axis_z), "x")
        body = _union(model, body, collar, f"shaft collar {index}", events)

    gear_r = float(source["gear_radius_mm"])
    gear_core_r = 0.78 * gear_r
    gear = _axis_cylinder(model, gear_core_r, 8.0, (-4.0, 0.0, shaft_axis_z), "x")
    body = _union(model, body, gear, "drive gear core", events)
    tooth_count = 18
    tooth_length = gear_r - gear_core_r + 1.5
    for index in range(tooth_count):
        tooth = model.box(8.0, tooth_length, 6.0)
        tooth = model.translate(tooth, x=-4.0, y=gear_core_r - 1.0, z=shaft_axis_z - 3.0)
        tooth = model.rotate(
            tooth,
            index * 360.0 / tooth_count,
            axis=(1.0, 0.0, 0.0),
            origin=(0.0, 0.0, shaft_axis_z),
        )
        body = _union(model, body, tooth, f"drive tooth {index + 1}", events)

    hub = _hex_prism_x(
        model,
        20.8,
        float(source["hex_height_mm"]) + 3.0,
        (0.0, shaft_axis_z),
        -10.0,
    )
    body = _union(model, body, hub, "hexagonal drive hub", events)

    # Four vertical clamp bolts on the tower caps.
    for tower_index, center_x in enumerate(tower_centers, 1):
        cap = model.box(tower_w + 4.0, tower_d + 4.0, 6.0)
        cap = model.translate(cap, x=center_x - tower_w / 2 - 2.0, y=-tower_d / 2 - 2.0, z=92.0)
        body = _union(model, body, cap, f"tower cap {tower_index}", events)
        for side, y in enumerate((-23.0, 23.0), 1):
            stem = _axis_cylinder(model, 4.0, 26.0, (center_x, y, 82.0), "z")
            body = _union(model, body, stem, f"clamp bolt stem {tower_index}-{side}", events)
            head = _hex_prism_z(model, 8.0, 6.0, (center_x, y), 101.0)
            body = _union(model, body, head, f"clamp bolt head {tower_index}-{side}", events)

    # Retaining hex nuts on both shaft ends and on the front tie rod.
    for index, x in enumerate((-96.0, 90.0), 1):
        nut = _hex_prism_x(model, 15.0, 10.0, (0.0, shaft_axis_z), x)
        body = _union(model, body, nut, f"shaft retaining nut {index}", events)
    for index, x in enumerate((-82.0, 75.0), 1):
        nut = _hex_prism_x(model, 7.0, 8.0, (-27.0, 41.0), x)
        body = _union(model, body, nut, f"tie rod nut {index}", events)

    # A longitudinal keyway and a radial pin hole connect the drive hub to its shaft.
    keyway = model.box(
        float(source["keyway_depth_mm"]) + 2.0,
        float(source["keyway_width_mm"]),
        32.0,
    )
    keyway = model.translate(
        keyway,
        x=-16.0,
        y=-float(source["keyway_width_mm"]) / 2,
        z=shaft_axis_z - 16.0,
    )
    keyway = model.rotate(keyway, 90.0, axis=(1.0, 0.0, 0.0), origin=(0.0, 0.0, shaft_axis_z))
    body = _cut(model, body, keyway, "drive keyway", events)
    pin = _axis_cylinder(model, 4.0, 30.0, (-15.0, 0.0, shaft_axis_z + 22.0), "x")
    body = _cut(model, body, pin, "drive radial pin hole", events)

    dims = {
        "base_x_mm": base_x,
        "base_y_mm": base_y,
        "base_thickness_mm": base_t,
        "tower_height_mm": tower_h,
        "shaft_axis_z_mm": shaft_axis_z,
        "drive_tooth_count": float(tooth_count),
        "clamp_bolt_count": 4.0,
        "base_mount_count": 4.0,
        "base_hole_radius_mm": base_hole_radius,
        "counterbore_radius_mm": counterbore_radius,
        "mounting_hole_radius_mm": float(source["mounting_hole_radius_mm"]),
    }
    return body, events, dims


def _png_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG signature")
    width, height = struct.unpack(">II", data[16:24])
    return {"width": width, "height": height, "bytes": len(data)}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUTPUT_DIR / "connector_workpiece.png"
    step_path = OUTPUT_DIR / "connector_workpiece.step"
    stl_path = OUTPUT_DIR / "connector_workpiece.stl"
    glb_path = OUTPUT_DIR / "connector_workpiece.glb"
    report_path = OUTPUT_DIR / "report.json"
    source = load_source_dimensions()
    with cad.Model() as model:
        body, events, assembly_dims = build_workpiece(model, source)
        validation = body.validate().to_dict()
        measured = {
            "topology": body.topology,
            "volume_mm3": body.volume,
            "area_mm2": body.area,
            "bbox_mm": body.bbox,
        }
        if not validation["ok"] or measured["topology"].get("solids") != 1:
            raise RuntimeError(f"final validation failed: {validation}, {measured}")
        body.export_step(str(step_path))
        body.export_stl(str(stl_path), binary=True)
        body.export_preview_glb(str(glb_path), deflection=0.2)

    brep.render_step_views_rpath(
        step_path,
        png_path,
        views=((25.0, -42.0, "isometric"), (86.0, -90.0, "top")),
        image_size=(16.0, 8.0),
        dpi=110,
        background_color=(0.94, 0.95, 0.97),
        show_brep_edges=True,
        title="Text2CAD connected fixture",
    )
    png = _png_info(png_path)
    stl_data = stl_path.read_bytes()
    triangles = struct.unpack("<I", stl_data[80:84])[0]
    glb_data = glb_path.read_bytes()
    if len(stl_data) != 84 + 50 * triangles or glb_data[:4] != b"glTF":
        raise ValueError("export validation failed")
    report = {
        "dataset": {
            "archive": str(ARCHIVE),
            "license": "CC BY-NC-SA 4.0 (Text2CAD v1.1)",
            "members": [BRACKET_MEMBER, DRIVE_MEMBER, PATTERN_MEMBER],
            "roles": {
                "0074/00743657": "base plate source dimensions",
                "0015/00150738": "drive shaft, hex hub, flange, keyway",
                "0069/00694843": "mounting-hole source radius",
            },
        },
        "units": "millimetres",
        "reconstruction_assumptions": [
            "The source records dimensions but no mates, so the fixture uses "
            "an explicit Z-up frame.",
            "The base is enlarged to 180 x 120 mm to accommodate four supports "
            "and connection hardware.",
            "The source gear-shaft label is represented by 18 rectangular drive teeth.",
            "All connectors overlap their host solids before union; the final "
            "result remains one Solid.",
        ],
        "validation": validation,
        "feature_diagnostics": events,
        "source_dimensions": source,
        "assembly_dimensions": assembly_dims,
        **measured,
        "files": {
            "png": {"path": str(png_path), **png},
            "step": {"path": str(step_path), "bytes": step_path.stat().st_size},
            "stl": {"path": str(stl_path), "bytes": len(stl_data), "triangles": triangles},
            "glb": {"path": str(glb_path), "bytes": len(glb_data)},
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
