import inspect
import json
import math

import pytest

import cadflow as cad
from cadflow import ql


def test_material_validation_and_assignment_are_separate_from_part_creation():
    body = cad.make_box_rsolid(2.0, 3.0, 1.0)
    part_signature = inspect.signature(cad.make_part_rpart)

    assert "material" not in part_signature.parameters

    material = cad.make_material_rmaterial(
        "aluminum_6061",
        name="Aluminum 6061",
        density=2.7e-6,
        density_unit="kg/mm^3",
        color=(0.7, 0.7, 0.75),
    )
    part = cad.make_part_rpart("base_plate", body, name="Base plate")
    assigned = cad.assign_material_rpart(part, material)

    assert part.material is None
    assert assigned.material == material
    assert assigned.body is body

    with pytest.raises(Exception, match="density_unit"):
        cad.make_material_rmaterial("bad_density", density=1.0)

    with pytest.raises(Exception, match="color"):
        cad.make_material_rmaterial("bad_color", color=(1.2, 0.0, 0.0))


def test_product_and_constraint_public_apis_do_not_use_bare_star_parameters():
    public_apis = [
        cad.make_material_rmaterial,
        cad.make_placement_rplacement,
        cad.make_part_rpart,
        cad.make_assembly_rassembly,
        cad.add_component_rassembly,
        cad.make_face_connector_rconnector,
        cad.make_edge_connector_rconnector,
        cad.make_vertex_connector_rconnector,
        cad.make_placement_connector_rconnector,
        cad.add_connector_rpart,
        cad.add_connector_rassembly,
        cad.forward_connector_rassembly,
        cad.make_connector_ref_rconnectorref,
        cad.make_scalar_limit_rscalarlimit,
        cad.ground_component_rassembly,
        cad.unground_component_rassembly,
        cad.add_fixed_constraint_rassembly,
        cad.add_revolute_constraint_rassembly,
        cad.add_prismatic_constraint_rassembly,
        cad.add_gear_constraint_rassembly,
        cad.add_belt_constraint_rassembly,
        cad.add_rack_pinion_constraint_rassembly,
        cad.solve_assembly_constraints_rassembly,
    ]

    for api in public_apis:
        signature = inspect.signature(api)
        assert all(
            parameter.kind is not inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )


def test_placement_is_canonical_right_handed_frame():
    placement = cad.make_placement_rplacement(
        origin=(10.0, 20.0, 30.0),
        x_axis=(0.0, 1.0, 0.0),
        y_axis=(-1.0, 0.0, 0.0),
    )

    assert placement.origin == (10.0, 20.0, 30.0)
    assert placement.z_axis == (0.0, -0.0, 1.0)
    assert placement.transform_point((1.0, 2.0, 3.0)) == (8.0, 21.0, 33.0)

    with pytest.raises(Exception, match="orthogonal"):
        cad.make_placement_rplacement(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(1.0, 0.0, 0.0),
        )

    with pytest.raises(Exception, match="non-zero"):
        cad.make_placement_rplacement(
            origin=(0.0, 0.0, 0.0),
            x_axis=(0.0, 0.0, 0.0),
        )


def test_assembly_components_reuse_part_and_project_to_compound():
    bolt_body = cad.make_cylinder_rsolid(1.0, 2.0)
    bolt_part = cad.make_part_rpart("bolt", bolt_body)
    assembly = cad.make_assembly_rassembly("fixture")

    assembly = cad.add_component_rassembly(
        assembly,
        bolt_part,
        component_id="bolt_left",
        placement=cad.make_placement_rplacement(origin=(-5.0, 0.0, 0.0)),
    )
    assembly = cad.add_component_rassembly(
        assembly,
        bolt_part,
        component_id="bolt_right",
        placement=cad.make_placement_rplacement(origin=(5.0, 0.0, 0.0)),
    )

    assert assembly.component_ids() == ("bolt_left", "bolt_right")
    assert assembly.get_component("bolt_left").item is bolt_part

    compound = cad.make_compound_from_assembly_rcompound(assembly)
    assert isinstance(compound, cad.Compound)
    assert len(compound.get_solids()) == 2
    assert math.isclose(compound.get_volume(), 2.0 * bolt_body.get_volume(), rel_tol=1e-7)

    face_centers_x = sorted(round(face.get_center().x, 1) for face in ql.faces().resolve(compound))
    assert face_centers_x[0] < 0.0
    assert face_centers_x[-1] > 0.0


