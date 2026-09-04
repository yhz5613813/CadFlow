from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import hashlib
import json
import math

import pytest

import cadflow as cad


def _occt() -> bool:
    with cad.NativeSession() as session:
        return "analytic" not in session.version


requires_occt = pytest.mark.skipif(not _occt(), reason="requires OCCT native backend")


def _box_pair(gap: float = 2.0):
    body_a = cad.make_box_rsolid(10.0, 10.0, 10.0)
    body_b = cad.make_box_rsolid(10.0, 10.0, 10.0)
    part_a = cad.make_part_rpart("part_a", body_a)
    part_b = cad.make_part_rpart("part_b", body_b)
    assembly = cad.make_assembly_rassembly("contact_pair")
    assembly = cad.add_component_rassembly(
        assembly, part_a, "a", cad.identity_placement_rplacement()
    )
    assembly = cad.add_component_rassembly(
        assembly,
        part_b,
        "b",
        cad.make_placement_rplacement((0.0, 0.0, 10.0 + gap)),
    )
    top = max(body_a.get_faces(), key=lambda face: face.get_center().z)
    bottom = min(body_b.get_faces(), key=lambda face: face.get_center().z)
    return assembly, top, bottom


def _simulation(gap: float = 2.0):
    assembly, top, bottom = _box_pair(gap)
    surface_a = cad.make_surface_region_rsurfaceregion(
        surface_id="a.top", component_id="a", faces=(top,)
    )
    surface_b = cad.make_surface_region_rsurfaceregion(
        surface_id="b.bottom", component_id="b", faces=(bottom,)
    )
    law = cad.SurfaceContactLaw(
        "dry_steel",
        normal_model="penalty",
        normal_penalty_stiffness=2.0e5,
        friction_model="coulomb",
        friction_coefficient=0.2,
        tangential_penalty_stiffness=8.0e4,
    )
    pair = cad.SurfaceContactPair(
        "block_contact",
        "a.top",
        "b.bottom",
        "dry_steel",
        search_tolerance=gap + 0.01,
    )
    steel = cad.MechanicalMaterial(
        "steel", youngs_modulus=210000.0, poisson_ratio=0.3,
        density=7.85e-9, yield_stress=355.0,
    )
    model = cad.ContactSimulationModel(
        assembly_id="contact_pair",
        surfaces=(surface_a, surface_b),
        contact_laws=(law,),
        contact_pairs=(pair,),
        materials=(steel,),
        component_materials={"a": "steel", "b": "steel"},
    )
    return model, assembly


@requires_occt
def test_native_face_and_pair_metrics_are_solver_neutral() -> None:
    with cad.Model() as model:
        lower = model.box(10.0, 10.0, 10.0)
        upper = model.translate(model.box(10.0, 10.0, 10.0), 0.0, 0.0, 12.0)
        lower_faces = model.faces(lower)
        upper_faces = model.faces(upper)
        top = max(lower_faces, key=lambda face: face.center_of_mass[2])
        bottom = min(upper_faces, key=lambda face: face.center_of_mass[2])

        face = top.surface_metrics()
        pair = top.contact_metrics(bottom)

        assert len(lower_faces) == 6
        assert face["area"] == pytest.approx(100.0)
        assert face["surface_geometry"] == "plane"
        assert face["normal"] == pytest.approx((0.0, 0.0, 1.0))
        assert face["valid"] is True
        assert pair["minimum_distance"] == pytest.approx(2.0)
        assert pair["normal_dot"] == pytest.approx(-1.0)
        assert pair["signed_normal_gap"] == pytest.approx(2.0)
        assert pair["tangential_offset"] == pytest.approx(0.0)


@requires_occt
def test_native_curved_surface_reports_curvature() -> None:
    with cad.Model() as model:
        cylinder = model.cylinder(5.0, 10.0)
        curved = next(
            face for face in model.faces(cylinder)
            if face.surface_metrics()["surface_geometry"] == "cylinder"
        )
        metrics = curved.surface_metrics()
        assert metrics["area"] == pytest.approx(100.0 * math.pi, rel=1e-6)
        assert abs(float(metrics["principal_curvature_min"])) == pytest.approx(0.2, rel=1e-6)
        assert float(metrics["principal_curvature_max"]) == pytest.approx(0.0, abs=1e-9)


