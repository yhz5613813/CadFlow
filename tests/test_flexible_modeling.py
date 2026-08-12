import json
import struct
from collections import Counter

import numpy as np
import pytest

from cadflow.flexible import (
    FlexibleMaterial,
    FlexibleModel,
    FlexiblePanel,
    RingSection,
    sectioned_panel,
)


def _flat_panel(*, thickness=0.2, rows=5, columns=6):
    return FlexiblePanel(
        name="flat",
        control_points=[
            [[0.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
            [[3.0, 0.0, 0.0], [3.0, 2.0, 0.0]],
        ],
        sample_rows=rows,
        sample_columns=columns,
        material=FlexibleMaterial(thickness=thickness),
    )


def _section(z, radius_u, radius_v, phase=0.0):
    return RingSection(
        center=(0.0, 0.0, z),
        axis_u=(1.0, 0.0, 0.0),
        axis_v=(0.0, 1.0, 0.0),
        radius_u=radius_u,
        radius_v=radius_v,
        wrinkle_amplitude=0.025,
        wrinkle_count=5,
        wrinkle_phase=phase,
    )


def _orientation_errors(triangles):
    directed = Counter()
    for left, right, third in triangles:
        a, b, c = int(left), int(right), int(third)
        directed[(a, b)] += 1
        directed[(b, c)] += 1
        directed[(c, a)] += 1
    undirected = {tuple(sorted(edge)) for edge in directed}
    return [
        edge
        for edge in undirected
        if directed[edge] != 1 or directed[(edge[1], edge[0])] != 1
    ]


def test_panel_validation_rejects_bad_control_grid():
    with pytest.raises(ValueError, match="shape"):
        FlexiblePanel("bad", [[0.0, 1.0], [2.0, 3.0]])
    with pytest.raises(ValueError, match="sample_rows"):
        _flat_panel(rows=1)
    with pytest.raises(ValueError, match="thickness"):
        FlexibleMaterial(thickness=-0.1)


def test_open_thick_panel_has_expected_counts_and_is_watertight():
    mesh = _flat_panel(thickness=0.2, rows=5, columns=6).build()
    expected_surface_triangles = 2 * (5 - 1) * (6 - 1)
    expected_boundary_edges = 2 * (5 - 1) + 2 * (6 - 1)
    assert mesh.vertex_count == 2 * 5 * 6
    assert mesh.triangle_count == 2 * expected_surface_triangles + 2 * expected_boundary_edges
    assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0, atol=1e-8)
    combined = FlexibleModel("flat-model")
    combined.add_panel(_flat_panel(thickness=0.2, rows=5, columns=6))
    combined_mesh = combined.build()
    assert combined_mesh.is_watertight
    assert not _orientation_errors(combined_mesh.triangles)


def test_zero_thickness_panel_is_a_single_surface():
    mesh = _flat_panel(thickness=0.0, rows=5, columns=6).build()
    assert mesh.vertex_count == 5 * 6
    assert mesh.triangle_count == 2 * (5 - 1) * (6 - 1)
    lower, upper = mesh.bounds
    assert lower == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert upper == pytest.approx((3.0, 2.0, 0.0), abs=1e-12)


def test_periodic_sectioned_panel_has_no_duplicate_seam_column():
    panel = sectioned_panel(
        "torso",
        [_section(0.0, 2.0, 1.0), _section(4.0, 2.4, 1.2, 0.3)],
        control_columns=12,
        sample_rows=9,
        sample_columns=24,
        material=FlexibleMaterial(thickness=0.15),
    )
    mesh = panel.build()
    expected_surface_triangles = 2 * (9 - 1) * 24
    expected_boundary_edges = 2 * 24
    assert mesh.vertex_count == 2 * 9 * 24
    assert mesh.triangle_count == 2 * expected_surface_triangles + 2 * expected_boundary_edges
    assert np.max(mesh.triangles) < mesh.vertex_count
    model = FlexibleModel("torso")
    model.add_panel(panel)
    combined_mesh = model.build()
    assert combined_mesh.is_watertight
    assert not _orientation_errors(combined_mesh.triangles)


def test_wrinkles_are_static_geometry_parameters():
    smooth = RingSection(
        center=(0.0, 0.0, 0.0),
        axis_u=(1.0, 0.0, 0.0),
        axis_v=(0.0, 1.0, 0.0),
        radius_u=2.0,
        radius_v=1.0,
    ).points(32)
    wrinkled = _section(0.0, 2.0, 1.0, phase=0.2).points(32)
    assert not np.allclose(smooth, wrinkled)
    assert np.max(np.linalg.norm(wrinkled - smooth, axis=1)) > 0.02


def test_multi_panel_model_offsets_indices_and_exports(tmp_path):
    model = FlexibleModel("two-panels")
    model.add_panel(_flat_panel(thickness=0.1, rows=4, columns=5))
    model.add_panel(
        FlexiblePanel(
            name="raised",
            control_points=[
                [[0.0, 0.0, 2.0], [0.0, 2.0, 2.0]],
                [[3.0, 0.0, 2.0], [3.0, 2.0, 2.0]],
            ],
            sample_rows=4,
            sample_columns=5,
            material=FlexibleMaterial(thickness=0.1),
        )
    )
    mesh = model.build()
    assert [panel.name for panel in mesh.panels] == ["flat", "raised"]
    assert mesh.panels[1].vertex_start == mesh.panels[0].vertex_count
    assert int(mesh.triangles.max()) < mesh.vertex_count
    assert mesh.surface_area > 0.0

    obj = mesh.write_obj(tmp_path / "model.obj")
    stl = mesh.write_stl(tmp_path / "model.stl")
    metadata = mesh.write_json(tmp_path / "model.json")
    obj_text = obj.read_text(encoding="utf-8")
    assert obj_text.count("\nv ") == mesh.vertex_count
    assert obj_text.count("\nf ") == mesh.triangle_count
    assert "g flat\n" in obj_text and "g raised\n" in obj_text
    with stl.open("rb") as handle:
        handle.seek(80)
        assert struct.unpack("<I", handle.read(4))[0] == mesh.triangle_count
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    assert payload["vertex_count"] == mesh.vertex_count
    assert payload["triangle_count"] == mesh.triangle_count
    assert payload["watertight"] is True


def test_native_builder_is_deterministic():
    panel = sectioned_panel(
        "deterministic",
        [_section(0.0, 2.0, 1.0), _section(3.0, 2.2, 1.1, 0.4)],
        sample_rows=8,
        sample_columns=20,
    )
    first = panel.build()
    second = panel.build()
    assert np.array_equal(first.vertices, second.vertices)
    assert np.array_equal(first.normals, second.normals)
    assert np.array_equal(first.triangles, second.triangles)
