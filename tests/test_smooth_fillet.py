from __future__ import annotations

from collections import Counter
import math

import numpy as np
import pytest

import cadflow as cad
from test_surface_analysis import requires_occt


def _edge_index(model: cad.Model, shape: cad.Shape, target) -> int:
    edges = model.edges(shape)
    target = np.asarray(target, dtype=float)
    return min(
        range(len(edges)),
        key=lambda index: float(np.linalg.norm(np.asarray(edges[index].center_of_mass) - target)),
    )


def _rounds(shape: cad.Shape) -> list[dict]:
    return [edge for edge in shape.continuity()["edges"] if edge["level"] != "G0"]


def _cross_curvature(model: cad.Model, shape: cad.Shape, height: float) -> np.ndarray:
    """Curvature along the iso-line that crosses the round at `height`."""
    face = next(
        face for face in model.faces(shape)
        if face.surface_metrics()["surface_geometry"] not in {"plane", "cylinder"}
    )
    grid = face.curvature_samples(101, 101)
    lines = [grid[i * 101:(i + 1) * 101] for i in range(101)] + [grid[j::101] for j in range(101)]
    line = min(
        lines,
        key=lambda samples: np.ptp([s["point"][2] for s in samples])
        + abs(np.mean([s["point"][2] for s in samples]) - height),
    )
    return np.array([
        max(abs(s["principal_curvature_min"]), abs(s["principal_curvature_max"])) for s in line
    ])


@requires_occt
def test_box_edge_becomes_curvature_continuous() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        edge = _edge_index(model, box, (0, 0, 15))
        rounded = model.fillet(box, 3.0, [edge])
        smooth = model.smooth_fillet(box, 3.0, [edge])
        assert smooth.kind == "smooth_fillet"
        assert smooth.topology == rounded.topology
        # A G2 transition leaves each plane with zero curvature, so it keeps
        # more material than the arc but never reaches the sharp corner.
        assert rounded.volume < smooth.volume < box.volume
        assert [edge["level"] for edge in _rounds(rounded)] == ["G1", "G1"]
        trims = _rounds(smooth)
        assert [edge["level"] for edge in trims] == ["G2", "G2"]
        for trim in trims:
            assert trim["max_gap"] < 1e-6 and trim["max_angle_degrees"] < 1e-4
        assert smooth.surface_quality()["issues"] == []


@requires_occt
def test_default_tension_gives_one_central_curvature_peak() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        edge = _edge_index(model, box, (0, 0, 15))
        profile = _cross_curvature(model, model.smooth_fillet(box, 3.0, [edge]), 15.0)
        assert profile[0] < 1e-9 and profile[-1] < 1e-9
        peaks = np.flatnonzero((profile[1:-1] > profile[:-2]) & (profile[1:-1] > profile[2:]))
        assert len(peaks) == 1
        assert abs(peaks[0] + 1 - 50) <= 1
        # A short fixed tension gives the double-humped profile auto avoids.
        short = _cross_curvature(model, model.smooth_fillet(box, 3.0, [edge], tension=1.0), 15.0)
        humps = np.flatnonzero((short[1:-1] > short[:-2]) & (short[1:-1] > short[2:]))
        assert len(humps) == 2


@requires_occt
def test_closed_rim_of_a_cylinder() -> None:
    with cad.Model() as model:
        cylinder = model.cylinder(5.0, 10.0)
        rim = _edge_index(model, cylinder, (0, 0, 10))
        rounded = model.fillet(cylinder, 1.5, [rim])
        smooth = model.smooth_fillet(cylinder, 1.5, [rim])
        assert rounded.volume < smooth.volume < cylinder.volume
        assert [edge["level"] for edge in _rounds(smooth)] == ["G2", "G2"]
        assert smooth.surface_quality()["issues"] == []


