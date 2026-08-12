from __future__ import annotations

import json
import math

import pytest
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt

import cadflow as cad
from cadflow.graph import GraphSession


def _profile(z: float, radius: float, count: int = 12):
    return [
        (
            radius * math.cos(2.0 * math.pi * index / count),
            radius * math.sin(2.0 * math.pi * index / count),
            z,
        )
        for index in range(count)
    ]


def test_periodic_interpolated_wire_is_closed_and_passes_through_points():
    points = _profile(0.0, 2.0, count=10)

    wire = cad.make_periodic_spline_rwire(points=points + [points[0]])

    assert wire.is_closed()
    assert len(wire.get_edges()) == 1
    edge = wire.get_edges(0)
    for point in points:
        distance = BRepExtrema_DistShapeShape(
            BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex(),
            edge.wrapped,
        )
        distance.Perform()
        assert distance.IsDone()
        assert distance.Value() <= 1.0e-6


def test_interpolated_spline_graph_replays_the_same_wire():
    points = _profile(0.0, 1.5, count=8)
    with GraphSession() as session:
        wire = cad.make_interpolated_spline_rwire(
            points=points,
            periodic=True,
            tolerance=1.0e-7,
        )
        session.capture_result(value=wire)

    payload = json.loads(cad.export_model_json(session))
    operations = [node["op"] for node in payload["graph"]["nodes"]]
    assert "make_interpolated_spline_redge" in operations
    assert "make_wire_from_edges_rwire" in operations

    replayed = cad.replay_model_json(json.dumps(payload))[0]
    assert isinstance(replayed, cad.Wire)
    assert replayed.is_closed()
    assert replayed.get_edges(0).get_length() == pytest.approx(
        wire.get_edges(0).get_length(),
        rel=1.0e-9,
    )


def test_interpolated_spline_graph_preserves_parameter_expressions():
    x = cad.var("spline_x", 1.0)
    tolerance = cad.var("spline_tolerance", 1.0e-7)
    with GraphSession() as session:
        edge = cad.make_interpolated_spline_redge(
            points=[(0.0, 0.0, 0.0), (x, 1.0, 0.0), (2.0, 0.0, 0.0)],
            tolerance=tolerance,
        )
        session.capture_result(value=edge)

    node = next(
        node
        for node in session.graph.nodes
        if node.op == "make_interpolated_spline_redge"
    )
    assert set(node.param_exprs) == {"points", "tolerance"}

    replayed = cad.replay_model_json(cad.export_model_json(session))[0]
    assert isinstance(replayed, cad.Edge)
    assert replayed.get_length() == pytest.approx(edge.get_length(), rel=1.0e-9)


def test_periodic_profile_loft_records_and_replays():
    with GraphSession() as session:
        profiles = [
            cad.make_periodic_spline_rwire(points=_profile(0.0, 2.0)),
            cad.make_periodic_spline_rwire(points=_profile(1.0, 1.6)),
            cad.make_periodic_spline_rwire(points=_profile(2.0, 1.0)),
        ]
        solid = cad.loft_rsolid(
            profiles,
            tracking_policy=cad.TrackingPolicy.GRAPH,
        )
        session.capture_result(value=solid)

    loft = next(node for node in session.graph.nodes if node.op == "make_loft_rsolid")
    assert loft.params == {
        "profile_count": 3,
        "ruled": False,
        "tracking_policy": "graph",
    }

    replayed = cad.replay_model_json(cad.export_model_json(session))[0]
    assert isinstance(replayed, cad.Solid)
    assert replayed.get_volume() == pytest.approx(solid.get_volume(), rel=1.0e-8)