def test_nested_assembly_projection_composes_component_placements():
    body = cad.make_box_rsolid(1.0, 1.0, 1.0)
    part = cad.make_part_rpart("cube_part", body)
    child = cad.make_assembly_rassembly("child_assembly")
    child = cad.add_component_rassembly(
        child,
        part,
        component_id="cube",
        placement=cad.make_placement_rplacement(origin=(2.0, 0.0, 0.0)),
    )
    root = cad.make_assembly_rassembly("root_assembly")
    root = cad.add_component_rassembly(
        root,
        child,
        component_id="child",
        placement=cad.make_placement_rplacement(origin=(10.0, 0.0, 0.0)),
    )

    compound = cad.make_compound_from_assembly_rcompound(root)
    face_centers_x = sorted(round(face.get_center().x, 1) for face in ql.faces().resolve(compound))

    assert len(compound.get_solids()) == 1
    assert face_centers_x[0] >= 11.5
    assert face_centers_x[-1] <= 12.5


def _part_with_face_connector(part_id):
    body = cad.make_box_rsolid(1.0, 1.0, 1.0)
    part = cad.make_part_rpart(part_id, body)
    top_face = ql.faces().resolve(body)[-1]
    connector = cad.make_face_connector_rconnector("axis", top_face)
    return cad.add_connector_rpart(part, connector)


def _part_with_placement_connector(part_id, connector_origin=(0.0, 0.0, 0.0)):
    body = cad.make_box_rsolid(1.0, 1.0, 1.0)
    part = cad.make_part_rpart(part_id, body)
    placement = cad.make_placement_rplacement(origin=connector_origin)
    connector = cad.make_placement_connector_rconnector("axis", placement)
    return cad.add_connector_rpart(part, connector)


