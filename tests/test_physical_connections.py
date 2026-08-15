from __future__ import annotations

import json

import pytest

import cadflow as cad


def _part(part_id: str, connector_id: str = "joint") -> cad.Part:
    body = cad.make_box_rsolid(10.0, 10.0, 10.0)
    part = cad.make_part_rpart(part_id, body)
    connector = cad.make_placement_connector_rconnector(
        connector_id,
        cad.identity_placement_rplacement(),
    )
    return cad.add_connector_rpart(part, connector)


def _assembly() -> tuple[cad.Assembly, cad.ConnectorRef, cad.ConnectorRef]:
    identity = cad.identity_placement_rplacement()
    assembly = cad.make_assembly_rassembly("wood_frame")
    assembly = cad.add_component_rassembly(
        assembly, _part("rail"), "rail", identity
    )
    assembly = cad.add_component_rassembly(
        assembly, _part("stile"), "stile", identity
    )
    assembly = cad.ground_component_rassembly(assembly, "rail")
    connector_a = cad.make_connector_ref_rconnectorref("rail", "joint")
    connector_b = cad.make_connector_ref_rconnectorref("stile", "joint")
    assembly = cad.add_fixed_constraint_rassembly(
        assembly,
        "joint_fixed",
        connector_a,
        connector_b,
    )
    return assembly, connector_a, connector_b


def _tenon_connection(
    connector_a: cad.ConnectorRef,
    connector_b: cad.ConnectorRef,
    *,
    behavior: cad.ConnectionBehavior | None = None,
) -> cad.PhysicalConnection:
    return cad.make_physical_connection_rphysicalconnection(
        connection_id="main_tenon",
        connection_kind=cad.PhysicalConnectionKind.MORTISE_TENON,
        connector_a=connector_a,
        connector_b=connector_b,
        behavior=behavior,
        insertion_direction=(1.0, 0.0, 0.0),
        kinematic_constraint_id="joint_fixed",
        metadata={"fit_class": "sliding"},
    )


def test_physical_connection_layer_is_separate_and_queryable() -> None:
    assembly, connector_a, connector_b = _assembly()
    layer = cad.make_physical_connection_layer_rphysicalconnectionlayer(assembly)
    connection = _tenon_connection(connector_a, connector_b)
    layer = cad.add_physical_connection_rphysicalconnectionlayer(layer, connection)

    assert assembly.constraint_ids() == ("joint_fixed",)
    assert not hasattr(assembly, "physical_connections")
    assert layer.connection_ids() == ("main_tenon",)
    assert layer.get_connection("main_tenon").connection_kind == "mortise_tenon"
    assert layer.connections_for_component("rail") == (connection,)
    assert layer.connections_between("rail", "stile") == (connection,)
    assert connection.behavior.response_mode == "bonded"

    removed = cad.remove_physical_connection_rphysicalconnectionlayer(
        layer, "main_tenon"
    )
    assert removed.connection_ids() == ()
    assert assembly.constraint_ids() == ("joint_fixed",)


