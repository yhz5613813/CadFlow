from __future__ import annotations

import math

import numpy as np
import pytest

import cadflow as cad
from test_surface_analysis import requires_occt


def _segments(model: cad.Model, corners) -> list[cad.Shape]:
    return [
        model.polyline([corners[index], corners[(index + 1) % len(corners)]])
        for index in range(len(corners))
    ]


@requires_occt
def test_four_sided_filling_interpolates_every_boundary_edge() -> None:
    with cad.Model() as model:
        edges = _segments(model, [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 2)])
        face = model.filling_surface(edges)
        assert face.kind == "filling_surface"
        assert face.area > 100.0  # a 10 x 10 patch with one raised corner
        for edge in edges:
            assert face.distance_to(edge) < 1e-9
        assert len(model.free_boundaries(face)) == 1


@requires_occt
def test_flat_square_filling_is_the_square() -> None:
    with cad.Model() as model:
        face = model.filling_surface(_segments(model, [(0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)]))
        assert face.area == pytest.approx(12.0, rel=1e-9)
        for sample in face.curvature_samples(4, 4):
            assert abs(sample["normal"][2]) == pytest.approx(1.0)


@requires_occt
def test_filling_accepts_curved_edges_in_any_order_and_direction() -> None:
    with cad.Model() as model:
        south = model.interpolate([(0, 0, 0), (5, 0, 2), (10, 0, 0)])
        east = model.interpolate([(10, 0, 0), (11, 5, 1), (10, 10, 0)])
        north = model.interpolate([(0, 10, 0), (5, 10, -2), (10, 10, 0)])  # runs west->east
        west = model.interpolate([(0, 0, 0), (-1, 5, 1), (0, 10, 0)])  # runs south->north
        face = model.filling_surface([north, south, west, east])
        for edge in (south, east, north, west):
            assert face.distance_to(edge) < 1e-9
        assert face.surface_quality()["issues"] == []


@requires_occt
def test_filling_accepts_extracted_edges() -> None:
    with cad.Model() as model:
        box = model.box(2.0, 3.0, 4.0)
        top = max(model.faces(box), key=lambda face: face.center_of_mass[2])
        face = model.filling_surface(model.edges(top))
        assert face.area == pytest.approx(6.0, rel=1e-9)


@requires_occt
def test_three_and_five_sided_fillings_close_on_their_boundary() -> None:
    with cad.Model() as model:
        triangle = model.filling_surface(_segments(model, [(0, 0, 0), (10, 0, 0), (5, 8, 3)]))
        assert triangle.area == pytest.approx(
            0.5 * np.linalg.norm(np.cross((10, 0, 0), (5, 8, 3))), rel=1e-6
        )
        corners = [
            (10 * math.cos(a), 10 * math.sin(a), 2 * math.sin(3 * a))
            for a in np.linspace(0.0, 2.0 * math.pi, 6)[:-1]
        ]
        edges = _segments(model, corners)
        pentagon = model.filling_surface(edges, tolerance=1e-3)
        assert max(pentagon.distance_to(edge) for edge in edges) < 1e-3
        assert pentagon.area > 200.0


@requires_occt
def test_filling_rejects_open_boundaries() -> None:
    with cad.Model() as model:
        edges = [
            model.polyline([(0, 0, 0), (1, 0, 0)]),
            model.polyline([(1, 0, 0), (1, 1, 0)]),
            model.polyline([(5, 5, 5), (6, 6, 6)]),
        ]
        with pytest.raises(cad.NativeError, match="closed loop"):
            model.filling_surface(edges)
        with pytest.raises(cad.NativeError, match="at least 3"):
            model.filling_surface(edges[:2])


@requires_occt
def test_sewing_accepts_faces_from_any_constructor(tmp_path) -> None:
    with cad.Model() as model:
        box = model.box(1.0, 1.0, 1.0)
        faces = model.faces(box)  # extracted faces are not tagged as constructed faces
        shell = model.sew(list(faces), tolerance=1e-6)
        assert shell.topology["faces"] == 6
        solid = model.shell_to_solid(shell)
        assert solid.volume == pytest.approx(1.0)
        with pytest.raises(cad.NativeError, match="faces or shells"):
            model.sew([model.polyline([(0, 0, 0), (1, 0, 0)])])
