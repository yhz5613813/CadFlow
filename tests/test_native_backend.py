from __future__ import annotations

import math
from pathlib import Path

import pytest

import cadflow


def _occt_backend_available() -> bool:
    with cadflow.NativeSession() as session:
        return "analytic" not in session.version


requires_occt = pytest.mark.skipif(
    not _occt_backend_available(),
    reason="requires the OCCT native backend",
)


@requires_occt
def test_native_primitives_and_properties() -> None:
    with cadflow.Model() as model:
        box = model.box(2, 3, 4)
        cylinder = model.cylinder(1, 4)
        tool = model.translate(cylinder, 1, 1, 0)
        result = model.cut(box, tool)

        assert box.kind == "box"
        assert box.volume == pytest.approx(24.0)
        assert box.area == pytest.approx(52.0)
        assert box.length == pytest.approx(36.0)
        assert box.center_of_mass == pytest.approx((1, 1.5, 2))
        assert box.bbox == pytest.approx((0, 0, 0, 2, 3, 4), abs=1e-6)
        assert result.kind == "cut"
        assert result.volume == pytest.approx(24.0 - 4 * math.pi)
        assert box.topology == {"vertices": 8, "edges": 12, "faces": 6, "solids": 1}


@requires_occt
def test_extended_occt_primitives_boolean_and_rotation() -> None:
    with cadflow.Model() as model:
        sphere = model.sphere(2)
        cone = model.cone(2, 1, 3)
        box = model.box(3, 3, 3)
        shifted = model.translate(model.box(3, 3, 3), 1, 1, 1)
        common = model.intersect(box, shifted)
        rotated = model.rotate(box, 90, axis=(0, 0, 1))
        separated = model.translate(model.box(1, 1, 1), 5, 0, 0)
        unit = model.box(1, 1, 1)

        assert sphere.volume == pytest.approx(32 * math.pi / 3)
        assert sphere.area == pytest.approx(16 * math.pi)
        assert cone.volume == pytest.approx(7 * math.pi)
        assert common.volume == pytest.approx(8)
        assert rotated.volume == pytest.approx(27)
        assert model.distance(unit, separated) == pytest.approx(4)
        assert unit.distance_to(separated) == pytest.approx(4)


@requires_occt
def test_native_profile_extrude_and_revolve_pipeline() -> None:
    with cadflow.Model() as model:
        wire = model.polyline(
            ((0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0)),
            closed=True,
        )
        face = model.face(wire)
        prism = model.extrude(face, 0, 0, 4)
        circle = model.circle_profile(2)
        cylinder = model.extrude(circle, 0, 0, 5)
        annulus_section = model.polyline(
            ((1, 0, 0), (2, 0, 0), (2, 0, 1), (1, 0, 1)),
            closed=True,
        )
        revolved = model.revolve(annulus_section)
        lower = model.circle_profile(2, center=(0, 0, 0))
        upper = model.circle_profile(1, center=(0, 0, 3))
        lofted = model.loft((lower, upper))
        sweep_profile = model.circle_profile(1, normal=(1, 0, 0))
        sweep_path = model.polyline(((0, 0, 0), (5, 0, 0)))
        swept = model.sweep(sweep_profile, sweep_path)
        arc = model.arc(
            (1, 0, 0),
            (math.sqrt(0.5), math.sqrt(0.5), 0),
            (0, 1, 0),
        )
        spline = model.interpolate(((0, 0, 0), (1, 1, 0), (2, 0, 0)))
        helix = model.helix(pitch=2, height=4, radius=1)

        assert wire.kind == "wire"
        assert wire.length == pytest.approx(10)
        assert face.kind == "face"
        assert face.area == pytest.approx(6)
        assert prism.kind == "extrude"
        assert prism.volume == pytest.approx(24)
        assert prism.area == pytest.approx(52)
        assert prism.topology == {
            "vertices": 8,
            "edges": 12,
            "faces": 6,
            "solids": 1,
        }
        assert cylinder.volume == pytest.approx(20 * math.pi)
        assert circle.length == pytest.approx(4 * math.pi)
        assert revolved.kind == "revolve"
        assert revolved.volume == pytest.approx(3 * math.pi)
        assert lofted.kind == "loft"
        assert lofted.volume == pytest.approx(7 * math.pi)
        assert lofted.topology["solids"] == 1
        assert swept.kind == "sweep"
        assert swept.volume == pytest.approx(5 * math.pi)
        assert swept.topology["solids"] == 1
        assert arc.length == pytest.approx(math.pi / 2)
        assert 2 < spline.length < 4
        assert helix.length == pytest.approx(4 * math.sqrt(1 + math.pi**2), rel=1e-4)