def test_connection_regions_and_json_round_trip(tmp_path) -> None:
    assembly, connector_a, connector_b = _assembly()
    geometry_ref = cad.GeometryRef(
        kind="face",
        source_node_id="tenon_node",
        geo_selector={"selector": "tag", "tag": "role.tenon.cheek"},
    )
    region = cad.make_connection_region_rconnectionregion(
        region_id="tenon_cheek",
        component_id="rail",
        geometry_ref=geometry_ref,
        role="contact",
        metadata={"surface": "side"},
    )
    connection = cad.make_physical_connection_rphysicalconnection(
        connection_id="main_tenon",
        connection_kind="mortise_tenon",
        connector_a=connector_a,
        connector_b=connector_b,
        behavior=cad.make_connection_behavior_rconnectionbehavior(
            response_mode="frictional_contact",
            normal_stiffness=1000.0,
            tangential_stiffness=250.0,
            friction_coefficient=0.35,
            clearance=0.02,
        ),
        regions=(region,),
        insertion_direction=(1.0, 0.0, 0.0),
        kinematic_constraint_id="joint_fixed",
        name="Main rail mortise and tenon",
    )
    layer = cad.add_physical_connection_rphysicalconnectionlayer(
        cad.make_physical_connection_layer_rphysicalconnectionlayer(
            assembly,
            metadata={"source": "design"},
        ),
        connection,
    )

    compact = layer.to_json()
    replayed = cad.PhysicalConnectionLayer.from_json(compact)
    assert replayed == layer
    assert json.loads(compact)["schema_version"] == "1.0"
    assert replayed.get_connection("main_tenon").regions[0].geometry_ref.kind == "face"

    output = tmp_path / "wood_frame.physical-connections.json"
    assert cad.export_physical_connection_layer_json_rpath(layer, output) == output
    loaded = cad.import_physical_connection_layer_json_rphysicalconnectionlayer(output)
    assert loaded == layer


def test_layer_validation_checks_assembly_references_and_semantics() -> None:
    assembly, connector_a, connector_b = _assembly()
    valid_layer = cad.add_physical_connection_rphysicalconnectionlayer(
        cad.make_physical_connection_layer_rphysicalconnectionlayer(assembly),
        _tenon_connection(
            connector_a,
            connector_b,
            behavior=cad.make_connection_behavior_rconnectionbehavior(
                response_mode="bonded",
                normal_stiffness=1000.0,
            ),
        ),
    )
    report = cad.validate_physical_connection_layer_rphysicalconnectionvalidationreport(
        valid_layer, assembly
    )
    assert report.valid
    assert report.issues == ()

    missing_connector = cad.make_physical_connection_rphysicalconnection(
        connection_id="bad_joint",
        connection_kind="press_fit",
        connector_a=cad.make_connector_ref_rconnectorref("rail", "missing"),
        connector_b=connector_b,
    )
    invalid_layer = cad.add_physical_connection_rphysicalconnectionlayer(
        cad.make_physical_connection_layer_rphysicalconnectionlayer("wrong_assembly"),
        missing_connector,
    )
    report = cad.validate_physical_connection_layer_rphysicalconnectionvalidationreport(
        invalid_layer, assembly
    )
    assert not report.valid
    assert {issue.code for issue in report.errors} == {
        "assembly_id_mismatch",
        "connector_missing",
    }
    assert {
        "response_not_parameterized",
        "press_fit_interference_missing",
        "contact_stiffness_missing",
        "insertion_direction_missing",
    } <= {issue.code for issue in report.warnings}
    with pytest.raises(ValueError, match="does not match"):
        report.raise_for_errors()


def test_native_bonded_response_and_failure_utilization() -> None:
    assembly, connector_a, connector_b = _assembly()
    behavior = cad.make_connection_behavior_rconnectionbehavior(
        response_mode="bonded",
        normal_stiffness=1000.0,
        tangential_stiffness=500.0,
        rotational_stiffness=100.0,
        normal_damping=10.0,
        tangential_damping=5.0,
        rotational_damping=2.0,
        tensile_limit=50.0,
        shear_limit=20.0,
        torque_limit=5.0,
    )
    layer = cad.add_physical_connection_rphysicalconnectionlayer(
        cad.make_physical_connection_layer_rphysicalconnectionlayer(assembly),
        _tenon_connection(connector_a, connector_b, behavior=behavior),
    )
    state = cad.PhysicalConnectionState(
        "main_tenon",
        relative_translation=(0.1, 0.1, 0.0),
        relative_rotation=(0.0, 0.0, 0.1),
        relative_linear_velocity=(0.2, 0.2, 0.0),
        relative_angular_velocity=(0.0, 0.0, 0.5),
    )

    batch = cad.evaluate_physical_connections_rphysicalconnectionresponsebatch(
        layer, (state,)
    )
    response = batch.responses[0]
    assert batch.backend == "native_cpp"
    assert response.force == pytest.approx((-102.0, -51.0, 0.0))
    assert response.torque == pytest.approx((0.0, 0.0, -11.0))
    assert response.normal_force == pytest.approx(-102.0)
    assert response.shear_force == pytest.approx(51.0)
    assert response.tensile_utilization == pytest.approx(2.04)
    assert response.shear_utilization == pytest.approx(2.55)
    assert response.torque_utilization == pytest.approx(2.2)
    assert response.active
    assert response.failed


