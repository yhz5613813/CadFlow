from __future__ import annotations

import json
import math
import struct

import numpy as np
import pytest

import cadflow as cad
from cadflow import surface_analysis as sa


def _occt() -> bool:
    with cad.NativeSession() as session:
        return "analytic" not in session.version


requires_occt = pytest.mark.skipif(not _occt(), reason="requires OCCT native backend")


def _wavy_net() -> np.ndarray:
    net = np.zeros((4, 4, 3))
    for i in range(4):
        for j in range(4):
            net[i, j] = (
                10.0 * i, 10.0 * j,
                3.0 * math.sin(0.9 * i) * math.cos(0.7 * j) + 0.4 * i * j,
            )
    return net


def _split_cubic_rows(net: np.ndarray, t: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """De Casteljau split of a cubic-in-u Bezier net: the halves join C-infinity."""
    left, right = [], []
    for column in range(net.shape[1]):
        current = [net[row, column] for row in range(net.shape[0])]
        first, last = [current[0]], [current[-1]]
        while len(current) > 1:
            current = [(1 - t) * a + t * b for a, b in zip(current[:-1], current[1:])]
            first.append(current[0])
            last.append(current[-1])
        left.append(first)
        right.append(last[::-1])
    return np.array(left).transpose(1, 0, 2), np.array(right).transpose(1, 0, 2)


def _pair_level(model: cad.Model, a: np.ndarray, b: np.ndarray) -> tuple[str, dict]:
    face_a = model.bezier_surface(a.tolist())
    face_b = model.bezier_surface(b.tolist())
    report = face_a.continuity_with(face_b)
    assert len(report["edges"]) == 1
    return report["edges"][0]["level"], report["edges"][0]


@requires_occt
def test_box_edges_are_position_continuous_at_right_angles() -> None:
    with cad.Model() as model:
        box = model.box(10.0, 20.0, 30.0)
        report = box.continuity()
        summary = report["summary"]
        assert summary["checked"] == 12
        assert summary["G0"] == 12
        assert summary["free"] == summary["seam"] == summary["non_manifold"] == 0
        assert summary["worst_angle_degrees"] == pytest.approx(90.0, abs=1e-9)
        assert summary["worst_gap"] == pytest.approx(0.0, abs=1e-12)
        face_count = len(model.faces(box))
        for edge in report["edges"]:
            assert not edge["orientation_flipped"]
            assert all(0 <= index < face_count for index in edge["faces"])
        # Reported edge indices address the same edges as Model.fillet.
        sharp = [edge["edge_index"] for edge in report["edges"] if edge["level"] == "G0"]
        rounded = model.fillet(box, 1.0, sharp[:2])
        assert rounded.continuity()["summary"]["G1"] == 4


@requires_occt
def test_round_fillet_is_tangent_but_not_curvature_continuous() -> None:
    radius = 3.0
    with cad.Model() as model:
        part = model.fillet(model.box(10.0, 20.0, 30.0), radius, [0])
        report = part.continuity()
        tangent = [edge for edge in report["edges"] if edge["level"] == "G1"]
        assert len(tangent) == 2
        for edge in tangent:
            assert edge["max_angle_degrees"] == pytest.approx(0.0, abs=1e-6)
            assert edge["max_curvature_ratio"] == pytest.approx(1.0)
            curvatures = sorted((abs(edge["curvature_a"]), abs(edge["curvature_b"])))
            assert curvatures[0] == pytest.approx(0.0, abs=1e-12)
            assert curvatures[1] == pytest.approx(1.0 / radius)
        assert report["summary"]["G0"] == len(report["edges"]) - 2


@requires_occt
def test_bezier_split_reports_each_continuity_level() -> None:
    a, b = _split_cubic_rows(_wavy_net())
    with cad.Model() as model:
        level, edge = _pair_level(model, a, b)
        assert level == "G2"
        assert edge["max_gap"] < 1e-12
        assert edge["max_curvature_ratio"] < 1e-6

        g1 = b.copy()
        g1[2] += (0.0, 0.0, 1.5)  # third row: tangent plane kept, curvature broken
        assert _pair_level(model, a, g1)[0] == "G1"

        g0 = b.copy()
        g0[1] += (0.0, 0.0, 2.0)  # tangent row: tangent plane broken
        level, edge = _pair_level(model, a, g0)
        assert level == "G0"
        assert edge["max_angle_degrees"] > 5.0

        gap = b.copy()
        gap[0] += (0.0, 0.0, 0.01)
        gap[1] += (0.0, 0.0, 0.01)
        level, edge = _pair_level(model, a, gap)
        assert level == "gap"
        # Distance to the other boundary curve, slightly below the vertical
        # offset because the boundary is inclined.
        assert edge["max_gap"] == pytest.approx(0.01, rel=1e-4)


@requires_occt
def test_unsewn_face_pair_ignores_arbitrary_orientation() -> None:
    a, b = _split_cubic_rows(_wavy_net())
    with cad.Model() as model:
        level, edge = _pair_level(model, a, b[:, ::-1])
        assert level == "G2"
        assert edge["orientation_flipped"] is True


@requires_occt
def test_sewn_shell_reports_shared_edge_level() -> None:
    a, b = _split_cubic_rows(_wavy_net())
    g1 = b.copy()
    g1[2] += (0.0, 0.0, 1.5)
    with cad.Model() as model:
        for other, expected in ((b, "G2"), (g1, "G1")):
            shell = model.sew(
                [model.bezier_surface(a.tolist()), model.bezier_surface(other.tolist())],
                tolerance=1e-4,
            )
            report = shell.continuity()
            assert [edge["level"] for edge in report["edges"]] == [expected]
            assert report["edges"][0]["shared"] is True
            assert report["summary"]["free"] == 6


@requires_occt
def test_cylinder_seam_is_skipped_and_caps_are_sharp() -> None:
    with cad.Model() as model:
        summary = model.cylinder(5.0, 10.0).continuity()["summary"]
        assert summary["seam"] == 1
        assert summary["G0"] == 2
        assert summary["checked"] == 2


@requires_occt
def test_sphere_curvature_samples_are_exact_and_poles_singular() -> None:
    radius = 4.0
    with cad.Model() as model:
        face = model.faces(model.sphere(radius))[0]
        samples = face.curvature_samples(9, 7)
        assert len(samples) == 63
        regular = [sample for sample in samples if not sample["singular"]]
        singular = [sample for sample in samples if sample["singular"]]
        assert len(singular) == 2 * 9  # both pole rows of the v range
        for sample in regular:
            assert sample["principal_curvature_min"] == pytest.approx(-1.0 / radius)
            assert sample["principal_curvature_max"] == pytest.approx(-1.0 / radius)
            assert sample["gaussian_curvature"] == pytest.approx(1.0 / radius**2)
            point = np.array(sample["point"])
            assert np.dot(sample["normal"], point / np.linalg.norm(point)) == pytest.approx(1.0)
        assert all(math.isnan(sample["mean_curvature"]) for sample in singular)


@requires_occt
def test_cylinder_principal_directions_follow_the_axis() -> None:
    radius = 2.5
    with cad.Model() as model:
        lateral = max(
            model.faces(model.cylinder(radius, 8.0)),
            key=lambda face: face.surface_metrics()["surface_geometry"] == "cylinder",
        )
        for sample in lateral.curvature_samples(5, 5):
            assert sample["principal_curvature_min"] == pytest.approx(-1.0 / radius)
            assert sample["principal_curvature_max"] == pytest.approx(0.0, abs=1e-12)
            assert sample["gaussian_curvature"] == pytest.approx(0.0, abs=1e-12)
            # Strongest bending is around the axis; the flat direction is along it.
            assert abs(sample["direction_min"][2]) == pytest.approx(0.0, abs=1e-9)
            assert abs(sample["direction_max"][2]) == pytest.approx(1.0)


@requires_occt
def test_saddle_has_negative_gaussian_curvature() -> None:
    grid = [[(x, y, 0.02 * (x * x - y * y)) for y in range(-5, 6)] for x in range(-5, 6)]
    with cad.Model() as model:
        saddle = model.fit_surface(grid)
        center = saddle.curvature_samples(3, 3)[4]
        assert center["gaussian_curvature"] < 0.0
        assert center["principal_curvature_min"] < 0.0 < center["principal_curvature_max"]
        assert abs(center["mean_curvature"]) < 1e-6


@requires_occt
def test_surface_quality_flags_wavy_surfaces_with_hints() -> None:
    smooth = [[(i, j, 0.05 * (i - 5) ** 2 - 0.03 * (j - 5) ** 2) for j in range(11)] for i in range(11)]
    wavy = [[(i, j, 0.4 * math.sin(2.6 * i)) for j in range(11)] for i in range(11)]
    with cad.Model() as model:
        clean = model.fit_surface(smooth).surface_quality()
        assert clean["faces"][0]["issues"] == []
        assert clean["issues"] == []
        assert clean["faces"][0]["surface_type"] == "bspline"

        report = model.fit_surface(wavy, tolerance=1e-6).surface_quality()
        face = report["faces"][0]
        codes = {issue["code"] for issue in face["issues"]}
        assert {"surface.control_net_undulation", "surface.curvature_oscillation"} <= codes
        assert face["curvature"]["inflections_u"] >= 3
        assert face["curvature"]["inflections_v"] == 0
        assert all(issue["hint"] for issue in face["issues"])
        # Warnings propagate to the shape-level list with the face index.
        assert any(issue["message"].startswith("face 0:") for issue in report["issues"])
        json.dumps(report)  # JSON-safe for agent feedback


@requires_occt
def test_surface_quality_detects_hidden_internal_crease(tmp_path) -> None:
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepTools import BRepTools
    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt

    # Cubic in u with a triple interior knot at u = 0.5: C0 inside one face.
    poles = TColgp_Array2OfPnt(1, 7, 1, 4)
    for i in range(1, 8):
        for j in range(1, 5):
            poles.SetValue(i, j, gp_Pnt(float(i), float(j), 0.3 * abs(i - 4)))
    u_knots = TColStd_Array1OfReal(1, 3)
    for index, value in enumerate((0.0, 0.5, 1.0), start=1):
        u_knots.SetValue(index, value)
    u_mults = TColStd_Array1OfInteger(1, 3)
    for index, value in enumerate((4, 3, 4), start=1):
        u_mults.SetValue(index, value)
    v_knots = TColStd_Array1OfReal(1, 2)
    v_knots.SetValue(1, 0.0)
    v_knots.SetValue(2, 1.0)
    v_mults = TColStd_Array1OfInteger(1, 2)
    v_mults.SetValue(1, 4)
    v_mults.SetValue(2, 4)
    surface = Geom_BSplineSurface(poles, u_knots, v_knots, u_mults, v_mults, 3, 3)
    path = tmp_path / "crease.brep"
    BRepTools.Write_s(BRepBuilderAPI_MakeFace(surface, 1e-7).Face(), str(path))
    del BRep_Builder

    with cad.Model() as model:
        face = model.import_brep(str(path))
        report = face.surface_quality()["faces"][0]
        assert report["definition"]["internal_u_continuity"] == 0
        assert report["definition"]["internal_v_continuity"] is None
        assert "surface.internal_crease" in {issue["code"] for issue in report["issues"]}


@requires_occt
def test_self_intersection_check_reports_interfering_solids(tmp_path) -> None:
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Compound
    from OCP.gp import gp_Pnt

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(5.0, 5.0, 5.0), 10.0, 10.0, 10.0).Shape())
    path = tmp_path / "overlap.brep"
    BRepTools.Write_s(compound, str(path))

    with cad.Model() as model:
        overlapping = model.import_brep(str(path))
        report = overlapping.surface_quality(samples=4, check_self_intersection=True)
        assert report["self_intersection"]["interfering_pairs"] > 0
        assert "shape.self_intersection" in {issue["code"] for issue in report["issues"]}
        clean = model.box(1.0, 1.0, 1.0).surface_quality(samples=4, check_self_intersection=True)
        assert clean["self_intersection"] == {"checked": True, "interfering_pairs": 0}
        assert model.box(1.0, 1.0, 1.0).surface_quality(samples=4)["self_intersection"] is None


