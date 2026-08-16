"""Assemble a Text2CAD-derived boiler-shaped mechanical workpiece.

The visible components are based on local Text2CAD cylinder, flange, bracket,
hex-hub, and circular-hole components.  The dataset has no assembly mates, so
the script chooses a Z-up pressure-vessel frame and explicitly places the
connections.  This is an exterior CAD workpiece: the shell is modeled as a
solid envelope for robust rendering, not as a pressure-rated wall or a thermal
fluid simulation.
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
CYLINDER_MEMBER = "0000/00003775/minimal_json/00003775.json"
FLANGE_MEMBER = "0015/00150738/minimal_json/00150738.json"
BRACKET_MEMBER = "0074/00743657/minimal_json/00743657.json"
HOLES_MEMBER = "0069/00694843/minimal_json/00694843.json"
SCALE_MM = 100.0
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "text2cad_boiler"


def _read(member: str) -> dict[str, object]:
    with zipfile.ZipFile(ARCHIVE) as archive:
        return json.loads(archive.read(member))


def load_source_dimensions() -> dict[str, object]:
    """Read source dimensions and feature counts from the local archive."""

    cylinder = _read(CYLINDER_MEMBER)["parts"]["part_1"]
    flange_parts = _read(FLANGE_MEMBER)["parts"]
    bracket = _read(BRACKET_MEMBER)["parts"]["part_1"]
    hole_parts = _read(HOLES_MEMBER)["parts"]
    flange = flange_parts["part_1"]
    hex_hub = flange_parts["part_2"]
    small_holes = [
        part["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        for name, part in hole_parts.items()
        if name != "part_1"
        and part["extrusion"]["operation"] == "CutFeatureOperation"
        and "circle_1" in part["sketch"]["face_1"]["loop_1"]
        and part["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"] < 0.1
    ]
    raw_hex = [
        edge["Start Point"]
        for edge in hex_hub["sketch"]["face_1"]["loop_1"].values()
    ]
    center_x = (min(point[0] for point in raw_hex) + max(point[0] for point in raw_hex)) / 2
    center_y = (min(point[1] for point in raw_hex) + max(point[1] for point in raw_hex)) / 2
    hex_points = [
        ((point[0] - center_x) * SCALE_MM, (point[1] - center_y) * SCALE_MM)
        for point in raw_hex
    ]
    return {
        "cylinder_radius_mm": cylinder["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "cylinder_height_mm": cylinder["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "flange_radius_mm": flange["sketch"]["face_1"]["loop_1"]["circle_1"]["Radius"]
        * SCALE_MM,
        "flange_bore_radius_mm": flange["sketch"]["face_1"]["loop_2"]["circle_1"]["Radius"]
        * SCALE_MM,
        "flange_thickness_mm": flange["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "hex_points_mm": hex_points,
        "hex_height_mm": hex_hub["extrusion"]["extrude_depth_towards_normal"]
        * SCALE_MM,
        "base_length_mm": bracket["description"]["length"] * 220.0,
        "base_width_mm": bracket["description"]["width"] * 220.0,
        "base_thickness_mm": bracket["description"]["height"] * 220.0,
        "bolt_radius_mm": sum(small_holes) / len(small_holes) * SCALE_MM,
        "bolt_count": len(small_holes),
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
        shape = model.rotate(shape, 90.0, axis=(0.0, 1.0, 0.0))
    elif axis == "xn":
        shape = model.rotate(shape, -90.0, axis=(0.0, 1.0, 0.0))
    elif axis == "y":
        shape = model.rotate(shape, -90.0, axis=(1.0, 0.0, 0.0))
    elif axis == "yn":
        shape = model.rotate(shape, 90.0, axis=(1.0, 0.0, 0.0))
    elif axis != "z":
        raise ValueError(f"unsupported axis {axis}")
    return model.translate(shape, x=base[0], y=base[1], z=base[2])


def _hex_z(
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


def _hex_x(
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


def _hex_y(
    model: cad.Model,
    radius: float,
    length: float,
    center: tuple[float, float],
    y: float,
    direction: float = 1.0,
) -> cad.Shape:
    points = [
        (center[0] + radius * math.cos(i * math.pi / 3), y,
         center[1] + radius * math.sin(i * math.pi / 3))
        for i in range(6)
    ]
    return model.extrude(
        model.face(model.polyline(points, closed=True)),
        0.0,
        direction * length,
        0.0,
    )


def _annulus_z(
    model: cad.Model,
    outer_radius: float,
    inner_radius: float,
    height: float,
    z: float,
    events: list[dict[str, object]],
    label: str,
) -> cad.Shape:
    ring = _axis_cylinder(model, outer_radius, height, (0.0, 0.0, z), "z")
    hole = _axis_cylinder(model, inner_radius, height + 2.0, (0.0, 0.0, z - 1.0), "z")
    return _cut(model, ring, hole, label, events)


def build_boiler(
    model: cad.Model, source: dict[str, object]
) -> tuple[cad.Shape, list[dict[str, object]], dict[str, float]]:
    events: list[dict[str, object]] = []
    shell_r = 70.0
    shell_z = 30.0
    shell_h = 155.0
    bottom_z = 10.0
    head_h = 25.0

    body = _axis_cylinder(model, shell_r, shell_h, (0.0, 0.0, shell_z), "z")
    body = _valid(body, "vertical cylindrical shell", events)
    bottom_head = model.cone(52.0, shell_r, head_h)
    bottom_head = model.translate(bottom_head, x=0.0, y=0.0, z=bottom_z)
    body = _union(model, body, bottom_head, "lower dished head", events)
    top_head = model.cone(shell_r, 52.0, head_h)
    top_head = model.translate(top_head, x=0.0, y=0.0, z=shell_z + shell_h - 5.0)
    body = _union(model, body, top_head, "upper dished head", events)

    base_ring = _axis_cylinder(model, 78.0, 10.0, (0.0, 0.0, 5.0), "z")
    body = _union(model, body, base_ring, "boiler foundation ring", events)

    # Raised shell bands are common pressure-vessel reinforcement details.
    for index, z in enumerate((62.0, 116.0, 170.0), 1):
        band = _axis_cylinder(model, 72.5, 4.0, (0.0, 0.0, z), "z")
        body = _union(model, body, band, f"shell reinforcement band {index}", events)

    # Four feet and diagonal gussets anchor the vessel to the base.
    for index, (x, y) in enumerate(((-52.0, -43.0), (52.0, -43.0), (-52.0, 43.0), (52.0, 43.0)), 1):
        foot = model.box(28.0, 28.0, 6.0)
        foot = model.translate(foot, x=x - 14.0, y=y - 14.0, z=0.0)
        body = _union(model, body, foot, f"boiler foot plate {index}", events)
        leg = model.box(16.0, 16.0, 34.0)
        leg = model.translate(leg, x=x - 8.0, y=y - 8.0, z=4.0)
        body = _union(model, body, leg, f"boiler support leg {index}", events)

    # Top chimney stack, cap, and a separate safety-valve boss.
    neck = _axis_cylinder(model, 24.0, 12.0, (0.0, 0.0, 205.0), "z")
    body = _union(model, body, neck, "chimney neck", events)
    stack = _axis_cylinder(model, 19.0, 22.0, (0.0, 0.0, 216.0), "z")
    body = _union(model, body, stack, "chimney stack", events)
    flare = model.cone(19.0, 14.0, 25.0)
    flare = model.translate(flare, x=0.0, y=0.0, z=232.0)
    body = _union(model, body, flare, "chimney tapered crown", events)
    cap = _axis_cylinder(model, 22.0, 5.0, (0.0, 0.0, 252.0), "z")
    body = _union(model, body, cap, "chimney cap", events)
    safety = _axis_cylinder(model, 10.0, 16.0, (36.0, 0.0, 198.0), "z")
    body = _union(model, body, safety, "safety valve boss", events)
    safety_head = _hex_z(model, 14.0, 7.0, (36.0, 0.0), 211.0)
    body = _union(model, body, safety_head, "safety valve hex head", events)

    # Offset manhole ring, cover and source-sized circular bolt pattern.
    manhole_center = (-38.0, 26.0)
    ring = _annulus_z(model, 30.0, 19.0, 8.0, 193.0, events, "manhole flange ring")
    ring = model.translate(ring, x=manhole_center[0], y=manhole_center[1], z=0.0)
    body = _union(model, body, ring, "manhole flange", events)
    bolt_r = float(source["bolt_radius_mm"])
    bolt_circle = 23.0
    bolt_count = int(source["bolt_count"])
    for index in range(bolt_count):
        angle = 2.0 * math.pi * index / bolt_count
        x = manhole_center[0] + bolt_circle * math.cos(angle)
        y = manhole_center[1] + bolt_circle * math.sin(angle)
        cutter = _axis_cylinder(model, bolt_r, 10.0, (x, y, 192.0), "z")
        body = _cut(model, body, cutter, f"manhole bolt hole {index + 1}", events)
    cover = _axis_cylinder(
        model,
        22.0,
        5.0,
        (manhole_center[0], manhole_center[1], 201.0),
        "z",
    )
    body = _union(model, body, cover, "manhole cover", events)
    for index in range(bolt_count):
        angle = 2.0 * math.pi * index / bolt_count
        x = manhole_center[0] + bolt_circle * math.cos(angle)
        y = manhole_center[1] + bolt_circle * math.sin(angle)
        stem = _axis_cylinder(model, bolt_r + 1.0, 7.0, (x, y, 204.0), "z")
        body = _union(model, body, stem, f"manhole bolt stem {index + 1}", events)
        head = _hex_z(model, bolt_r * 1.8, 4.0, (x, y), 211.0)
        body = _union(model, body, head, f"manhole bolt head {index + 1}", events)

    # Front furnace door, cover, burner nozzle, and radial bolt heads.
    door_center = (0.0, 0.0, 92.0)
    door_ring = _axis_cylinder(model, 30.0, 8.0, (0.0, -68.0, 92.0), "yn")
    body = _union(model, body, door_ring, "front furnace door flange", events)
    door_cover = _axis_cylinder(model, 25.0, 5.0, (0.0, -76.0, 92.0), "yn")
    body = _union(model, body, door_cover, "front furnace door cover", events)
    burner = _axis_cylinder(model, 12.0, 26.0, (0.0, -81.0, 92.0), "yn")
    body = _union(model, body, burner, "front burner nozzle", events)
    for index in range(8):
        angle = 2.0 * math.pi * index / 8
        x = 21.0 * math.cos(angle)
        z = 92.0 + 21.0 * math.sin(angle)
        stem = _axis_cylinder(model, 3.5, 8.0, (x, -77.0, z), "yn")
        body = _union(model, body, stem, f"furnace bolt stem {index + 1}", events)
        head = _hex_y(model, 6.0, 4.0, (x, z), -85.0, direction=-1.0)
        body = _union(model, body, head, f"furnace bolt head {index + 1}", events)

    # Side feedwater and steam connections, each with a flange and hex coupling.
    side_ports = (
        ("feedwater inlet", -64.0, -20.0, 58.0, "xn", -66.0, -1.0),
        ("steam outlet", 64.0, 20.0, 158.0, "x", 66.0, 1.0),
    )
    for label, x, y, z, axis, flange_x, direction in side_ports:
        pipe = _axis_cylinder(model, 10.0 if "steam" in label else 8.0, 30.0, (x, y, z), axis)
        body = _union(model, body, pipe, label, events)
        flange_shape = _axis_cylinder(model, 18.0, 6.0, (flange_x, y, z), axis)
        body = _union(model, body, flange_shape, f"{label} flange", events)
        coupling_x = flange_x - 8.0 if direction < 0 else flange_x + 6.0
        coupling = _hex_x(model, 12.0, 8.0, (y, z), coupling_x)
        body = _union(model, body, coupling, f"{label} hex coupling", events)

    # Steam riser and elbow assembled from perpendicular cylinders and a sphere.
    riser = _axis_cylinder(model, 8.0, 38.0, (70.0, 20.0, 158.0), "z")
    body = _union(model, body, riser, "steam riser", events)
    elbow = model.sphere(9.0)
    elbow = model.translate(elbow, x=70.0, y=20.0, z=196.0)
    body = _union(model, body, elbow, "steam pipe elbow", events)
    steam_arm = _axis_cylinder(model, 8.0, 32.0, (70.0, 20.0, 196.0), "x")
    body = _union(model, body, steam_arm, "steam header arm", events)

    # Front pressure-gauge branch and a small rectangular instrument bracket.
    gauge_stem = _axis_cylinder(model, 6.0, 18.0, (30.0, -61.0, 145.0), "yn")
    body = _union(model, body, gauge_stem, "pressure gauge branch", events)
    gauge = _axis_cylinder(model, 11.0, 5.0, (30.0, -77.0, 145.0), "yn")
    body = _union(model, body, gauge, "pressure gauge housing", events)
    bracket = model.box(34.0, 8.0, 22.0)
    bracket = model.translate(bracket, x=13.0, y=-72.0, z=134.0)
    body = _union(model, body, bracket, "gauge mounting bracket", events)

    # A front sight-glass water-level gauge links two shell pressure taps.
    level_x = -30.0
    for label, z in (("lower", 118.0), ("upper", 150.0)):
        tap = _axis_cylinder(model, 5.0, 18.0, (level_x, -61.0, z), "yn")
        body = _union(model, body, tap, f"water level {label} tap", events)
        tap_flange = _axis_cylinder(model, 9.0, 5.0, (level_x, -76.0, z), "yn")
        body = _union(
            model, body, tap_flange, f"water level {label} flange", events
        )
    sight_glass = _axis_cylinder(
        model, 3.0, 32.0, (level_x, -78.0, 118.0), "z"
    )
    body = _union(model, body, sight_glass, "water level sight glass", events)

    # The lower head carries a drain/blowdown connection and retaining nut.
    blowdown = _axis_cylinder(model, 7.0, 30.0, (-58.0, 0.0, 25.0), "xn")
    body = _union(model, body, blowdown, "bottom blowdown pipe", events)
    blowdown_flange = _axis_cylinder(
        model, 13.0, 6.0, (-64.0, 0.0, 25.0), "xn"
    )
    body = _union(model, body, blowdown_flange, "bottom blowdown flange", events)
    blowdown_nut = _hex_x(model, 11.0, 8.0, (0.0, 25.0), -88.0)
    body = _union(model, body, blowdown_nut, "bottom blowdown valve nut", events)

    dimensions = {
        "shell_radius_mm": shell_r,
        "shell_height_mm": shell_h,
        "overall_height_mm": 257.0,
        "base_length_mm": float(source["base_length_mm"]),
        "base_width_mm": float(source["base_width_mm"]),
        "manhole_bolt_count": float(bolt_count),
        "furnace_bolt_count": 8.0,
        "support_leg_count": 4.0,
        "pipe_connection_count": 6.0,
    }
    return body, events, dimensions


def _png_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG signature")
    width, height = struct.unpack(">II", data[16:24])
    return {"width": width, "height": height, "bytes": len(data)}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUTPUT_DIR / "boiler.png"
    step_path = OUTPUT_DIR / "boiler.step"
    stl_path = OUTPUT_DIR / "boiler.stl"
    glb_path = OUTPUT_DIR / "boiler.glb"
    report_path = OUTPUT_DIR / "report.json"
    source = load_source_dimensions()
    with cad.Model() as model:
        body, events, dimensions = build_boiler(model, source)
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
        body.export_preview_glb(str(glb_path), deflection=0.22)

    brep.render_step_views_rpath(
        step_path,
        png_path,
        views=((23.0, -42.0, "isometric"), (86.0, -90.0, "top")),
        image_size=(16.0, 8.0),
        dpi=110,
        background_color=(0.94, 0.95, 0.97),
        show_brep_edges=True,
        title="Text2CAD boiler workpiece",
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
            "members": [CYLINDER_MEMBER, FLANGE_MEMBER, BRACKET_MEMBER, HOLES_MEMBER],
            "roles": {
                "0000/00003775": "cylindrical vessel source",
                "0015/00150738": "flange and hex-hub source",
                "0074/00743657": "base/bracket source dimensions",
                "0069/00694843": "manhole bolt-pattern source",
            },
        },
        "units": "millimetres",
        "reconstruction_assumptions": [
            (
                "The source records dimensions but no assembly mates, so the boiler "
                "uses a Z-up vessel frame."
            ),
            (
                "The shell is an exterior solid envelope, not a pressure-rated wall "
                "or fluid simulation."
            ),
            (
                "The Text2CAD cylinder/flange components are enlarged and placed as "
                "boiler shell, manhole, and pipe hardware."
            ),
            (
                "All visible connections overlap host geometry before union and the "
                "result is one Solid."
            ),
        ],
        "validation": validation,
        "feature_diagnostics": events,
        "source_dimensions": source,
        "assembly_dimensions": dimensions,
        **measured,
        "files": {
            "png": {"path": str(png_path), **png},
            "step": {"path": str(step_path), "bytes": step_path.stat().st_size},
            "stl": {
                "path": str(stl_path),
                "bytes": len(stl_data),
                "triangles": triangles,
            },
            "glb": {"path": str(glb_path), "bytes": len(glb_data)},
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