@requires_occt
def test_curved_pair_normals_are_evaluated_at_closest_points() -> None:
    with cad.Model() as model:
        left = model.cylinder(5.0, 10.0)
        right = model.translate(model.cylinder(5.0, 10.0), 12.0, 0.0, 0.0)
        face_a = next(
            face for face in model.faces(left)
            if face.surface_metrics()["surface_geometry"] == "cylinder"
        )
        face_b = next(
            face for face in model.faces(right)
            if face.surface_metrics()["surface_geometry"] == "cylinder"
        )
        metrics = face_a.contact_metrics(face_b)
        assert metrics["minimum_distance"] == pytest.approx(2.0)
        assert metrics["face_a"]["normal"] == pytest.approx(
            (1.0, 0.0, 0.0), abs=1e-9
        )
        assert metrics["face_b"]["normal"] == pytest.approx(
            (-1.0, 0.0, 0.0), abs=1e-9
        )
        assert metrics["normal_dot"] == pytest.approx(-1.0)
        assert metrics["signed_normal_gap"] == pytest.approx(2.0)


def test_contact_law_enforces_distributed_units_and_modes() -> None:
    with pytest.raises(ValueError, match="normal_penalty_stiffness"):
        cad.SurfaceContactLaw("bad", normal_model="penalty")
    with pytest.raises(ValueError, match="frictionless"):
        cad.SurfaceContactLaw("bad", friction_coefficient=0.2)
    with pytest.raises(ValueError, match="at least two"):
        cad.SurfaceContactLaw("bad", normal_model="tabular")
    law = cad.SurfaceContactLaw(
        "nonlinear",
        normal_model="tabular",
        pressure_overclosure=((0.0, 0.0), (0.1, 100.0)),
    )
    assert law.pressure_overclosure == ((0.0, 0.0), (0.1, 100.0))


@requires_occt
def test_contact_model_round_trip_validation_and_native_analysis() -> None:
    model, assembly = _simulation()
    replayed = cad.ContactSimulationModel.from_json(model.to_json(indent=None))
    assert replayed == model
    assert replayed.to_dict()["units"]["contact_penalty"] == "N/mm^3"
    assert replayed.to_dict()["units"]["density"] == "N*s^2/mm^4"

    validation = cad.validate_contact_simulation_model_rcontactsimulationvalidationreport(
        replayed, assembly
    )
    assert validation.valid
    assert validation.issues == ()

    analysis = cad.analyze_contact_simulation_model_rcontactsimulationanalysis(
        replayed, assembly
    )
    pair = analysis.pair_metrics[0]
    assert analysis.backend == "native_cpp_occt"
    assert pair["candidate_count"] == 1
    assert pair["face_pairs"][0]["minimum_distance"] == pytest.approx(2.0)
    assert pair["face_pairs"][0]["normal_dot"] == pytest.approx(-1.0)
    assert pair["face_pairs"][0]["solver_initial_normal_gap"] == pytest.approx(2.0)
    assert pair["face_pairs"][0]["initial_overclosure"] == pytest.approx(0.0)
    assert pair["face_pairs"][0]["initial_contact_candidate"] is True


@requires_occt
def test_declared_interference_is_exported_as_initial_overclosure() -> None:
    model, assembly = _simulation(gap=2.0)
    pair = replace(model.contact_pairs[0], search_tolerance=0.0, interference=2.5)
    model = replace(model, contact_pairs=(pair,))
    analysis = cad.analyze_contact_simulation_model_rcontactsimulationanalysis(
        model, assembly
    )
    metrics = analysis.pair_metrics[0]["face_pairs"][0]
    assert metrics["solver_initial_normal_gap"] == pytest.approx(-0.5)
    assert metrics["initial_overclosure"] == pytest.approx(0.5)
    assert metrics["initial_contact_candidate"] is True


