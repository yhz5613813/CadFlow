"""Build a detailed Text2CAD-derived vertical fire-tube boiler workpiece.

Local Text2CAD cylinders, flanges, brackets, hex hubs, and bolt patterns supply
the reusable component vocabulary. The source data has no assembly mates, so
this reconstruction uses a documented Z-up boiler frame. The pressure shell is
hollow and contains a furnace, tube sheets, fire tubes, stays, steam space, and
smokebox so an actual CAD cutaway reveals the internal gas and water passages.

The result is a visual mechanical reconstruction, not a pressure-rated design
or a thermal, combustion, flow, or structural simulation.
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


def _annulus_axis(
    model: cad.Model,
    outer_radius: float,
    inner_radius: float,
    length: float,
    base: tuple[float, float, float],
    axis: str,
    events: list[dict[str, object]],
    label: str,
) -> cad.Shape:
    outer = _axis_cylinder(model, outer_radius, length, base, axis)
    offsets = {
        "x": (-1.0, 0.0, 0.0),
        "xn": (1.0, 0.0, 0.0),
        "y": (0.0, -1.0, 0.0),
        "yn": (0.0, 1.0, 0.0),
        "z": (0.0, 0.0, -1.0),
    }
    if axis not in offsets:
        raise ValueError(f"unsupported annulus axis {axis}")
    offset = offsets[axis]
    inner_base = tuple(base[index] + offset[index] for index in range(3))
    inner = _axis_cylinder(model, inner_radius, length + 2.0, inner_base, axis)
    return _cut(model, outer, inner, label, events)


def _handwheel_z(
    model: cad.Model,
    center: tuple[float, float],
    z: float,
    radius: float,
    events: list[dict[str, object]],
    label: str,
) -> cad.Shape:
    wheel = _annulus_z(
        model,
        radius,
        radius - 2.5,
        2.5,
        z,
        events,
        f"{label} rim",
    )
    wheel = model.translate(wheel, x=center[0], y=center[1], z=0.0)
    spoke_length = 2.0 * radius - 2.5
    for index, angle in enumerate((0.0, 45.0, 90.0, 135.0), 1):
        spoke = model.box(spoke_length, 2.2, 2.5)
        spoke = model.translate(
            spoke,
            x=-spoke_length / 2.0,
            y=-1.1,
            z=0.0,
        )
        spoke = model.rotate(spoke, angle, axis=(0.0, 0.0, 1.0))
        spoke = model.translate(spoke, x=center[0], y=center[1], z=z)
        wheel = _union(model, wheel, spoke, f"{label} spoke {index}", events)
    hub = _axis_cylinder(model, 3.5, 4.0, (center[0], center[1], z - 0.75), "z")
    return _union(model, wheel, hub, f"{label} hub", events)


def build_boiler(
    model: cad.Model, source: dict[str, object]
) -> tuple[
    cad.Shape,
    cad.Shape,
    list[dict[str, object]],
    dict[str, float],
    list[dict[str, object]],
]:
    events: list[dict[str, object]] = []
    shell_r = 70.0
    shell_inner_r = 65.5
    shell_z = 30.0
    shell_h = 155.0
    bottom_z = 10.0
    head_h = 25.0
    lower_sheet_z = 72.0
    upper_sheet_z = 157.0
    tube_outer_r = 4.2
    tube_inner_r = 3.1

    # Hollow pressure boundary with formed lower and upper heads.
    body = _axis_cylinder(model, shell_r, shell_h, (0.0, 0.0, shell_z), "z")
    body = _valid(body, "outer shell barrel", events)
    bottom_head = model.cone(52.0, shell_r, head_h)
    bottom_head = model.translate(bottom_head, x=0.0, y=0.0, z=bottom_z)
    body = _union(model, body, bottom_head, "outer lower formed head", events)
    top_head = model.cone(shell_r, 52.0, head_h)
    top_head = model.translate(top_head, x=0.0, y=0.0, z=shell_z + shell_h - 5.0)
    body = _union(model, body, top_head, "outer upper formed head", events)

    inner_barrel = _axis_cylinder(
        model,
        shell_inner_r,
        151.0,
        (0.0, 0.0, 32.0),
        "z",
    )
    body = _cut(model, body, inner_barrel, "hollow shell water space", events)
    lower_void = model.cone(47.5, shell_inner_r, 20.0)
    lower_void = model.translate(lower_void, x=0.0, y=0.0, z=15.0)
    body = _cut(model, body, lower_void, "hollow lower head", events)
    upper_void = model.cone(shell_inner_r, 47.5, 19.0)
    upper_void = model.translate(upper_void, x=0.0, y=0.0, z=181.0)
    body = _cut(model, body, upper_void, "hollow upper head", events)

    # Tube sheets close the furnace and smokebox while remaining tied to shell.
    lower_sheet = _axis_cylinder(
        model,
        66.0,
        5.0,
        (0.0, 0.0, lower_sheet_z),
        "z",
    )
    body = _union(model, body, lower_sheet, "lower furnace tube sheet", events)
    upper_sheet = _axis_cylinder(
        model,
        66.0,
        5.0,
        (0.0, 0.0, upper_sheet_z),
        "z",
    )
    body = _union(model, body, upper_sheet, "upper smokebox tube sheet", events)

    # Water-backed combustion chamber and horizontal burner flame tube.
    chamber_outer = _axis_cylinder(model, 40.0, 41.0, (0.0, 0.0, 34.0), "z")
    chamber_inner = _axis_cylinder(model, 35.0, 38.0, (0.0, 0.0, 38.0), "z")
    chamber = _cut(
        model,
        chamber_outer,
        chamber_inner,
        "combustion chamber pressure wall",
        events,
    )
    body = _union(model, body, chamber, "combustion chamber assembly", events)
    furnace = _annulus_axis(
        model,
        24.0,
        19.0,
        65.0,
        (0.0, -75.0, 52.0),
        "y",
        events,
        "furnace flame tube wall",
    )
    body = _union(model, body, furnace, "furnace-to-chamber joint", events)
    furnace_opening = _axis_cylinder(
        model,
        19.0,
        54.0,
        (0.0, -83.0, 52.0),
        "y",
    )
    body = _cut(model, body, furnace_opening, "burner throat opening", events)

    # Eighteen small fire tubes plus a central uptake form the gas pass.
    tube_positions: list[tuple[float, float]] = []
    for ring_radius, count, offset in (
        (20.0, 6, 0.0),
        (42.0, 12, math.pi / 12.0),
    ):
        tube_positions.extend(
            (
                ring_radius * math.cos(2.0 * math.pi * index / count + offset),
                ring_radius * math.sin(2.0 * math.pi * index / count + offset),
            )
            for index in range(count)
        )
    for index, (x, y) in enumerate(tube_positions, 1):
        tube = _axis_cylinder(
            model,
            tube_outer_r,
            87.0,
            (x, y, lower_sheet_z + 2.0),
            "z",
        )
        body = _union(model, body, tube, f"fire tube outer wall {index}", events)

    uptake = _axis_cylinder(
        model,
        13.5,
        90.0,
        (0.0, 0.0, lower_sheet_z + 2.0),
        "z",
    )
    body = _union(model, body, uptake, "central gas uptake wall", events)

    smokebox = _annulus_z(
        model,
        54.0,
        49.0,
        31.0,
        upper_sheet_z + 2.0,
        events,
        "upper smokebox casing",
    )
    body = _union(model, body, smokebox, "smokebox-to-tube-sheet joint", events)

    for index, (x, y) in enumerate(tube_positions, 1):
        bore = _axis_cylinder(
            model,
            tube_inner_r,
            97.0,
            (x, y, lower_sheet_z - 3.0),
            "z",
        )
        body = _cut(model, body, bore, f"fire tube gas bore {index}", events)

    # Peripheral stays support both flat tube sheets without blocking smoke flow.
    stay_positions: list[tuple[float, float]] = []
    for index in range(6):
        angle = 2.0 * math.pi * index / 6.0 + math.pi / 6.0
        x = 59.0 * math.cos(angle)
        y = 59.0 * math.sin(angle)
        stay_positions.append((x, y))
        stay = _axis_cylinder(
            model,
            2.2,
            84.0,
            (x, y, lower_sheet_z + 3.0),
            "z",
        )
        body = _union(model, body, stay, f"tube-sheet stay rod {index + 1}", events)

    # Six riser holes connect the upper steam space around the smokebox casing.
    for index in range(6):
        angle = 2.0 * math.pi * index / 6.0
        x = 59.0 * math.cos(angle)
        y = 59.0 * math.sin(angle)
        riser_hole = _axis_cylinder(
            model,
            3.0,
            12.0,
            (x, y, upper_sheet_z - 3.0),
            "z",
        )
        body = _cut(model, body, riser_hole, f"steam riser port {index + 1}", events)

    dry_pipe = _annulus_axis(
        model,
        6.5,
        4.5,
        77.0,
        (-15.0, 50.0, 149.0),
        "x",
        events,
        "internal dry-steam collector",
    )
    body = _union(model, body, dry_pipe, "dry pipe shell connection", events)
    fusible_plug = _hex_z(model, 7.0, 5.0, (0.0, -28.0), lower_sheet_z - 5.0)
    body = _union(model, body, fusible_plug, "fusible crown plug", events)

    # Central chimney carries gas from the smokebox through the upper head.
    neck = _axis_cylinder(model, 24.0, 14.0, (0.0, 0.0, 201.0), "z")
    body = _union(model, body, neck, "chimney neck", events)
    stack = _axis_cylinder(model, 19.0, 28.0, (0.0, 0.0, 212.0), "z")
    body = _union(model, body, stack, "chimney stack", events)
    flare = model.cone(19.0, 15.0, 20.0)
    flare = model.translate(flare, x=0.0, y=0.0, z=238.0)
    body = _union(model, body, flare, "chimney tapered crown", events)
    rain_cap = model.cone(23.0, 18.0, 5.0)
    rain_cap = model.translate(rain_cap, x=0.0, y=0.0, z=257.0)
    body = _union(model, body, rain_cap, "chimney rain cap", events)
    central_bore = _axis_cylinder(
        model,
        10.5,
        196.0,
        (0.0, 0.0, lower_sheet_z - 3.0),
        "z",
    )
    body = _cut(model, body, central_bore, "central uptake and chimney bore", events)

    # Branch here: the cutaway is a true quarter removal of the pressure core.
    cutaway_tool = model.box(120.0, 120.0, 290.0)
    cutaway_tool = model.translate(cutaway_tool, x=0.0, y=-120.0, z=-10.0)
    section = _cut(model, body, cutaway_tool, "quarter cutaway pressure core", events)

    base_ring = _axis_cylinder(model, 78.0, 10.0, (0.0, 0.0, 5.0), "z")
    body = _union(model, body, base_ring, "boiler foundation ring", events)

    # External cladding bands remain annular so they do not fill the vessel.
    for index, z in enumerate((62.0, 116.0, 170.0), 1):
        band = _annulus_z(
            model,
            72.5,
            69.0,
            4.0,
            z,
            events,
            f"cladding band ring {index}",
        )
        body = _union(model, body, band, f"shell reinforcement band {index}", events)

    # Four feet, legs, and gussets anchor the vessel to the foundation.
    leg_locations = ((-52.0, -43.0), (52.0, -43.0), (-52.0, 43.0), (52.0, 43.0))
    for index, (x, y) in enumerate(leg_locations, 1):
        foot = model.box(28.0, 28.0, 6.0)
        foot = model.translate(foot, x=x - 14.0, y=y - 14.0, z=0.0)
        body = _union(model, body, foot, f"boiler foot plate {index}", events)
        leg = model.box(16.0, 16.0, 34.0)
        leg = model.translate(leg, x=x - 8.0, y=y - 8.0, z=4.0)
        body = _union(model, body, leg, f"boiler support leg {index}", events)
        gusset = model.box(7.0, 22.0, 25.0)
        gusset = model.translate(gusset, x=x - 3.5, y=y - 11.0, z=18.0)
        body = _union(model, body, gusset, f"boiler leg gusset {index}", events)

    # Four drilled lifting lugs are welded near the upper shell course.
    lug_specs = (
        (62.0, -4.0, "x positive"),
        (-72.0, -4.0, "x negative"),
        (-4.0, 62.0, "y positive"),
        (-4.0, -72.0, "y negative"),
    )
    for index, (x, y, label) in enumerate(lug_specs, 1):
        lug = model.box(10.0, 10.0, 24.0)
        lug = model.translate(lug, x=x, y=y, z=169.0)
        if "x" in label:
            hole = _axis_cylinder(model, 3.0, 12.0, (x + 5.0, y - 1.0, 185.0), "y")
        else:
            hole = _axis_cylinder(model, 3.0, 12.0, (x - 1.0, y + 5.0, 185.0), "x")
        lug = _cut(model, lug, hole, f"lifting lug hole {index}", events)
        body = _union(model, body, lug, f"lifting lug {index}", events)

    # Side manhole with pressure opening, flange, cover, and eight bolts.
    manhole_yz = (20.0, 126.0)
    manhole_opening = _axis_cylinder(
        model,
        14.0,
        22.0,
        (-79.0, manhole_yz[0], manhole_yz[1]),
        "x",
    )
    body = _cut(model, body, manhole_opening, "side manhole opening", events)
    ring = _annulus_axis(
        model,
        26.0,
        14.0,
        8.0,
        (-66.0, manhole_yz[0], manhole_yz[1]),
        "xn",
        events,
        "side manhole flange ring",
    )
    body = _union(model, body, ring, "side manhole flange", events)
    cover = _axis_cylinder(
        model,
        19.0,
        5.0,
        (-74.0, manhole_yz[0], manhole_yz[1]),
        "xn",
    )
    body = _union(model, body, cover, "side manhole cover", events)
    bolt_r = float(source["bolt_radius_mm"])
    bolt_circle = 21.5
    bolt_count = int(source["bolt_count"])
    for index in range(bolt_count):
        angle = 2.0 * math.pi * index / bolt_count
        y = manhole_yz[0] + bolt_circle * math.cos(angle)
        z = manhole_yz[1] + bolt_circle * math.sin(angle)
        stem = _axis_cylinder(model, bolt_r + 1.0, 7.0, (-77.0, y, z), "xn")
        body = _union(model, body, stem, f"manhole bolt stem {index + 1}", events)
        head = _hex_x(model, bolt_r * 1.8, 4.0, (y, z), -84.0)
        body = _union(model, body, head, f"manhole bolt head {index + 1}", events)

    # Burner door, air register, fan housing, observation port, and cleanout.
    door_ring = _annulus_axis(
        model,
        31.0,
        19.0,
        8.0,
        (0.0, -68.0, 52.0),
        "yn",
        events,
        "burner door flange ring",
    )
    body = _union(model, body, door_ring, "burner door flange", events)
    door_cover = _annulus_axis(
        model,
        26.0,
        11.0,
        5.0,
        (0.0, -76.0, 52.0),
        "yn",
        events,
        "burner door annular cover",
    )
    body = _union(model, body, door_cover, "burner door cover", events)
    for index in range(8):
        angle = 2.0 * math.pi * index / 8
        x = 21.0 * math.cos(angle)
        z = 52.0 + 21.0 * math.sin(angle)
        stem = _axis_cylinder(model, 3.2, 7.0, (x, -77.0, z), "yn")
        body = _union(model, body, stem, f"furnace bolt stem {index + 1}", events)
        head = _hex_y(model, 5.5, 4.0, (x, z), -84.0, direction=-1.0)
        body = _union(model, body, head, f"furnace bolt head {index + 1}", events)
    register_outer = model.cone(18.0, 12.0, 12.0)
    register_inner = model.cone(12.0, 7.0, 14.0)
    register_outer = model.rotate(register_outer, 90.0, axis=(1.0, 0.0, 0.0))
    register_inner = model.rotate(register_inner, 90.0, axis=(1.0, 0.0, 0.0))
    register_outer = model.translate(register_outer, x=0.0, y=-80.0, z=52.0)
    register_inner = model.translate(register_inner, x=0.0, y=-79.0, z=52.0)
    register = _cut(
        model,
        register_outer,
        register_inner,
        "burner conical air register",
        events,
    )
    body = _union(model, body, register, "burner air register assembly", events)
    fan = _annulus_axis(
        model,
        16.0,
        7.0,
        12.0,
        (0.0, -91.0, 52.0),
        "yn",
        events,
        "forced-draft fan housing",
    )
    body = _union(model, body, fan, "burner fan housing assembly", events)
    fan_motor = _axis_cylinder(model, 9.0, 15.0, (0.0, -103.0, 52.0), "yn")
    body = _union(model, body, fan_motor, "burner fan motor", events)
    observation = _annulus_axis(
        model,
        8.0,
        3.5,
        9.0,
        (28.0, -64.0, 66.0),
        "yn",
        events,
        "flame observation port",
    )
    body = _union(model, body, observation, "flame observation assembly", events)

    cleanout = model.box(48.0, 8.0, 22.0)
    cleanout = model.translate(cleanout, x=-24.0, y=-59.0, z=16.0)
    body = _union(model, body, cleanout, "lower cleanout door", events)
    for index, x in enumerate((-18.0, 18.0), 1):
        for z in (21.0, 33.0):
            bolt = _axis_cylinder(model, 2.5, 6.0, (x, -57.0, z), "yn")
            body = _union(model, body, bolt, f"cleanout door bolt {index}-{z:g}", events)

    # Two independent spring safety valves with discharge branches.
    safety_positions = ((-25.0, 22.0, "left"), (25.0, 22.0, "right"))
    for x, y, side in safety_positions:
        boss = _axis_cylinder(model, 8.0, 13.0, (x, y, 194.0), "z")
        body = _union(model, body, boss, f"{side} safety valve nozzle", events)
        valve_body = _hex_z(model, 11.0, 8.0, (x, y), 204.0)
        body = _union(model, body, valve_body, f"{side} safety valve body", events)
        bonnet = _axis_cylinder(model, 5.0, 18.0, (x, y, 211.0), "z")
        body = _union(model, body, bonnet, f"{side} safety spring bonnet", events)
        cap = _hex_z(model, 7.0, 4.0, (x, y), 227.0)
        body = _union(model, body, cap, f"{side} safety valve cap", events)
        direction = "xn" if x < 0.0 else "x"
        branch_x = x - 2.0 if x < 0.0 else x + 2.0
        discharge = _axis_cylinder(
            model,
            3.5,
            18.0,
            (branch_x, y, 220.0),
            direction,
        )
        body = _union(model, body, discharge, f"{side} safety discharge", events)
        port = _axis_cylinder(model, 3.2, 28.0, (x, y, 189.0), "z")
        body = _cut(model, body, port, f"{side} safety valve pressure bore", events)

    # Main steam stop valve with globe body, bonnet, stem, and handwheel.
    steam_opening = _axis_cylinder(model, 5.5, 18.0, (55.0, 20.0, 149.0), "x")
    body = _cut(model, body, steam_opening, "main steam shell opening", events)
    steam_pipe = _annulus_axis(
        model,
        9.0,
        5.5,
        35.0,
        (58.0, 20.0, 149.0),
        "x",
        events,
        "main steam outlet pipe wall",
    )
    body = _union(model, body, steam_pipe, "main steam outlet pipe", events)
    steam_flange = _annulus_axis(
        model,
        16.0,
        5.5,
        6.0,
        (68.0, 20.0, 149.0),
        "x",
        events,
        "main steam outlet flange ring",
    )
    body = _union(model, body, steam_flange, "main steam outlet flange", events)
    steam_globe = model.sphere(14.0)
    steam_globe = model.translate(steam_globe, x=84.0, y=20.0, z=149.0)
    body = _union(model, body, steam_globe, "main steam stop valve globe", events)
    steam_bonnet = _axis_cylinder(model, 6.0, 22.0, (84.0, 20.0, 158.0), "z")
    body = _union(model, body, steam_bonnet, "main steam valve bonnet", events)
    steam_wheel = _handwheel_z(
        model,
        (84.0, 20.0),
        179.0,
        12.0,
        events,
        "main steam handwheel",
    )
    body = _union(model, body, steam_wheel, "main steam handwheel assembly", events)
    # Feed check valve mirrors the steam valve at the lower water space.
    feed_opening = _axis_cylinder(model, 4.5, 24.0, (-78.0, -18.0, 82.0), "x")
    body = _cut(model, body, feed_opening, "feedwater shell opening", events)
    feed_pipe = _annulus_axis(
        model,
        8.0,
        4.5,
        34.0,
        (-58.0, -18.0, 82.0),
        "xn",
        events,
        "feedwater inlet pipe wall",
    )
    body = _union(model, body, feed_pipe, "feedwater inlet pipe", events)
    feed_flange = _annulus_axis(
        model,
        15.0,
        4.5,
        6.0,
        (-68.0, -18.0, 82.0),
        "xn",
        events,
        "feedwater inlet flange ring",
    )
    body = _union(model, body, feed_flange, "feedwater inlet flange", events)
    feed_globe = model.sphere(13.0)
    feed_globe = model.translate(feed_globe, x=-85.0, y=-18.0, z=82.0)
    body = _union(model, body, feed_globe, "feed check valve globe", events)
    feed_bonnet = _axis_cylinder(model, 5.5, 18.0, (-85.0, -18.0, 91.0), "z")
    body = _union(model, body, feed_bonnet, "feed check valve bonnet", events)
    feed_wheel = _handwheel_z(
        model,
        (-85.0, -18.0),
        108.0,
        10.0,
        events,
        "feed check handwheel",
    )
    body = _union(model, body, feed_wheel, "feed check handwheel assembly", events)
    # Pressure gauge with siphon loop, dial, hub, and pointer.
    gauge_branch = _axis_cylinder(model, 3.5, 20.0, (20.0, -62.0, 157.0), "yn")
    body = _union(model, body, gauge_branch, "pressure gauge shell branch", events)
    lower_elbow = model.sphere(4.5)
    lower_elbow = model.translate(lower_elbow, x=20.0, y=-82.0, z=157.0)
    body = _union(model, body, lower_elbow, "pressure gauge lower siphon elbow", events)
    siphon_riser = _axis_cylinder(model, 3.5, 19.0, (20.0, -82.0, 157.0), "z")
    body = _union(model, body, siphon_riser, "pressure gauge siphon riser", events)
    upper_elbow = model.sphere(4.5)
    upper_elbow = model.translate(upper_elbow, x=20.0, y=-82.0, z=176.0)
    body = _union(model, body, upper_elbow, "pressure gauge upper siphon elbow", events)
    dial_stem = _axis_cylinder(model, 3.5, 9.0, (20.0, -82.0, 176.0), "yn")
    body = _union(model, body, dial_stem, "pressure gauge dial stem", events)
    gauge = _axis_cylinder(model, 13.0, 5.0, (20.0, -89.0, 176.0), "yn")
    body = _union(model, body, gauge, "pressure gauge dial housing", events)
    gauge_hub = _axis_cylinder(model, 2.0, 2.0, (20.0, -94.0, 176.0), "yn")
    body = _union(model, body, gauge_hub, "pressure gauge pointer hub", events)
    pointer = model.box(1.5, 2.0, 10.0)
    pointer = model.translate(pointer, x=-0.75, y=-1.0, z=0.0)
    pointer = model.rotate(pointer, -35.0, axis=(0.0, 1.0, 0.0))
    pointer = model.translate(pointer, x=20.0, y=-94.0, z=176.0)
    body = _union(model, body, pointer, "pressure gauge pointer", events)

    # Two independent sight glasses, each with isolation taps and guard rods.
    for gauge_index, level_x in enumerate((-34.0, 34.0), 1):
        for label, z in (("lower", 113.0), ("upper", 148.0)):
            tap_bore = _axis_cylinder(
                model,
                2.3,
                18.0,
                (level_x, -74.0, z),
                "y",
            )
            body = _cut(
                model,
                body,
                tap_bore,
                f"water gauge {gauge_index} {label} pressure bore",
                events,
            )
            tap = _axis_cylinder(model, 5.0, 20.0, (level_x, -61.0, z), "yn")
            body = _union(
                model,
                body,
                tap,
                f"water gauge {gauge_index} {label} tap",
                events,
            )
            gland = _hex_y(model, 7.0, 5.0, (level_x, z), -78.0, direction=-1.0)
            body = _union(
                model,
                body,
                gland,
                f"water gauge {gauge_index} {label} gland",
                events,
            )
        sight_glass = _axis_cylinder(
            model,
            2.6,
            35.0,
            (level_x, -80.0, 113.0),
            "z",
        )
        body = _union(
            model,
            body,
            sight_glass,
            f"water gauge {gauge_index} sight glass",
            events,
        )
        for guard_index, guard_x in enumerate((level_x - 5.0, level_x + 5.0), 1):
            guard = _axis_cylinder(model, 1.5, 39.0, (guard_x, -80.0, 111.0), "z")
            body = _union(
                model,
                body,
                guard,
                f"water gauge {gauge_index} guard rod {guard_index}",
                events,
            )

    # Three level limiters represent high, low, and low-low burner trips.
    for index, z in enumerate((121.0, 136.0, 151.0), 1):
        probe_bore = _axis_cylinder(model, 2.0, 17.0, (58.0, -30.0, z), "x")
        body = _cut(model, body, probe_bore, f"level limiter bore {index}", events)
        probe = _annulus_axis(
            model,
            5.0,
            2.0,
            18.0,
            (60.0, -30.0, z),
            "x",
            events,
            f"level limiter probe housing {index}",
        )
        body = _union(model, body, probe, f"level limiter nozzle {index}", events)
        box = model.box(10.0, 12.0, 10.0)
        box = model.translate(box, x=76.0, y=-36.0, z=z - 5.0)
        body = _union(model, body, box, f"level limiter switch box {index}", events)

    # Bottom blowdown globe valve and handwheel flush sediment from the head.
    blowdown_opening = _axis_cylinder(model, 4.0, 23.0, (-76.0, 0.0, 24.0), "x")
    body = _cut(model, body, blowdown_opening, "blowdown shell opening", events)
    blowdown_pipe = _annulus_axis(
        model,
        7.0,
        4.0,
        34.0,
        (-55.0, 0.0, 24.0),
        "xn",
        events,
        "bottom blowdown pipe wall",
    )
    body = _union(model, body, blowdown_pipe, "bottom blowdown pipe", events)
    blowdown_flange = _annulus_axis(
        model,
        13.0,
        4.0,
        6.0,
        (-64.0, 0.0, 24.0),
        "xn",
        events,
        "bottom blowdown flange ring",
    )
    body = _union(model, body, blowdown_flange, "bottom blowdown flange", events)
    blowdown_globe = model.sphere(11.0)
    blowdown_globe = model.translate(blowdown_globe, x=-84.0, y=0.0, z=24.0)
    body = _union(model, body, blowdown_globe, "blowdown valve globe", events)
    blowdown_bonnet = _axis_cylinder(model, 4.5, 15.0, (-84.0, 0.0, 31.0), "z")
    body = _union(model, body, blowdown_bonnet, "blowdown valve bonnet", events)
    blowdown_wheel = _handwheel_z(
        model,
        (-84.0, 0.0),
        45.0,
        9.0,
        events,
        "blowdown handwheel",
    )
    body = _union(model, body, blowdown_wheel, "blowdown handwheel assembly", events)
    # Rear handholes, a sampling cock, and an exterior identification plate.
    for index, (x, z) in enumerate(((-28.0, 96.0), (28.0, 122.0)), 1):
        handhole = _annulus_axis(
            model,
            13.0,
            7.0,
            7.0,
            (x, 62.0, z),
            "y",
            events,
            f"rear handhole flange {index}",
        )
        body = _union(model, body, handhole, f"rear handhole ring {index}", events)
        handhole_cover = _axis_cylinder(model, 10.0, 4.0, (x, 69.0, z), "y")
        body = _union(
            model,
            body,
            handhole_cover,
            f"rear handhole cover {index}",
            events,
        )
    sample_cock = _axis_cylinder(model, 3.5, 21.0, (-62.0, 42.0, 106.0), "xn")
    body = _union(model, body, sample_cock, "boiler-water sampling cock", events)
    sample_head = _hex_x(model, 6.0, 5.0, (42.0, 106.0), -82.0)
    body = _union(model, body, sample_head, "sampling cock valve head", events)
    nameplate = model.box(38.0, 3.0, 20.0)
    nameplate = model.translate(nameplate, x=-19.0, y=-71.5, z=88.0)
    body = _union(model, body, nameplate, "boiler identification plate", events)

    dimensions = {
        "shell_radius_mm": shell_r,
        "shell_wall_mm": shell_r - shell_inner_r,
        "shell_height_mm": shell_h,
        "overall_height_mm": 262.0,
        "lower_tube_sheet_z_mm": lower_sheet_z,
        "upper_tube_sheet_z_mm": upper_sheet_z,
        "fire_tube_outer_diameter_mm": 2.0 * tube_outer_r,
        "fire_tube_inner_diameter_mm": 2.0 * tube_inner_r,
        "fire_tube_count": float(len(tube_positions)),
        "central_uptake_count": 1.0,
        "tube_sheet_stay_count": float(len(stay_positions)),
        "steam_riser_port_count": 6.0,
        "base_length_mm": float(source["base_length_mm"]),
        "base_width_mm": float(source["base_width_mm"]),
        "manhole_bolt_count": float(bolt_count),
        "furnace_bolt_count": 8.0,
        "support_leg_count": 4.0,
        "safety_valve_count": 2.0,
        "water_level_gauge_count": 2.0,
        "water_level_limiter_count": 3.0,
    }
    inventory = [
        {"group": "pressure boundary", "component": "shell barrel", "count": 1},
        {"group": "pressure boundary", "component": "formed heads", "count": 2},
        {"group": "pressure boundary", "component": "tube sheets", "count": 2},
        {"group": "combustion", "component": "furnace flame tube", "count": 1},
        {"group": "combustion", "component": "combustion chamber", "count": 1},
        {"group": "heat transfer", "component": "fire tubes", "count": len(tube_positions)},
        {"group": "heat transfer", "component": "central uptake", "count": 1},
        {"group": "structure", "component": "tube-sheet stays", "count": len(stay_positions)},
        {"group": "gas path", "component": "smokebox casing", "count": 1},
        {"group": "gas path", "component": "chimney sections", "count": 4},
        {"group": "steam", "component": "steam riser ports", "count": 6},
        {"group": "steam", "component": "dry-steam collector", "count": 1},
        {"group": "mounting", "component": "safety valves", "count": 2},
        {"group": "mounting", "component": "main steam stop valve", "count": 1},
        {"group": "mounting", "component": "feed check valve", "count": 1},
        {"group": "mounting", "component": "pressure gauge and siphon", "count": 1},
        {"group": "mounting", "component": "water level gauges", "count": 2},
        {"group": "control", "component": "water level limiters", "count": 3},
        {"group": "mounting", "component": "fusible plug", "count": 1},
        {"group": "mounting", "component": "blowdown valve", "count": 1},
        {"group": "inspection", "component": "side manhole", "count": 1},
        {"group": "inspection", "component": "rear handholes", "count": 2},
        {"group": "inspection", "component": "flame observation port", "count": 1},
        {"group": "inspection", "component": "cleanout door", "count": 1},
        {"group": "combustion", "component": "burner air register", "count": 1},
        {"group": "combustion", "component": "forced-draft fan", "count": 1},
        {"group": "mounting", "component": "sampling cock", "count": 1},
        {"group": "structure", "component": "support legs and feet", "count": 4},
        {"group": "structure", "component": "leg gussets", "count": 4},
        {"group": "structure", "component": "lifting lugs", "count": 4},
        {"group": "cladding", "component": "shell bands", "count": 3},
        {"group": "identification", "component": "nameplate", "count": 1},
    ]
    return body, section, events, dimensions, inventory


def _png_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG signature")
    width, height = struct.unpack(">II", data[16:24])
    return {"width": width, "height": height, "bytes": len(data)}


def _stl_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"invalid binary STL: {path}")
    triangles = struct.unpack("<I", data[80:84])[0]
    if len(data) != 84 + 50 * triangles:
        raise ValueError(f"invalid binary STL length: {path}")
    return {"triangles": triangles, "bytes": len(data)}


def _glb_info(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if len(data) < 12:
        raise ValueError(f"invalid GLB: {path}")
    magic, version, declared_length = struct.unpack("<4sII", data[:12])
    if magic != b"glTF" or version != 2 or declared_length != len(data):
        raise ValueError(f"invalid GLB header: {path}")
    return {"version": version, "bytes": len(data)}


def _normalize_step(path: Path) -> None:
    lines = path.read_bytes().splitlines()
    path.write_bytes(b"\n".join(line.rstrip(b" \t") for line in lines) + b"\n")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUTPUT_DIR / "boiler.png"
    section_png_path = OUTPUT_DIR / "boiler_section.png"
    step_path = OUTPUT_DIR / "boiler.step"
    section_step_path = OUTPUT_DIR / "boiler_section.step"
    stl_path = OUTPUT_DIR / "boiler.stl"
    section_stl_path = OUTPUT_DIR / "boiler_section.stl"
    glb_path = OUTPUT_DIR / "boiler.glb"
    section_glb_path = OUTPUT_DIR / "boiler_section.glb"
    report_path = OUTPUT_DIR / "report.json"
    source = load_source_dimensions()
    with cad.Model() as model:
        body, section, events, dimensions, inventory = build_boiler(model, source)
        validation = body.validate().to_dict()
        section_validation = section.validate().to_dict()
        measured = {
            "topology": body.topology,
            "volume_mm3": body.volume,
            "area_mm2": body.area,
            "bbox_mm": body.bbox,
        }
        section_measured = {
            "topology": section.topology,
            "volume_mm3": section.volume,
            "area_mm2": section.area,
            "bbox_mm": section.bbox,
        }
        if not validation["ok"] or measured["topology"].get("solids") != 1:
            raise RuntimeError(f"final validation failed: {validation}, {measured}")
        if (
            not section_validation["ok"]
            or section_measured["topology"].get("solids") != 1
        ):
            raise RuntimeError(
                f"section validation failed: {section_validation}, {section_measured}"
            )
        body.export_step(str(step_path))
        body.export_stl(str(stl_path), binary=True)
        body.export_preview_glb(str(glb_path), deflection=0.20)
        section.export_step(str(section_step_path))
        section.export_stl(str(section_stl_path), binary=True)
        section.export_preview_glb(str(section_glb_path), deflection=0.16)

    _normalize_step(step_path)
    _normalize_step(section_step_path)

    brep.render_step_views_rpath(
        step_path,
        png_path,
        views=(
            (28.0, -45.0, "detailed isometric"),
            (0.0, 0.0, "front elevation"),
        ),
        image_size=(16.0, 8.0),
        dpi=110,
        background_color=(0.94, 0.95, 0.97),
        show_brep_edges=True,
        linear_deflection=0.16,
        angular_deflection=0.18,
        title="Detailed Text2CAD vertical fire-tube boiler",
    )
    brep.render_step_views_rpath(
        section_step_path,
        section_png_path,
        views=(
            (28.0, -45.0, "quarter cutaway"),
            (0.0, 0.0, "combustion and tube section"),
        ),
        image_size=(16.0, 8.0),
        dpi=110,
        background_color=(0.94, 0.95, 0.97),
        show_brep_edges=True,
        linear_deflection=0.12,
        angular_deflection=0.16,
        title="Vertical fire-tube boiler - true CAD cutaway",
    )
    png = _png_info(png_path)
    section_png = _png_info(section_png_path)
    stl = _stl_info(stl_path)
    section_stl = _stl_info(section_stl_path)
    glb = _glb_info(glb_path)
    section_glb = _glb_info(section_glb_path)
    modeled_instances = sum(int(item["count"]) for item in inventory)
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
        "research_basis": [
            {
                "title": "Steam Generation (Boilers) Questions & Answers",
                "url": (
                    "https://github.com/learner20011-gif/Obsidian_uni/blob/"
                    "fcc3bd10ee1b79be377b89be7dcc23b0ab88b2dc/"
                    "2-1/Mecha/Boilers_Questions.md"
                ),
                "used_for": (
                    "vertical multi-tube fire-tube layout, mountings, accessories, "
                    "and gas-flow sequence"
                ),
            },
            {
                "title": "Technical Guidelines for Boiler Inspection",
                "url": (
                    "https://github.com/munim430-ai/Vantage_legal_brain/blob/"
                    "4e92157b6b1b788a28f4411663af9b169daaa7cc/vantage/docs/"
                    "regulations/safety-fire/Boiler%20Inspection%20Rules.md"
                ),
                "used_for": (
                    "dual safety valves, gauge siphon, inspection openings, and "
                    "high/low/low-low water protection"
                ),
            },
        ],
        "units": "millimetres",
        "reconstruction_assumptions": [
            (
                "The source records dimensions but no assembly mates, so the boiler "
                "uses a Z-up vessel frame."
            ),
            (
                "The shell is hollowed to a representative 4.5 mm visual wall, but "
                "the value is not a pressure-code calculation."
            ),
            (
                "The internal layout is a compact vertical multi-tube fire-tube "
                "boiler with an oil/gas burner and forced-draft fan."
            ),
            (
                "Water, steam, flame, and flue gas are represented by void spaces; "
                "no fluid bodies or operating simulation are included."
            ),
        ],
        "component_type_count": len(inventory),
        "modeled_component_instances": modeled_instances,
        "component_inventory": inventory,
        "gas_path": [
            "forced-draft fan and air register",
            "horizontal furnace flame tube",
            "water-backed combustion chamber",
            "18 fire tubes plus central uptake",
            "upper smokebox",
            "central chimney",
        ],
        "validation": {
            "complete_boiler": validation,
            "quarter_cutaway": section_validation,
        },
        "feature_diagnostics": events,
        "source_dimensions": source,
        "assembly_dimensions": dimensions,
        "complete_boiler_measurements": measured,
        "quarter_cutaway_measurements": section_measured,
        "files": {
            "complete_boiler": {
                "png": {"path": str(png_path), **png},
                "step": {
                    "path": str(step_path),
                    "bytes": step_path.stat().st_size,
                },
                "stl": {"path": str(stl_path), **stl},
                "glb": {"path": str(glb_path), **glb},
            },
            "quarter_cutaway": {
                "png": {"path": str(section_png_path), **section_png},
                "step": {
                    "path": str(section_step_path),
                    "bytes": section_step_path.stat().st_size,
                },
                "stl": {"path": str(section_stl_path), **section_stl},
                "glb": {"path": str(section_glb_path), **section_glb},
            },
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