@requires_occt
def test_curvature_mesh_carries_exact_vertex_curvature(tmp_path) -> None:
    radius = 3.0
    with cad.Model() as model:
        part = model.fillet(model.box(10.0, 20.0, 30.0), radius, [0])
        mesh = part.curvature_mesh(0.05)
        assert mesh.positions.shape == (mesh.vertex_count, 3)
        assert mesh.triangles.max() < mesh.vertex_count
        assert set(np.unique(mesh.face_indices)) == set(range(len(model.faces(part))))
        np.testing.assert_allclose(np.linalg.norm(mesh.normals, axis=1), 1.0, atol=1e-5)
        summary = mesh.summary()
        assert summary["minimum_radius"] == pytest.approx(radius, rel=1e-5)
        assert summary["k_min"]["min"] == pytest.approx(-1.0 / radius, rel=1e-5)

        stripes = sa.zebra(mesh, stripes=12)
        bands = sa.isophotes(mesh, bands=6)
        assert set(np.unique(stripes)) <= {0.0, 1.0}
        assert set(np.unique(bands)) <= {0.0, 1.0}

        colors = sa.curvature_colors(mesh.field("mean"))
        assert colors.shape == (mesh.vertex_count, 3)
        # Flat faces stay white even though they dominate the vertex count.
        flat = mesh.field("mean") == 0.0
        assert flat.sum() > 0.5 * mesh.vertex_count
        np.testing.assert_allclose(colors[flat], 1.0)
        assert (colors[~flat][:, 0] < 0.5).all()  # fillet is blue (negative)

        glb = sa.to_glb(mesh, colors)
        magic, version, length = struct.unpack_from("<III", glb)
        assert (magic, version, length) == (0x46546C67, 2, len(glb))
        document = json.loads(glb[20:20 + struct.unpack_from("<I", glb, 12)[0]])
        assert document["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"] == 2

        for mode in ("mean", "gaussian", "zebra", "isophote", "shaded"):
            path = tmp_path / f"{mode}.png"
            description = sa.render_png(mesh, str(path), mode=mode, size=96)
            assert path.stat().st_size > 0
            assert description["mode"] == mode