@requires_occt
def test_matches_nonzero_curvature_of_a_freeform_side(tmp_path) -> None:
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire,
    )
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepTools import BRepTools
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt, gp_Vec

    points = [(20, 0), (23, 5), (22, 11), (17, 17), (10, 20)]
    array = TColgp_Array1OfPnt(1, len(points))
    for index, (x, y) in enumerate(points, start=1):
        array.SetValue(index, gp_Pnt(x, y, 0))
    wire = BRepBuilderAPI_MakeWire()
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(20, 0, 0)).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(GeomAPI_PointsToBSpline(array).Curve()).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(10, 20, 0), gp_Pnt(0, 20, 0)).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 20, 0), gp_Pnt(0, 0, 0)).Edge())
    prism = BRepPrimAPI_MakePrism(
        BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, 10)).Shape()
    path = tmp_path / "prism.brep"
    BRepTools.Write_s(prism, str(path))

    with cad.Model() as model:
        part = model.import_brep(str(path))
        edge = _edge_index(model, part, (20, 0, 5))  # plane meets the B-spline side
        rounded_trims = _rounds(model.fillet(part, 2.0, [edge]))
        smooth_trims = _rounds(model.smooth_fillet(part, 2.0, [edge]))
        freeform = [t for t in rounded_trims if abs(t["curvature_a"]) > 1e-3 and abs(t["curvature_b"]) > 1e-3]
        assert freeform and freeform[0]["max_curvature_ratio"] > 0.5  # arc misses the B-spline curvature
        assert [t["level"] for t in smooth_trims] == ["G2", "G2"]
        matched = max(smooth_trims, key=lambda t: abs(t["curvature_a"]))
        assert abs(matched["curvature_a"]) > 0.05  # genuinely curved support
        assert matched["max_curvature_ratio"] < 1e-6


@requires_occt
def test_separate_edges_are_rounded_together() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        edges = [_edge_index(model, box, (0, 0, 15)), _edge_index(model, box, (10, 20, 15))]
        smooth = model.smooth_fillet(box, 2.0, edges)
        assert [edge["level"] for edge in _rounds(smooth)] == ["G2"] * 4
        assert smooth.topology["faces"] == 8


def _levels(shape: cad.Shape) -> Counter:
    return Counter(edge["level"] for edge in shape.continuity()["edges"])


def _prism(path, sides: int, radius: float = 6.0, height: float = 8.0) -> str:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt, gp_Vec

    polygon = BRepBuilderAPI_MakePolygon()
    for k in range(sides):
        angle = 2.0 * math.pi * k / sides
        polygon.Add(gp_Pnt(radius * math.cos(angle), radius * math.sin(angle), 0.0))
    polygon.Close()
    solid = BRepPrimAPI_MakePrism(
        BRepBuilderAPI_MakeFace(polygon.Wire()).Face(), gp_Vec(0, 0, height)).Shape()
    BRepTools.Write_s(solid, str(path))
    return str(path)


@requires_occt
def test_three_rounds_meeting_at_a_box_corner() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        edges = [_edge_index(model, box, point) for point in [(0, 0, 15), (5, 0, 0), (0, 10, 0)]]
        rounded = model.fillet(box, 2.0, edges)
        smooth = model.smooth_fillet(box, 2.0, edges)
        # OCCT's spherical corner is G1 to its rounds; every round-to-round
        # and round-to-face transition of the smooth fillet is G2.
        assert _levels(rounded) == Counter({"G0": 12, "G1": 9})
        assert _levels(smooth) == Counter({"G0": 12, "G2": 15})
        for edge in smooth.continuity()["edges"]:
            if edge["level"] == "G2":
                assert edge["max_gap"] < 1e-5 and edge["max_angle_degrees"] < 0.01
        assert rounded.volume < smooth.volume < box.volume
        assert smooth.surface_quality()["issues"] == []


@requires_occt
def test_every_edge_of_a_box() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        smooth = model.smooth_fillet(box, 2.0)
        assert _levels(model.fillet(box, 2.0)) == Counter({"G1": 48})
        assert _levels(smooth) == Counter({"G2": 96})
        assert smooth.surface_quality()["issues"] == []


