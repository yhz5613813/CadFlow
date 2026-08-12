import importlib.util
import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np
import pytest


pytest.importorskip("matplotlib")


def _load_example():
    path = Path(__file__).resolve().parents[1] / "examples" / "cadflow_static_flexible_garment.py"
    spec = importlib.util.spec_from_file_location("cadflow_static_flexible_garment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_flexible_garment_outputs_are_complete(tmp_path):
    example = _load_example()
    mesh = example.build_garment()

    assert mesh.vertex_count == 26720
    assert mesh.triangle_count == 53440
    assert len(mesh.panels) == 5
    assert mesh.is_watertight
    assert mesh.surface_area > 6_000_000.0
    assert np.all(np.isfinite(mesh.vertices))
    points = mesh.vertices[mesh.triangles]
    triangle_areas = 0.5 * np.linalg.norm(
        np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1
    )
    assert float(triangle_areas.min()) > 1e-6
    for panel in mesh.panels:
        triangles = mesh.triangles[
            panel.triangle_start : panel.triangle_start + panel.triangle_count
        ]
        directed = Counter()
        for left, right, third in triangles:
            a, b, c = int(left), int(right), int(third)
            directed[(a, b)] += 1
            directed[(b, c)] += 1
            directed[(c, a)] += 1
        undirected = {tuple(sorted(edge)) for edge in directed}
        assert all(
            directed[edge] == 1 and directed[(edge[1], edge[0])] == 1
            for edge in undirected
        )

    paths = example.write_outputs(mesh, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["vertex_count"] == mesh.vertex_count
    assert payload["triangle_count"] == mesh.triangle_count
    assert payload["watertight"] is True

    obj_text = paths["obj"].read_text(encoding="utf-8")
    assert obj_text.count("\nv ") == mesh.vertex_count
    assert obj_text.count("\nf ") == mesh.triangle_count
    assert obj_text.count("\ng ") == len(mesh.panels)

    assert paths["stl"].stat().st_size == 84 + 50 * mesh.triangle_count
    with paths["stl"].open("rb") as handle:
        handle.seek(80)
        assert struct.unpack("<I", handle.read(4))[0] == mesh.triangle_count

    png = paths["png"].read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert width >= 1200 and height >= 1000
    assert len(png) > 100_000
