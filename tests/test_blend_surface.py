from __future__ import annotations

import numpy as np
import pytest

import cadflow as cad
from test_surface_analysis import _split_cubic_rows, _wavy_net, requires_occt


def _edge_near(model: cad.Model, shape: cad.Shape, target) -> cad.Shape:
    target = np.asarray(target, dtype=float)
    return min(
        model.edges(shape),
        key=lambda edge: float(np.linalg.norm(np.asarray(edge.center_of_mass) - target)),
    )


def _rectangle(model: cad.Model, corners) -> cad.Shape:
    return model.face(model.polyline(corners, closed=True))


def _thirds(model: cad.Model):
    a, rest = _split_cubic_rows(_wavy_net(), 1.0 / 3.0)
    _, b = _split_cubic_rows(rest, 0.5)
    face_a = model.bezier_surface(a.tolist())
    face_b = model.bezier_surface(b.tolist())
    edge_a = _edge_near(model, face_a, a[-1].mean(axis=0))
    edge_b = _edge_near(model, face_b, b[0].mean(axis=0))
    return face_a, edge_a, face_b, edge_b


def _level(blend: cad.Shape, support: cad.Shape) -> dict:
    edges = blend.continuity_with(support, samples=32)["edges"]
    assert len(edges) == 1
    return edges[0]


@requires_occt
@pytest.mark.parametrize("level", ["G0", "G1", "G2"])
def test_blend_meets_curved_supports_at_the_requested_level(level: str) -> None:
    with cad.Model() as model:
        face_a, edge_a, face_b, edge_b = _thirds(model)
        blend = model.blend_surface(face_a, edge_a, face_b, edge_b, continuity=level)
        assert blend.kind == "blend_surface"
        for support in (face_a, face_b):
            edge = _level(blend, support)
            assert edge["max_gap"] < 1e-6
            assert edge["level"] == level
        assert blend.surface_quality()["issues"] == []


@requires_occt
def test_blend_g2_matches_support_curvature_tightly() -> None:
    with cad.Model() as model:
        face_a, edge_a, face_b, edge_b = _thirds(model)
        blend = model.blend_surface(face_a, edge_a, face_b, edge_b)
        for support in (face_a, face_b):
            edge = _level(blend, support)
            assert edge["max_angle_degrees"] < 1e-4
            assert edge["max_curvature_ratio"] < 1e-5


@requires_occt
def test_blend_continuity_can_differ_per_side() -> None:
    with cad.Model() as model:
        face_a, edge_a, face_b, edge_b = _thirds(model)
        blend = model.blend_surface(face_a, edge_a, face_b, edge_b, continuity=("G2", "G1"))
        assert _level(blend, face_a)["level"] == "G2"
        assert _level(blend, face_b)["level"] == "G1"


@requires_occt
def test_blend_couples_reversed_edges_automatically() -> None:
    a, rest = _split_cubic_rows(_wavy_net(), 1.0 / 3.0)
    _, b = _split_cubic_rows(rest, 0.5)
    with cad.Model() as model:
        face_a = model.bezier_surface(a.tolist())
        face_b = model.bezier_surface(b[:, ::-1].tolist())  # edge B runs backwards
        edge_a = _edge_near(model, face_a, a[-1].mean(axis=0))
        edge_b = _edge_near(model, face_b, b[0].mean(axis=0))
        automatic = model.blend_surface(face_a, edge_a, face_b, edge_b)
        kept = model.blend_surface(face_a, edge_a, face_b, edge_b, reverse_b=False)
        flipped = model.blend_surface(face_a, edge_a, face_b, edge_b, reverse_b=True)
        untwisted, twisted = sorted((kept, flipped), key=lambda shape: shape.area)
        assert twisted.area > 1.05 * untwisted.area
        assert automatic.area == pytest.approx(untwisted.area, rel=1e-12)
        assert _level(automatic, face_b)["level"] == "G2"


@requires_occt
def test_blend_between_coplanar_planes_is_the_plane() -> None:
    with cad.Model() as model:
        left = _rectangle(model, [(0, 0, 0), (10, 0, 0), (10, 8, 0), (0, 8, 0)])
        right = _rectangle(model, [(16, 0, 0), (26, 0, 0), (26, 8, 0), (16, 8, 0)])
        edge_a = _edge_near(model, left, (10, 4, 0))
        edge_b = _edge_near(model, right, (16, 4, 0))
        blend = model.blend_surface(left, edge_a, right, edge_b)
        assert blend.area == pytest.approx(6.0 * 8.0, rel=1e-9)
        low, high = blend.bbox[:3], blend.bbox[3:]
        assert abs(low[2]) < 1e-6 and abs(high[2]) < 1e-6  # bbox carries the 1e-7 tolerance
        assert blend.continuity_with(left)["edges"][0]["level"] == "G2"