def test_native_frictional_contact_caps_shear_and_opens() -> None:
    assembly, connector_a, connector_b = _assembly()
    behavior = cad.make_connection_behavior_rconnectionbehavior(
        response_mode="interference",
        normal_stiffness=100.0,
        tangential_stiffness=50.0,
        friction_coefficient=0.5,
        interference=0.1,
    )
    connection = cad.make_physical_connection_rphysicalconnection(
        connection_id="fitted_tenon",
        connection_kind="press_fit",
        connector_a=connector_a,
        connector_b=connector_b,
        behavior=behavior,
        insertion_direction=(0.0, 0.0, 1.0),
    )
    layer = cad.add_physical_connection_rphysicalconnectionlayer(
        cad.make_physical_connection_layer_rphysicalconnectionlayer(assembly),
        connection,
    )
    closed = cad.PhysicalConnectionState(
        "fitted_tenon", relative_translation=(1.0, 0.0, 0.0)
    )
    opened = cad.PhysicalConnectionState(
        "fitted_tenon", relative_translation=(1.0, 0.0, 0.2)
    )

    closed_response = cad.evaluate_physical_connections_rphysicalconnectionresponsebatch(
        layer, (closed,)
    ).responses[0]
    opened_response = cad.evaluate_physical_connections_rphysicalconnectionresponsebatch(
        layer, (opened,)
    ).responses[0]

    assert closed_response.force == pytest.approx((-5.0, 0.0, 10.0))
    assert closed_response.normal_force == pytest.approx(10.0)
    assert closed_response.shear_force == pytest.approx(5.0)
    assert closed_response.active
    assert opened_response.force == pytest.approx((0.0, 0.0, 0.0))
    assert not opened_response.active


def test_physical_connection_input_validation() -> None:
    _, connector_a, connector_b = _assembly()
    with pytest.raises(ValueError, match="cannot both"):
        cad.make_connection_behavior_rconnectionbehavior(
            response_mode="interference", clearance=0.1, interference=0.1
        )
    with pytest.raises(ValueError, match="non-zero"):
        cad.make_physical_connection_rphysicalconnection(
            connection_id="bad_axis",
            connection_kind="mortise_tenon",
            connector_a=connector_a,
            connector_b=connector_b,
            insertion_direction=(0.0, 0.0, 0.0),
        )
    with pytest.raises(ValueError, match="one entry"):
        layer = cad.add_physical_connection_rphysicalconnectionlayer(
            cad.make_physical_connection_layer_rphysicalconnectionlayer("wood_frame"),
            _tenon_connection(connector_a, connector_b),
        )
        state = cad.PhysicalConnectionState("main_tenon")
        cad.evaluate_physical_connections_rphysicalconnectionresponsebatch(
            layer, (state, state)
        )
    with pytest.raises(ValueError, match="schema_version"):
        cad.PhysicalConnectionLayer.from_json(
            '{"schema_version":"2.0","assembly_id":"x","units":{}}'
        )


def test_empty_native_batch_is_well_defined() -> None:
    layer = cad.make_physical_connection_layer_rphysicalconnectionlayer("empty_assembly")
    batch = cad.evaluate_physical_connections_rphysicalconnectionresponsebatch(layer, ())
    assert batch.backend == "native_cpp"
    assert batch.responses == ()