@requires_occt
@pytest.mark.parametrize("sides", [3, 5])
def test_non_orthogonal_corners_of_a_prism(tmp_path, sides: int) -> None:
    # Prism corners have 60 or 108 degree wall angles, i.e. three rounds of
    # different section angles meeting at each vertex.
    with cad.Model() as model:
        part = model.import_brep(_prism(tmp_path / "prism.brep", sides))
        smooth = model.smooth_fillet(part, 1.0)
        assert set(_levels(smooth)) == {"G2"}
        assert model.fillet(part, 1.0).volume < smooth.volume < part.volume
        assert smooth.surface_quality()["issues"] == []


@requires_occt
def test_mitred_rounds_on_two_edges_of_a_corner() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        edges = [_edge_index(model, box, (0, 0, 15)), _edge_index(model, box, (5, 0, 0))]
        smooth = model.smooth_fillet(box, 2.0, edges)
        assert smooth.topology == model.fillet(box, 2.0, edges).topology
        # The two blends meet along their intersection curve (a crease, as in
        # OCCT's own miter); both join the planes with G2.
        assert _levels(smooth)["G2"] == 4
        assert smooth.surface_quality()["issues"] == []


@requires_occt
def test_tangent_chain_around_a_stadium_rim(tmp_path) -> None:
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire,
    )
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepTools import BRepTools
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Pnt, gp_Vec

    wire = BRepBuilderAPI_MakeWire()
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, -5, 0), gp_Pnt(10, -5, 0)).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(
        gp_Pnt(10, -5, 0), gp_Pnt(15, 0, 0), gp_Pnt(10, 5, 0)).Value()).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(10, 5, 0), gp_Pnt(0, 5, 0)).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(
        gp_Pnt(0, 5, 0), gp_Pnt(-5, 0, 0), gp_Pnt(0, -5, 0)).Value()).Edge())
    solid = BRepPrimAPI_MakePrism(
        BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, 8)).Shape()
    path = tmp_path / "stadium.brep"
    BRepTools.Write_s(solid, str(path))
    with cad.Model() as model:
        part = model.import_brep(str(path))
        rim = [index for index, edge in enumerate(model.edges(part))
               if abs(edge.center_of_mass[2] - 8.0) < 1e-6]
        smooth = model.smooth_fillet(part, 2.0, rim)
        levels = _levels(smooth)
        # Trim lines are G2. Where a straight round meets a toroidal one the
        # rim itself is only G1 (line to arc), and so are the rounds.
        assert levels == Counter({"G2": 8, "G1": 8, "G0": 4})
        for edge in smooth.continuity()["edges"]:
            if edge["level"] == "G1":
                assert edge["max_angle_degrees"] < 1e-3
        assert smooth.surface_quality()["issues"] == []


@requires_occt
def test_unsupported_configurations_fail_clearly(tmp_path) -> None:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt

    loft = BRepOffsetAPI_ThruSections(True, True)
    for z, half in ((0.0, 6.0), (6.0, 3.0)):
        square = BRepBuilderAPI_MakePolygon()
        for x, y in ((-half, -half), (half, -half), (half, half), (-half, half)):
            square.Add(gp_Pnt(x, y, z))
        square.Close()
        loft.AddWire(square.Wire())
    loft.Build()
    BRepTools.Write_s(loft.Shape(), str(tmp_path / "frustum.brep"))
    with cad.Model() as model:
        frustum = model.import_brep(str(tmp_path / "frustum.brep"))
        with pytest.raises(cad.NativeError, match="tapered"):
            model.smooth_fillet(frustum, 1.0)
        box = model.box(10.0, 20.0, 30.0)
        edge = _edge_index(model, box, (0, 0, 15))
        with pytest.raises(cad.NativeError, match="setback"):
            model.smooth_fillet(box, 0.0, [edge])
        with pytest.raises(cad.NativeError, match="trim lines"):
            model.smooth_fillet(box, 50.0, [edge])
        with pytest.raises(ValueError, match="G1"):
            model.smooth_fillet(box, 2.0, [edge], continuity="G0")
        with pytest.raises(cad.NativeError, match="out of range"):
            model.smooth_fillet(box, 2.0, [99])