@requires_occt
def test_blend_turns_a_corner_between_perpendicular_planes() -> None:
    with cad.Model() as model:
        floor = _rectangle(model, [(-10, 0, 0), (0, 0, 0), (0, 10, 0), (-10, 10, 0)])
        wall = _rectangle(model, [(5, 0, 5), (5, 10, 5), (5, 10, 15), (5, 0, 15)])
        blend = model.blend_surface(
            floor, _edge_near(model, floor, (0, 5, 0)),
            wall, _edge_near(model, wall, (5, 5, 5)),
        )
        for support in (floor, wall):
            edge = _level(blend, support)
            assert edge["level"] == "G2"
        x0, y0, z0, x1, y1, z1 = blend.bbox
        assert x0 > -1e-6 and x1 < 5.0 + 1e-6
        assert z0 > -1e-6 and z1 < 5.0 + 1e-6
        # A curvature-continuous corner starts and ends flat, unlike a round.
        samples = blend.curvature_samples(9, 3)
        boundary = [s for s in samples if s["u"] in (0.0, 1.0) and not s["singular"]]
        assert max(abs(s["principal_curvature_min"]) for s in boundary) < 1e-6


@requires_occt
def test_blend_flares_between_coaxial_cylinder_rims() -> None:
    with cad.Model() as model:
        def lateral(shape):
            return next(
                face for face in model.faces(shape)
                if face.surface_metrics()["surface_geometry"] == "cylinder"
            )

        narrow = lateral(model.cylinder(4.0, 10.0))
        wide = lateral(model.translate(model.cylinder(8.0, 10.0), 0.0, 0.0, 14.0))
        # A circle's centroid lies on the axis, at the rim's height.
        top_rim = _edge_near(model, narrow, (0, 0, 10))
        bottom_rim = _edge_near(model, wide, (0, 0, 14))
        blend = model.blend_surface(narrow, top_rim, wide, bottom_rim)
        for support in (narrow, wide):
            edge = _level(blend, support)
            assert edge["level"] == "G2"
            # The bridge leaves each cylinder along its straight rulings.
            assert abs(edge["curvature_a"]) < 1e-6 and abs(edge["curvature_b"]) < 1e-6
        # Sample the surface itself: bbox is the looser control-pole hull.
        points = np.array([sample["point"] for sample in blend.curvature_samples(9, 33)])
        radii = np.hypot(points[:, 0], points[:, 1])
        assert points[:, 2].min() == pytest.approx(10.0, abs=1e-6)
        assert points[:, 2].max() == pytest.approx(14.0, abs=1e-6)
        assert radii.min() == pytest.approx(4.0, abs=1e-5)
        assert radii.max() == pytest.approx(8.0, abs=1e-5)


@requires_occt
def test_blend_rejects_invalid_requests() -> None:
    with cad.Model() as model:
        face_a, edge_a, face_b, edge_b = _thirds(model)
        with pytest.raises(cad.NativeError, match="boundary edge of its face"):
            model.blend_surface(face_a, edge_b, face_b, edge_b)
        with pytest.raises(ValueError, match="G0"):
            model.blend_surface(face_a, edge_a, face_b, edge_b, continuity="G3")
        with pytest.raises(cad.NativeError, match="tension"):
            model.blend_surface(face_a, edge_a, face_b, edge_b, tension=-1.0)
        with pytest.raises(cad.NativeError, match="tolerance"):
            model.blend_surface(face_a, edge_a, face_b, edge_b, tolerance=-1.0)
        with pytest.raises(cad.NativeError, match="one BREP face"):
            model.blend_surface(edge_a, edge_a, face_b, edge_b)
        other = _rectangle(model, [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        shared = _edge_near(model, other, (1, 0.5, 0))
        neighbour = _rectangle(model, [(1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0)])
        touching = _edge_near(model, neighbour, (1, 0.5, 0))
        with pytest.raises(cad.NativeError, match="touch"):
            model.blend_surface(other, shared, neighbour, touching)