def test_placement_connector_can_drive_fixed_constraints():
    part = _part_with_placement_connector("placement_constraint_part")
    assembly = cad.make_assembly_rassembly("placement_constraint_asm")
    assembly = cad.add_component_rassembly(
        assembly,
        part,
        component_id="base",
        placement=cad.make_placement_rplacement(origin=(1.0, 2.0, 3.0)),
    )
    assembly = cad.add_component_rassembly(
        assembly,
        part,
        component_id="follower",
        placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.ground_component_rassembly(assembly, "base")
    assembly = cad.add_fixed_constraint_rassembly(
        assembly,
        "fixed",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("follower", "axis"),
    )

    solved = cad.solve_assembly_constraints_rassembly(assembly)

    assert solved.get_component("follower").placement.origin == (1.0, 2.0, 3.0)
    assert cad.measure_constraint_residual_rconstraintresidual(solved, "fixed").within_tolerance


def test_forwarded_connector_resolves_and_solves_at_parent_level():
    inner_part = _part_with_placement_connector("forwarded_inner_part", (2.0, 0.0, 0.0))
    base_part = _part_with_placement_connector("forwarded_base_part")
    child = cad.make_assembly_rassembly("forwarded_child")
    child = cad.add_component_rassembly(
        child,
        inner_part,
        component_id="inner",
        placement=cad.make_placement_rplacement(origin=(5.0, 0.0, 0.0)),
    )
    child = cad.forward_connector_rassembly(
        child,
        connector_id="public_axis",
        source_component_id="inner",
        source_connector_id="axis",
    )

    assert child.connector_ids() == ("public_axis",)
    assert child.get_connector("public_axis").placement.origin == (7.0, 0.0, 0.0)

    root = cad.make_assembly_rassembly("forwarded_root")
    root = cad.add_component_rassembly(
        root,
        base_part,
        component_id="base",
        placement=cad.make_placement_rplacement(origin=(10.0, 0.0, 0.0)),
    )
    root = cad.add_component_rassembly(
        root,
        child,
        component_id="child",
        placement=cad.identity_placement_rplacement(),
    )
    root = cad.ground_component_rassembly(root, "base")
    root = cad.add_fixed_constraint_rassembly(
        root,
        "bind_forwarded_axis",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("child", "public_axis"),
    )
    solved = cad.solve_assembly_constraints_rassembly(root)

    assert solved.get_component("child").placement.origin == (3.0, 0.0, 0.0)
    assert cad.measure_constraint_residual_rconstraintresidual(
        solved,
        "bind_forwarded_axis",
    ).within_tolerance


def test_forwarded_connector_validation_reports_missing_sources():
    assembly = cad.make_assembly_rassembly("bad_forwarded_connector_asm")

    with pytest.raises(Exception, match="missing component"):
        cad.forward_connector_rassembly(
            assembly,
            connector_id="public_axis",
            source_component_id="inner",
            source_connector_id="axis",
        )


def test_fixed_revolute_and_prismatic_constraints_solve_component_placements():
    part = _part_with_face_connector("constraint_part")

    fixed_assembly = cad.make_assembly_rassembly("fixed_asm")
    fixed_assembly = cad.add_component_rassembly(
        fixed_assembly,
        part,
        component_id="base",
        placement=cad.make_placement_rplacement((1.0, 2.0, 3.0)),
    )
    fixed_assembly = cad.add_component_rassembly(
        fixed_assembly,
        part,
        component_id="follower",
        placement=cad.identity_placement_rplacement(),
    )
    fixed_assembly = cad.ground_component_rassembly(fixed_assembly, "base")
    fixed_assembly = cad.add_fixed_constraint_rassembly(
        fixed_assembly,
        "fixed",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("follower", "axis"),
    )
    fixed_solved = cad.solve_assembly_constraints_rassembly(fixed_assembly)
    assert fixed_solved.get_component("follower").placement.origin == (1.0, 2.0, 3.0)
    assert cad.measure_constraint_residual_rconstraintresidual(
        fixed_solved, "fixed"
    ).within_tolerance

    revolute_assembly = cad.make_assembly_rassembly("revolute_asm")
    revolute_assembly = cad.add_component_rassembly(
        revolute_assembly,
        part,
        component_id="base",
        placement=cad.identity_placement_rplacement(),
    )
    revolute_assembly = cad.add_component_rassembly(
        revolute_assembly,
        part,
        component_id="arm",
        placement=cad.identity_placement_rplacement(),
    )
    revolute_assembly = cad.ground_component_rassembly(revolute_assembly, "base")
    revolute_assembly = cad.add_revolute_constraint_rassembly(
        revolute_assembly,
        "hinge",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("arm", "axis"),
        drive_angle_degrees=90.0,
    )
    revolute_solved = cad.solve_assembly_constraints_rassembly(revolute_assembly)
    arm_placement = revolute_solved.get_component("arm").placement
    assert math.isclose(arm_placement.origin[0], 0.0, abs_tol=1e-12)
    assert math.isclose(arm_placement.origin[1], 0.0, abs_tol=1e-12)
    assert math.isclose(arm_placement.origin[2], 0.0, abs_tol=1e-12)
    assert math.isclose(revolute_solved.get_component("arm").placement.x_axis[0], 0.0, abs_tol=1e-10)
    assert math.isclose(revolute_solved.get_component("arm").placement.x_axis[1], 1.0, abs_tol=1e-10)

    prismatic_assembly = cad.make_assembly_rassembly("prismatic_asm")
    prismatic_assembly = cad.add_component_rassembly(
        prismatic_assembly,
        part,
        component_id="base",
        placement=cad.identity_placement_rplacement(),
    )
    prismatic_assembly = cad.add_component_rassembly(
        prismatic_assembly,
        part,
        component_id="slider",
        placement=cad.identity_placement_rplacement(),
    )
    prismatic_assembly = cad.ground_component_rassembly(prismatic_assembly, "base")
    prismatic_assembly = cad.add_prismatic_constraint_rassembly(
        prismatic_assembly,
        "slide",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("slider", "axis"),
        drive_distance=5.0,
    )
    prismatic_solved = cad.solve_assembly_constraints_rassembly(prismatic_assembly)
    assert prismatic_solved.get_component("slider").placement.origin == (0.0, 0.0, 5.0)
    report = cad.inspect_assembly_constraints_rconstraintreport(prismatic_solved)
    assert report.solved


def test_constraint_validation_rejects_missing_refs_and_limit_violations():
    part = _part_with_face_connector("limited_part")
    assembly = cad.make_assembly_rassembly("limited_asm")
    assembly = cad.add_component_rassembly(
        assembly,
        part,
        component_id="base",
        placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.add_component_rassembly(
        assembly,
        part,
        component_id="slider",
        placement=cad.identity_placement_rplacement(),
    )
    connector_a = cad.make_connector_ref_rconnectorref("base", "axis")
    connector_b = cad.make_connector_ref_rconnectorref("slider", "axis")

    assembly_with_limit = cad.ground_component_rassembly(assembly, "base")
    assembly_with_limit = cad.add_prismatic_constraint_rassembly(
        assembly_with_limit, "slide",
        connector_a,
        connector_b,
        drive_distance=10.0,
        distance_limit=cad.make_scalar_limit_rscalarlimit(0.0, 5.0),
    )
    solved = cad.solve_assembly_constraints_rassembly(assembly_with_limit)
    assert solved.get_component("slider").placement.origin == (0.0, 0.0, 5.0)

    with pytest.raises(Exception, match="connector"):
        cad.add_fixed_constraint_rassembly(
            assembly,
            "missing",
            connector_a,
            cad.make_connector_ref_rconnectorref("slider", "missing_axis"),
        )

    with pytest.raises(Exception, match="grounded"):
        ungrounded = cad.make_assembly_rassembly("ungrounded_asm")
        ungrounded = cad.add_component_rassembly(
            ungrounded, part, component_id="base", placement=cad.identity_placement_rplacement(),
        )
        ungrounded = cad.add_component_rassembly(
            ungrounded, part, component_id="slider", placement=cad.identity_placement_rplacement(),
        )
        ungrounded = cad.add_prismatic_constraint_rassembly(
            ungrounded, "slide_ungrounded",
            cad.make_connector_ref_rconnectorref("base", "axis"),
            cad.make_connector_ref_rconnectorref("slider", "axis"),
            drive_distance=1.0,
        )
        cad.solve_assembly_constraints_rassembly(ungrounded)


def test_assembly_rejects_duplicate_components_raw_solids_and_cycles():
    body = cad.make_box_rsolid(1.0, 1.0, 1.0)
    part = cad.make_part_rpart("box_part", body)
    placement = cad.identity_placement_rplacement()
    assembly = cad.make_assembly_rassembly("root")
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="box", placement=placement
    )

    with pytest.raises(Exception, match="duplicate component_id"):
        cad.add_component_rassembly(
            assembly, part, component_id="box", placement=placement
        )

    with pytest.raises(Exception, match="item"):
        cad.add_component_rassembly(
            assembly, body, component_id="raw_solid", placement=placement
        )

    child = cad.make_assembly_rassembly("child")
    child = cad.add_component_rassembly(
        child, assembly, component_id="parent_instance", placement=placement
    )

    with pytest.raises(Exception, match="cycle"):
        cad.add_component_rassembly(
            assembly, child, component_id="child_instance", placement=placement
        )


def test_product_graph_model_json_and_replay_roundtrip():
    with cad.GraphSession() as session:
        body = cad.make_box_rsolid(2.0, 3.0, 1.0)
        material = cad.make_material_rmaterial(
            "steel_8_8",
            density=7.85e-6,
            density_unit="kg/mm^3",
        )
        part = cad.make_part_rpart("plate", body)
        part = cad.assign_material_rpart(part, material)
        assembly = cad.make_assembly_rassembly("fixture")
        assembly = cad.add_component_rassembly(
            assembly,
            part,
            component_id="plate_1",
            placement=cad.identity_placement_rplacement(),
        )
        compound = cad.make_compound_from_assembly_rcompound(assembly)

    payload = json.loads(cad.export_model_json(session))
    ops = [node["op"] for node in payload["graph"]["nodes"]]

    assert "make_material_rmaterial" in ops
    assert "make_part_rpart" in ops
    assert "make_assign_material_rpart" in ops
    assert "make_assembly_rassembly" in ops
    assert "make_add_component_rassembly" in ops
    assert "make_compound_from_assembly_rcompound" in ops
    assert any(
        item["entity_type"] == "Part" and item["entity_id"] == "plate"
        for item in payload["semantic_entity_registry"]
    )

    replayed = cad.replay_model_json(json.dumps(payload))
    assert len(replayed) == 1
    assert isinstance(replayed[0], cad.Compound)
    assert math.isclose(replayed[0].get_volume(), compound.get_volume(), rel_tol=1e-7)


def test_constraint_graph_model_json_and_replay_roundtrip():
    with cad.GraphSession() as session:
        part = _part_with_face_connector("replay_constraint_part")
        assembly = cad.make_assembly_rassembly("replay_constraint_asm")
        assembly = cad.add_component_rassembly(
            assembly,
            part,
            component_id="base",
            placement=cad.identity_placement_rplacement(),
        )
        assembly = cad.add_component_rassembly(
            assembly,
            part,
            component_id="slider",
            placement=cad.identity_placement_rplacement(),
        )
        assembly = cad.ground_component_rassembly(assembly, "base")
        connector_a = cad.make_connector_ref_rconnectorref("base", "axis")
        connector_b = cad.make_connector_ref_rconnectorref("slider", "axis")
        limit = cad.make_scalar_limit_rscalarlimit(0.0, 10.0)
        assembly = cad.add_prismatic_constraint_rassembly(
            assembly,
            "slide",
            connector_a,
            connector_b,
            drive_distance=4.0,
            distance_limit=limit,
        )
        solved = cad.solve_assembly_constraints_rassembly(assembly)

    payload = json.loads(cad.export_model_json(session))
    ops = [node["op"] for node in payload["graph"]["nodes"]]
    assert "make_face_connector_rconnector" in ops
    assert "make_add_connector_rpart" in ops
    assert "make_connector_ref_rconnectorref" in ops
    assert "make_scalar_limit_rscalarlimit" in ops
    assert "make_ground_component_rassembly" in ops
    assert "make_prismatic_constraint_rassembly" in ops
    assert "make_solve_assembly_constraints_rassembly" in ops

    replayed = cad.replay_model_json(json.dumps(payload))
    assert len(replayed) == 1
    assert isinstance(replayed[0], cad.Assembly)
    assert replayed[0].get_component("slider").placement.origin == (0.0, 0.0, 4.0)
    assert replayed[0].constraints[0].distance_limit.lower_value == 0.0
    assert solved.get_component("slider").placement.origin == (0.0, 0.0, 4.0)


def test_boolean_named_face_connector_resolves_after_replay():
    with cad.GraphSession() as session:
        flange = cad.extrude_rsolid(
            cad.make_circle_rface(
                center=(0.0, 0.0, 0.0),
                radius=2.0,
                normal=(1.0, 0.0, 0.0),
            ),
            direction=(1.0, 0.0, 0.0),
            distance=2.0,
            end_face_tag="cap.face.end",
        )
        body = cad.make_cylinder_rsolid(
            radius=1.5,
            height=4.0,
            bottom_face_center=(-1.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        bridge = cad.make_box_rsolid(
            width=1.0,
            height=1.0,
            depth=1.0,
            bottom_face_center=(-0.5, -0.5, -0.5),
        )
        fused = cad.union_rsolid(body, flange, bridge, glue=False)
        result = cad.cut_rsolid(
            fused,
            cad.make_cylinder_rsolid(
                radius=0.25,
                height=4.0,
                bottom_face_center=(-1.0, 1.0, 0.0),
                axis=(1.0, 0.0, 0.0),
            ),
        )
        named_face = (
            ql.faces()
            .where(ql.tag("cap.face.end"))
            .exactly(1)
            .resolve(result)[0]
        )
        connector = cad.make_face_connector_rconnector("mount", named_face)
        part = cad.add_connector_rpart(
            cad.make_part_rpart("boolean_named_part", result),
            connector,
        )
        session.capture_result(value=part)

    replayed = cad.replay_model_json(cad.export_model_json(session))[0]
    assert isinstance(replayed, cad.Part)
    replayed_face = (
        ql.faces()
        .where(ql.tag("cap.face.end"))
        .exactly(1)
        .resolve(replayed.body)[0]
    )
    assert replayed.get_connector("mount").placement.origin == pytest.approx(
        tuple(replayed_face.get_center())
    )

    package = cad.compile_scene(
        scene_id="boolean-named-connector",
        roots=(cad.SceneRoot(root_id="main", value=replayed),),
    )
    snapshot = package.manifest["connectors"][0]
    asset = next(
        item
        for item in package.manifest["entity_assets"]
        if item["entity_asset_id"] == snapshot["target"]["entity_asset_id"]
    )
    entity_document = json.loads(package.blobs[asset["uri"]])
    target = next(
        item
        for item in entity_document["entities"]
        if item["entity_id"] == snapshot["target"]["entity_id"]
    )
    assert "cap.face.end" in target["evaluated_tags"]


def test_nested_constraint_graph_replay_preserves_child_assembly_constraints():
    with cad.GraphSession() as session:
        part = _part_with_placement_connector("nested_replay_part")
        child = cad.make_assembly_rassembly(assembly_id="nested_replay_child")
        child = cad.add_component_rassembly(
            assembly=child,
            item=part,
            component_id="base",
            placement=cad.identity_placement_rplacement(),
        )
        child = cad.add_component_rassembly(
            assembly=child,
            item=part,
            component_id="arm",
            placement=cad.identity_placement_rplacement(),
        )
        child = cad.ground_component_rassembly(
            assembly=child,
            component_id="base",
        )
        child = cad.add_revolute_constraint_rassembly(
            assembly=child,
            constraint_id="pivot",
            connector_a=cad.make_connector_ref_rconnectorref(
                component_id="base",
                connector_id="axis",
            ),
            connector_b=cad.make_connector_ref_rconnectorref(
                component_id="arm",
                connector_id="axis",
            ),
            drive_angle_degrees=30.0,
        )
        child = cad.solve_assembly_constraints_rassembly(assembly=child)

        root = cad.make_assembly_rassembly(assembly_id="nested_replay_root")
        root = cad.add_component_rassembly(
            assembly=root,
            item=child,
            component_id="child",
            placement=cad.make_placement_rplacement(origin=(10.0, 20.0, 30.0)),
        )

    payload = json.loads(cad.export_model_json(session))
    ops = [node["op"] for node in payload["graph"]["nodes"]]
    assert ops.count("make_revolute_constraint_rassembly") == 1
    assert ops.count("make_solve_assembly_constraints_rassembly") == 1
    assert ops.count("make_add_component_rassembly") == 3

    replayed = cad.replay_model_json(json.dumps(payload))
    assert len(replayed) == 1
    replayed_root = replayed[0]
    assert isinstance(replayed_root, cad.Assembly)
    replayed_child = replayed_root.get_component("child").item
    assert isinstance(replayed_child, cad.Assembly)
    assert replayed_child.assembly_id == "nested_replay_child"
    assert replayed_child.component_ids() == ("base", "arm")
    assert replayed_child.constraint_ids() == ("pivot",)
    assert replayed_child.grounded_component_ids == ("base",)
    assert replayed_child.get_constraint("pivot").drive_angle_degrees == 30.0
    assert replayed_child.get_component("arm").placement.x_axis == (
        math.cos(math.radians(30.0)),
        math.sin(math.radians(30.0)),
        0.0,
    )
    assert replayed_root.get_component("child").placement.origin == (10.0, 20.0, 30.0)


def test_graph_session_rejects_duplicate_product_ids():
    with pytest.raises(Exception, match="duplicate part"):
        with cad.GraphSession():
            cad.make_part_rpart("same_part", cad.make_box_rsolid(1, 1, 1))
            cad.make_part_rpart("same_part", cad.make_box_rsolid(1, 1, 1))


def test_limit_aware_prismatic_tree_clamps_scalar_to_bounds():
    part = _part_with_face_connector("clamp_part")
    assembly = cad.make_assembly_rassembly("clamp_asm")
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="base", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="slider", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.ground_component_rassembly(assembly, "base")
    assembly = cad.add_prismatic_constraint_rassembly(
        assembly, "slide",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("slider", "axis"),
        drive_distance=100.0,
        distance_limit=cad.make_scalar_limit_rscalarlimit(0.0, 5.0),
    )
    solved = cad.solve_assembly_constraints_rassembly(assembly)
    assert solved.get_component("slider").placement.origin == (0.0, 0.0, 5.0)
    residual = cad.measure_constraint_residual_rconstraintresidual(solved, "slide")
    assert residual.within_tolerance


def test_limit_aware_prismatic_tree_uses_drive_when_within_bounds():
    part = _part_with_face_connector("inrange_part")
    assembly = cad.make_assembly_rassembly("inrange_asm")
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="base", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="slider", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.ground_component_rassembly(assembly, "base")
    assembly = cad.add_prismatic_constraint_rassembly(
        assembly, "slide",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("slider", "axis"),
        drive_distance=3.0,
        distance_limit=cad.make_scalar_limit_rscalarlimit(0.0, 10.0),
    )
    solved = cad.solve_assembly_constraints_rassembly(assembly)
    assert solved.get_component("slider").placement.origin == (0.0, 0.0, 3.0)


def test_limit_aware_revolute_tree_clamps_angle_to_bounds():
    part = _part_with_face_connector("rev_clamp_part")
    assembly = cad.make_assembly_rassembly("rev_clamp_asm")
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="base", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="arm", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.ground_component_rassembly(assembly, "base")
    assembly = cad.add_revolute_constraint_rassembly(
        assembly, "hinge",
        cad.make_connector_ref_rconnectorref("base", "axis"),
        cad.make_connector_ref_rconnectorref("arm", "axis"),
        drive_angle_degrees=999.0,
        angle_limit=cad.make_scalar_limit_rscalarlimit(0.0, 45.0),
    )
    solved = cad.solve_assembly_constraints_rassembly(assembly)
    arm_x = solved.get_component("arm").placement.x_axis
    expected_cos = math.cos(math.radians(45.0))
    expected_sin = math.sin(math.radians(45.0))
    assert math.isclose(arm_x[0], expected_cos, abs_tol=1e-10)
    assert math.isclose(arm_x[1], expected_sin, abs_tol=1e-10)


def test_limit_aware_revolute_loop_finds_optimal_angle():
    part_a = _part_with_face_connector("loop_a")
    part_b = _part_with_face_connector("loop_b")
    assembly = cad.make_assembly_rassembly("rev_loop")
    assembly = cad.add_component_rassembly(
        assembly, part_a, component_id="link1",
        placement=cad.make_placement_rplacement(origin=(5.0, 0.0, 0.0)),
    )
    assembly = cad.add_component_rassembly(
        assembly, part_b, component_id="link2",
        placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.ground_component_rassembly(assembly, "link1")
    connector_a = cad.make_connector_ref_rconnectorref("link1", "axis")
    connector_b = cad.make_connector_ref_rconnectorref("link2", "axis")
    assembly = cad.add_revolute_constraint_rassembly(
        assembly, "hinge",
        connector_a, connector_b,
        angle_limit=cad.make_scalar_limit_rscalarlimit(0.0, 90.0),
    )
    solved = cad.solve_assembly_constraints_rassembly(assembly, strict=False)
    residual = cad.measure_constraint_residual_rconstraintresidual(solved, "hinge")
    assert residual.within_tolerance


def _signed_z_angle_degrees(placement):
    return math.degrees(math.atan2(placement.x_axis[1], placement.x_axis[0]))


def test_gear_and_belt_constraints_couple_revolute_support_joints():
    part = _part_with_face_connector("coupled_rotor_part")
    base_ref = cad.make_connector_ref_rconnectorref("base", "axis")
    gear_a_ref = cad.make_connector_ref_rconnectorref("gear_a", "axis")
    gear_b_ref = cad.make_connector_ref_rconnectorref("gear_b", "axis")

    gear_assembly = cad.make_assembly_rassembly("gear_coupler_asm")
    for component_id in ("base", "gear_a", "gear_b"):
        gear_assembly = cad.add_component_rassembly(
            gear_assembly,
            part,
            component_id=component_id,
            placement=cad.identity_placement_rplacement(),
        )
    gear_assembly = cad.ground_component_rassembly(gear_assembly, "base")
    gear_assembly = cad.add_revolute_constraint_rassembly(
        gear_assembly, "drive_a", base_ref, gear_a_ref, drive_angle_degrees=90.0,
    )
    gear_assembly = cad.add_revolute_constraint_rassembly(
        gear_assembly, "free_b", base_ref, gear_b_ref,
    )
    gear_assembly = cad.add_gear_constraint_rassembly(
        gear_assembly,
        "mesh",
        gear_a_ref,
        gear_b_ref,
        pitch_radius_a=1.0,
        pitch_radius_b=2.0,
    )
    gear_solved = cad.solve_assembly_constraints_rassembly(gear_assembly)
    assert math.isclose(
        _signed_z_angle_degrees(gear_solved.get_component("gear_b").placement),
        -45.0,
        abs_tol=1e-9,
    )
    assert cad.measure_constraint_residual_rconstraintresidual(
        gear_solved, "mesh"
    ).within_tolerance

    belt_assembly = cad.make_assembly_rassembly("belt_coupler_asm")
    for component_id in ("base", "gear_a", "gear_b"):
        belt_assembly = cad.add_component_rassembly(
            belt_assembly,
            part,
            component_id=component_id,
            placement=cad.identity_placement_rplacement(),
        )
    belt_assembly = cad.ground_component_rassembly(belt_assembly, "base")
    belt_assembly = cad.add_revolute_constraint_rassembly(
        belt_assembly, "drive_a", base_ref, gear_a_ref, drive_angle_degrees=90.0,
    )
    belt_assembly = cad.add_revolute_constraint_rassembly(
        belt_assembly, "free_b", base_ref, gear_b_ref,
    )
    belt_assembly = cad.add_belt_constraint_rassembly(
        belt_assembly,
        "belt",
        gear_a_ref,
        gear_b_ref,
        pulley_radius_a=1.0,
        pulley_radius_b=2.0,
    )
    belt_solved = cad.solve_assembly_constraints_rassembly(belt_assembly)
    assert math.isclose(
        _signed_z_angle_degrees(belt_solved.get_component("gear_b").placement),
        45.0,
        abs_tol=1e-9,
    )
    assert cad.measure_constraint_residual_rconstraintresidual(
        belt_solved, "belt"
    ).within_tolerance


def test_rack_pinion_constraint_couples_prismatic_and_revolute_support_joints():
    part = _part_with_face_connector("rack_pinion_part")
    base_ref = cad.make_connector_ref_rconnectorref("base", "axis")
    rack_ref = cad.make_connector_ref_rconnectorref("rack", "axis")
    pinion_ref = cad.make_connector_ref_rconnectorref("pinion", "axis")
    assembly = cad.make_assembly_rassembly("rack_pinion_asm")
    for component_id in ("base", "rack", "pinion"):
        assembly = cad.add_component_rassembly(
            assembly,
            part,
            component_id=component_id,
            placement=cad.identity_placement_rplacement(),
        )
    assembly = cad.ground_component_rassembly(assembly, "base")
    assembly = cad.add_prismatic_constraint_rassembly(
        assembly, "rack_slide", base_ref, rack_ref,
    )
    assembly = cad.add_revolute_constraint_rassembly(
        assembly, "pinion_axis", base_ref, pinion_ref, drive_angle_degrees=90.0,
    )
    assembly = cad.add_rack_pinion_constraint_rassembly(
        assembly,
        "rack_mesh",
        rack_ref,
        pinion_ref,
        pitch_radius=2.0,
    )

    solved = cad.solve_assembly_constraints_rassembly(assembly)

    assert math.isclose(
        solved.get_component("rack").placement.origin[2],
        -math.pi,
        abs_tol=1e-9,
    )
    assert cad.measure_constraint_residual_rconstraintresidual(
        solved, "rack_mesh"
    ).within_tolerance


def test_coupling_constraints_validate_positive_radii():
    part = _part_with_face_connector("invalid_coupler_part")
    assembly = cad.make_assembly_rassembly("invalid_coupler_asm")
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="a", placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="b", placement=cad.identity_placement_rplacement(),
    )
    ref_a = cad.make_connector_ref_rconnectorref("a", "axis")
    ref_b = cad.make_connector_ref_rconnectorref("b", "axis")

    with pytest.raises(Exception, match="pitch_radius_a"):
        cad.add_gear_constraint_rassembly(
            assembly, "bad_gear", ref_a, ref_b, pitch_radius_a=0.0, pitch_radius_b=1.0,
        )
    with pytest.raises(Exception, match="pulley_radius_b"):
        cad.add_belt_constraint_rassembly(
            assembly, "bad_belt", ref_a, ref_b, pulley_radius_a=1.0, pulley_radius_b=-1.0,
        )
    with pytest.raises(Exception, match="pitch_radius"):
        cad.add_rack_pinion_constraint_rassembly(
            assembly, "bad_rack", ref_a, ref_b, pitch_radius=0.0,
        )


def test_limit_aware_prismatic_loop_finds_optimal_distance():
    part = _part_with_face_connector("ploop_part")
    assembly = cad.make_assembly_rassembly("prism_loop")
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="fixed_part",
        placement=cad.make_placement_rplacement(origin=(0.0, 0.0, 2.0)),
    )
    assembly = cad.add_component_rassembly(
        assembly, part, component_id="movable",
        placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.ground_component_rassembly(assembly, "fixed_part")
    connector_a = cad.make_connector_ref_rconnectorref("fixed_part", "axis")
    connector_b = cad.make_connector_ref_rconnectorref("movable", "axis")
    assembly = cad.add_prismatic_constraint_rassembly(
        assembly, "slide",
        connector_a, connector_b,
        distance_limit=cad.make_scalar_limit_rscalarlimit(-5.0, 5.0),
    )
    solved = cad.solve_assembly_constraints_rassembly(assembly, strict=False)
    residual = cad.measure_constraint_residual_rconstraintresidual(solved, "slide")
    assert residual.within_tolerance