@requires_occt
def test_native_mirror_scale_and_profile_graph() -> None:
    with cadflow.Model() as model:
        box = model.box(2, 3, 4)
        mirrored = model.mirror(box, (1, 0, 0))
        scaled = model.scale(box, 2)

        assert mirrored.volume == pytest.approx(24)
        assert mirrored.bbox == pytest.approx((-2, 0, 0, 0, 3, 4), abs=1e-6)
        assert scaled.volume == pytest.approx(192)
        assert scaled.area == pytest.approx(208)
        assert scaled.bbox == pytest.approx((0, 0, 0, 4, 6, 8), abs=1e-6)

    graph = cadflow.Graph()
    wire = graph.add(
        "polyline",
        ((0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0)),
        True,
    )
    face = graph.add("face", wire)
    solid = graph.add("extrude", face, 0, 0, 4)
    graph.add("volume", solid)
    graph.add("bbox", solid)
    graph.add("length", wire)
    graph.add("center", solid)
    separated = graph.add("translate", solid, 5, 0, 0)
    graph.add("distance", solid, separated)

    output = graph.execute()
    assert float(output[3]) == pytest.approx(24)
    assert tuple(map(float, output[4].split())) == pytest.approx(
        (0, 0, 0, 2, 3, 4), abs=1e-6
    )
    assert float(output[5]) == pytest.approx(10)
    assert tuple(map(float, output[6].split())) == pytest.approx((1, 1.5, 2))
    assert float(output[8]) == pytest.approx(3)

    loft_graph = cadflow.Graph()
    lower = loft_graph.add("circle_profile", 2, (0, 0, 0), (0, 0, 1))
    upper = loft_graph.add("circle_profile", 1, (0, 0, 3), (0, 0, 1))
    lofted = loft_graph.add("loft", (lower, upper))
    loft_graph.add("volume", lofted)
    assert float(loft_graph.execute()[3]) == pytest.approx(7 * math.pi)

    sweep_graph = cadflow.Graph()
    profile = sweep_graph.add("circle_profile", 1, (0, 0, 0), (1, 0, 0))
    path = sweep_graph.add("polyline", ((0, 0, 0), (5, 0, 0)))
    swept = sweep_graph.add("sweep", profile, path)
    sweep_graph.add("volume", swept)
    assert float(sweep_graph.execute()[3]) == pytest.approx(5 * math.pi)

    curve_graph = cadflow.Graph()
    arc = curve_graph.add(
        "arc",
        ((1, 0, 0), (math.sqrt(0.5), math.sqrt(0.5), 0), (0, 1, 0)),
    )
    curve_graph.add("length", arc)
    assert float(curve_graph.execute()[1]) == pytest.approx(math.pi / 2)

    helix_graph = cadflow.Graph()
    helix = helix_graph.add("helix", 2, 4, 1)
    helix_graph.add("length", helix)
    assert float(helix_graph.execute()[1]) == pytest.approx(
        4 * math.sqrt(1 + math.pi**2), rel=1e-4
    )


@requires_occt
def test_native_surface_construction_and_graph() -> None:
    flat_grid = (
        ((0, 0, 0), (0, 3, 0)),
        ((2, 0, 0), (2, 3, 0)),
    )
    fitted_grid = tuple(
        tuple((float(row), float(column), 0.1 * row * column) for column in range(4))
        for row in range(4)
    )

    with cadflow.Model() as model:
        bezier = model.bezier_surface(flat_grid)
        weighted = model.bezier_surface(flat_grid, weights=((1, 1), (1, 2)))
        fitted = model.fit_surface(fitted_grid, degree_min=2, degree_max=3)

        assert bezier.kind == "surface"
        assert bezier.area == pytest.approx(6)
        assert bezier.bbox == pytest.approx((0, 0, 0, 2, 3, 0), abs=1e-6)
        assert bezier.topology == {
            "vertices": 4,
            "edges": 4,
            "faces": 1,
            "solids": 0,
        }
        assert bezier.mesh()["triangles"]
        assert weighted.area == pytest.approx(6)
        assert fitted.area > 9
        assert fitted.bbox == pytest.approx((0, 0, 0, 3, 3, 0.9), abs=1e-6)

        with pytest.raises(cadflow.NativeError, match="rectangular"):
            model.bezier_surface((((0, 0, 0),), ((1, 0, 0), (1, 1, 0))))

    graph = cadflow.Graph()
    surface = graph.add("bezier_surface", flat_grid)
    graph.add("area", surface)
    assert float(graph.execute()[1]) == pytest.approx(6)