def test_curvature_mesh_buffer_parser_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        sa.parse_curvature_mesh_buffer(b"CFCA")
    with pytest.raises(ValueError):
        sa.parse_curvature_mesh_buffer(struct.pack("<4sIII", b"XXXX", 1, 1, 1))
    with pytest.raises(ValueError):
        sa.parse_curvature_mesh_buffer(struct.pack("<4sIII", b"CFCA", 1, 3, 1))


@requires_occt
def test_surface_analysis_rejects_invalid_requests() -> None:
    with cad.Model() as model:
        box = model.box(1.0, 1.0, 1.0)
        face = model.faces(box)[0]
        with pytest.raises(cad.NativeError, match="samples"):
            box.continuity(samples=1)
        with pytest.raises(cad.NativeError, match="tolerance"):
            box.continuity(position_tolerance=0.0)
        with pytest.raises(cad.NativeError, match="one BREP face"):
            box.continuity_with(face)
        with pytest.raises(cad.NativeError, match="one BREP face"):
            box.curvature_samples()
        with pytest.raises(cad.NativeError):
            face.curvature_samples(1, 5)
        with pytest.raises(cad.NativeError, match="deflection"):
            box.curvature_mesh(0.0)
        with pytest.raises(cad.NativeError, match="samples"):
            box.surface_quality(samples=2)
        with cad.Model() as other:
            with pytest.raises(ValueError, match="same Model"):
                face.continuity_with(other.faces(other.box(1.0, 1.0, 1.0))[0])


@requires_occt
def test_capabilities_advertise_surface_analysis() -> None:
    with cad.Model() as model:
        capabilities = model.capabilities()
        assert "surface_analysis" in capabilities["frontend"]
        assert {"continuity", "surface_quality", "curvature_mesh"} <= set(
            capabilities["native_operations"]
        )
    assert "continuity_report" in cad.capabilities()["native"]