@requires_occt
def test_face_flip_changes_contact_orientation_without_changing_geometry() -> None:
    model, assembly = _simulation()
    flipped = replace_surface_flip(model, "b.bottom")
    analysis = cad.analyze_contact_simulation_model_rcontactsimulationanalysis(
        flipped, assembly
    )
    pair = analysis.pair_metrics[0]["face_pairs"][0]
    assert pair["minimum_distance"] == pytest.approx(2.0)
    assert pair["normal_dot"] == pytest.approx(1.0)
    assert pair["initial_contact_candidate"] is False


def replace_surface_flip(model: cad.ContactSimulationModel, surface_id: str):
    surfaces = []
    for surface in model.surfaces:
        if surface.surface_id == surface_id:
            refs = tuple(
                cad.GeometryRef(ref.kind, ref.source_node_id, ref.geo_selector, not ref.flip)
                for ref in surface.geometry_refs
            )
            surface = cad.SurfaceRegion(
                surface.surface_id, surface.component_id, refs,
                surface.role, surface.property_id, surface.metadata,
            )
        surfaces.append(surface)
    return cad.ContactSimulationModel(
        assembly_id=model.assembly_id,
        surfaces=tuple(surfaces),
        contact_laws=model.contact_laws,
        contact_pairs=model.contact_pairs,
        surface_properties=model.surface_properties,
        materials=model.materials,
        component_materials=model.component_materials,
    )


def test_validation_rejects_missing_references() -> None:
    model, assembly = _simulation()
    invalid_pair = cad.SurfaceContactPair(
        "missing", "a.top", "unknown", "dry_steel", search_tolerance=1.0
    )
    invalid = cad.ContactSimulationModel(
        assembly_id=model.assembly_id,
        surfaces=model.surfaces,
        contact_laws=model.contact_laws,
        contact_pairs=(invalid_pair,),
        materials=model.materials,
        component_materials=model.component_materials,
    )
    report = cad.validate_contact_simulation_model_rcontactsimulationvalidationreport(
        invalid, assembly
    )
    assert not report.valid
    assert {issue.code for issue in report.errors} == {"surface_missing"}
    with pytest.raises(ValueError, match="does not exist"):
        report.raise_for_errors()


@requires_occt
def test_simulation_package_contains_verified_face_breps(tmp_path) -> None:
    model, assembly = _simulation()
    manifest_path = cad.export_contact_simulation_package_rpath(
        model, assembly, tmp_path / "package"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "cadflow-contact-simulation-package"
    assert payload["analysis"]["backend"] == "native_cpp_occt"
    components = payload["analysis"]["components"]
    assert [item["component_id"] for item in components] == ["a", "b"]
    assert all(item["material_id"] == "steel" for item in components)
    faces = [
        face
        for surface in payload["analysis"]["resolved_surfaces"]
        for face in surface["faces"]
    ]
    assert len(faces) == 2
    assert payload["analysis"]["pair_metrics"][0]["candidate_count"] == 1
    for face in faces:
        assert face["component_face_index"] in range(6)
        path = manifest_path.parent / face["brep_uri"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == face["brep_sha256"]
        assert len(data) == face["local_brep_byte_length"]
        from OCP.BRep import BRep_Builder
        from OCP.BRepTools import BRepTools
        from OCP.TopoDS import TopoDS_Shape
        shape = TopoDS_Shape()
        BRepTools.Read_s(shape, BytesIO(data), BRep_Builder())
        assert not shape.IsNull()

    for component in components:
        path = manifest_path.parent / component["brep_uri"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == component["brep_sha256"]
        assert len(data) == component["brep_byte_length"]

    first_bytes = manifest_path.read_bytes()
    second = cad.export_contact_simulation_package_rpath(
        model, assembly, tmp_path / "package"
    )
    assert second.read_bytes() == first_bytes
