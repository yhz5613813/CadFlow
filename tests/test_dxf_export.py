from __future__ import annotations

from pathlib import Path

import pytest
import ezdxf

import cadflow


def _occt_backend_available() -> bool:
    with cadflow.NativeSession() as session:
        return "analytic" not in session.version


requires_occt = pytest.mark.skipif(
    not _occt_backend_available(), reason="requires the OCCT native backend"
)


def _pairs(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="ascii").splitlines()
    assert len(lines) % 2 == 0
    return [(int(lines[index]), lines[index + 1]) for index in range(0, len(lines), 2)]


def _polylines(path: Path) -> list[dict[str, object]]:
    pairs = _pairs(path)
    entities_start = next(
        index
        for index in range(len(pairs) - 1)
        if pairs[index] == (0, "SECTION") and pairs[index + 1] == (2, "ENTITIES")
    )
    entities_end = next(
        index for index in range(entities_start + 2, len(pairs)) if pairs[index] == (0, "ENDSEC")
    )
    entities: list[dict[str, object]] = []
    index = entities_start + 2
    while index < entities_end:
        if pairs[index] != (0, "LWPOLYLINE"):
            index += 1
            continue
        index += 1
        entity_pairs: list[tuple[int, str]] = []
        while index < entities_end and pairs[index][0] != 0:
            entity_pairs.append(pairs[index])
            index += 1
        vertices: list[list[float]] = []
        for code, value in entity_pairs:
            if code == 10:
                vertices.append([float(value), 0.0, 0.0])
            elif code == 20:
                vertices[-1][1] = float(value)
            elif code == 42:
                vertices[-1][2] = float(value)
        values = {code: value for code, value in entity_pairs if code in {8, 70, 90}}
        entities.append(
            {
                "layer": values[8],
                "closed": int(values[70]) & 1 == 1,
                "declared_count": int(values[90]),
                "vertices": vertices,
            }
        )
    return entities


def _signed_polygon_area(vertices: list[list[float]]) -> float:
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(vertices, vertices[1:] + vertices[:1])
    )


def _read_clean_dxf(path: Path) -> ezdxf.document.Drawing:
    document = ezdxf.readfile(path)
    auditor = document.audit()
    assert auditor.errors == []
    assert auditor.fixes == []
    return document


def _top_face(model: cadflow.Model, shape: cadflow.Shape) -> cadflow.Shape:
    return max(model.faces(shape), key=lambda face: face.center_of_mass[2])


@requires_occt
def test_planar_face_exports_closed_machining_profile(tmp_path: Path) -> None:
    target = tmp_path / "plate.dxf"
    target.write_text("previous", encoding="ascii")
    with cadflow.Model() as model:
        face = _top_face(model, model.box(30, 20, 5))
        face.export_dxf(target)

    pairs = _pairs(target)
    profiles = _polylines(target)
    document = _read_clean_dxf(target)
    reopened = list(document.modelspace().query("LWPOLYLINE"))
    assert (1, "AC1015") in pairs
    assert (9, "$INSUNITS") in pairs
    assert document.dxfversion == "AC1015"
    assert document.units == 4
    assert len(reopened) == 1
    assert reopened[0].closed
    assert target.stat().st_size > 200
    assert len(profiles) == 1
    assert profiles[0]["layer"] == "PROFILE_OUTER"
    assert profiles[0]["closed"]
    assert profiles[0]["declared_count"] == 4
    vertices = profiles[0]["vertices"]
    assert isinstance(vertices, list)
    assert abs(_signed_polygon_area(vertices)) == pytest.approx(600.0)
    assert all(vertex[2] == 0.0 for vertex in vertices)
    assert not list(tmp_path.glob("*.cadflow-*.tmp"))
    assert not list(tmp_path.glob("*.cadflow-*.bak"))


@requires_occt
def test_planar_face_exports_circular_hole_as_exact_bulge(tmp_path: Path) -> None:
    target = tmp_path / "plate-with-hole.dxf"
    with cadflow.Model() as model:
        plate = model.box(30, 20, 5)
        drill = model.translate(model.cylinder(3, 5), 15, 10, 0)
        face = _top_face(model, model.cut(plate, drill))
        face.export_dxf(target, tolerance=0.001)

    profiles = _polylines(target)
    assert [profile["layer"] for profile in profiles] == [
        "PROFILE_OUTER",
        "PROFILE_INNER",
    ]
    assert all(profile["closed"] for profile in profiles)
    outer_vertices = profiles[0]["vertices"]
    inner_vertices = profiles[1]["vertices"]
    assert isinstance(outer_vertices, list)
    assert isinstance(inner_vertices, list)
    assert abs(_signed_polygon_area(outer_vertices)) == pytest.approx(600.0)
    assert len(inner_vertices) == 4
    assert all(abs(vertex[2]) == pytest.approx(2**0.5 - 1) for vertex in inner_vertices)
    document = _read_clean_dxf(target)
    reopened = list(document.modelspace().query("LWPOLYLINE"))
    hole_segments = list(reopened[1].virtual_entities())
    assert [entity.dxftype() for entity in hole_segments] == ["ARC"] * 4
    assert all(entity.dxf.radius == pytest.approx(3.0) for entity in hole_segments)


@requires_occt
def test_rotated_planar_face_keeps_profile_dimensions(tmp_path: Path) -> None:
    target = tmp_path / "rotated-face.dxf"
    with cadflow.Model() as model:
        face = _top_face(model, model.box(30, 20, 5))
        rotated = model.rotate(face, 37, axis=(1, 1, 0))
        rotated.export_dxf(target)

    profiles = _polylines(target)
    assert len(profiles) == 1
    vertices = profiles[0]["vertices"]
    assert isinstance(vertices, list)
    assert abs(_signed_polygon_area(vertices)) == pytest.approx(600.0)


@requires_occt
def test_dxf_export_rejects_non_profile_inputs_without_overwriting(tmp_path: Path) -> None:
    target = tmp_path / "existing.dxf"
    target.write_text("previous", encoding="ascii")
    with cadflow.Model() as model:
        solid = model.box(10, 10, 2)
        with pytest.raises(cadflow.NativeError, match="must be one planar face"):
            solid.export_dxf(target)

        cylinder = model.cylinder(5, 10)
        curved_face = max(model.faces(cylinder), key=lambda face: face.area)
        with pytest.raises(cadflow.NativeError, match="requires a planar face"):
            curved_face.export_dxf(target)

    assert target.read_text(encoding="ascii") == "previous"
    assert not list(tmp_path.glob("*.cadflow-*.tmp"))


@requires_occt
@pytest.mark.parametrize(
    ("filename", "tolerance", "message"),
    [
        ("profile.txt", 0.01, "must end with .dxf"),
        ("profile.dxf", 0.0, "must be finite and positive"),
        ("profile.dxf", float("nan"), "must be finite and positive"),
    ],
)
def test_dxf_export_validates_path_and_tolerance(
    tmp_path: Path, filename: str, tolerance: float, message: str
) -> None:
    with cadflow.Model() as model:
        face = _top_face(model, model.box(10, 10, 2))
        with pytest.raises(cadflow.NativeError, match=message):
            face.export_dxf(tmp_path / filename, tolerance=tolerance)


@requires_occt
def test_dxf_export_requires_existing_directory(tmp_path: Path) -> None:
    with cadflow.Model() as model:
        face = _top_face(model, model.box(10, 10, 2))
        with pytest.raises(cadflow.NativeError, match="directory does not exist"):
            face.export_dxf(tmp_path / "missing" / "profile.dxf")