@requires_occt
def test_native_edge_features_and_indexed_selections() -> None:
    with cadflow.Model() as model:
        box = model.box(10, 8, 6)
        filleted_all = model.fillet(box, 0.5)
        filleted_edge = model.fillet(box, 0.5, [0])
        chamfered_all = model.chamfer(box, 0.5)
        chamfered_edge = model.chamfer(box, 0.5, edges=[0])
        shelled = model.shell(box, 0.5, faces=[5])

        assert filleted_all.kind == "fillet"
        assert filleted_edge.kind == "fillet"
        assert chamfered_all.kind == "chamfer"
        assert chamfered_edge.kind == "chamfer"
        assert shelled.kind == "shell"
        assert 0 < filleted_all.volume < filleted_edge.volume < box.volume
        assert 0 < chamfered_all.volume < chamfered_edge.volume < box.volume
        assert 0 < shelled.volume < box.volume
        assert filleted_edge.topology["faces"] == 7
        assert chamfered_edge.topology["faces"] == 7
        assert shelled.topology["solids"] == 1


@requires_occt
def test_native_edge_feature_validation_and_graph() -> None:
    with cadflow.Model() as model:
        box = model.box(10, 8, 6)
        with pytest.raises(cadflow.NativeError, match="unique"):
            model.fillet(box, 0.5, [0, 0])
        with pytest.raises(cadflow.NativeError, match="non-negative"):
            model.chamfer(box, 0.5, [-1])
        with pytest.raises(cadflow.NativeError, match="out of range"):
            model.fillet(box, 0.5, [12])
        with pytest.raises(cadflow.NativeError, match="at least one"):
            model.shell(box, 0.5)

    graph = cadflow.Graph()
    box = graph.add("box", 10, 8, 6)
    filleted = graph.add("fillet", box, 0.5, [0])
    graph.add("kind", filleted)
    chamfered = graph.add("chamfer", box, 0.5, [0])
    graph.add("kind", chamfered)
    shelled = graph.add("shell", box, 0.5, [5])
    graph.add("kind", shelled)

    output = graph.execute()
    assert output[2] == "fillet"
    assert output[4] == "chamfer"
    assert output[6] == "shell"


def test_edge_features_fail_explicitly_in_analytic_build() -> None:
    with cadflow.NativeSession() as session:
        if "analytic" not in session.version:
            pytest.skip("requires the analytic fallback build")
        box = session.box(2, 3, 4)
        with pytest.raises(cadflow.NativeError, match="OCCT backend"):
            session.fillet(box, 0.1)
        with pytest.raises(cadflow.NativeError, match="OCCT backend"):
            session.chamfer(box, 0.1)
        with pytest.raises(cadflow.NativeError, match="OCCT backend"):
            session.shell(box, 0.1, [0])


def test_handles_are_session_scoped() -> None:
    left = cadflow.Model()
    right = cadflow.Model()
    try:
        shape = left.box(1, 1, 1)
        with pytest.raises(ValueError, match="belong"):
            right.translate(shape, 1, 2, 3)
    finally:
        left.close()
        right.close()


def test_closed_session_rejects_new_native_work() -> None:
    session = cadflow.NativeSession()
    session.close()
    with pytest.raises(cadflow.NativeError, match="closed"):
        session.box(1, 1, 1)


def test_graph_executes_in_one_native_call() -> None:
    graph = cadflow.Graph()
    box = graph.add("box", 10, 20, 30)
    tool = graph.add("cylinder", 2, 30)
    tool = graph.add("translate", tool, 2, 2, 0)
    cut = graph.add("cut", box, tool)
    volume = graph.add("volume", cut)
    bbox = graph.add("bbox", cut)

    output = graph.execute()
    assert int(output[0]) > 0
    assert int(output[1]) > 0
    assert int(output[2]) > 0
    assert int(output[3]) > 0
    assert float(output[4]) == pytest.approx(6000 - 120 * math.pi)
    assert tuple(map(float, output[5].split())) == pytest.approx((0, 0, 0, 10, 20, 30), abs=1e-6)


def test_native_errors_are_structured() -> None:
    with cadflow.NativeSession() as session:
        with pytest.raises(cadflow.NativeError, match="positive"):
            session.box(0, 1, 1)


@requires_occt
def test_occt_mesh_and_step_export(tmp_path: Path) -> None:
    pytest.importorskip("OCP")
    with cadflow.Model() as model:
        shape = model.box(1, 2, 3)
        stl_target = tmp_path / "box.stl"
        shape.export_stl(str(stl_target))
        assert stl_target.stat().st_size > 84

        mesh = shape.mesh(0.05)
        assert len(mesh["vertices"]) > 0
        assert len(mesh["triangles"]) > 0
        target = tmp_path / "box.step"
        try:
            shape.export_step(str(target))
        except cadflow.NativeError as error:
            pytest.skip(f"native STEP writer is disabled: {error}")
        assert target.stat().st_size > 0
        imported = model.import_step(str(target))
        assert imported.kind == "imported"
        assert imported.volume == pytest.approx(6)
        assert imported.topology["solids"] == 1
