"""TDD coverage for remaining primitive/transform expression integration."""

from __future__ import annotations

import unittest

import cadflow as cad
from cadflow.graph import GraphSession


class TestRemainingPrimitiveExpressionSupport(unittest.TestCase):
    def test_cone_accepts_expression_parameters(self):
        r = cad.var("br", 2.0)
        h = cad.var("h", 5.0)
        solid = cad.make_cone_rsolid(r, h, top_radius=r / 2)
        self.assertIsInstance(solid, cad.Solid)

    def test_sphere_accepts_expression_radius_and_center(self):
        r = cad.var("sr", 2.0)
        x = cad.var("sx", 1.0)
        solid = cad.make_sphere_rsolid(r, center=(x, 0.0, 0.0))
        self.assertIsInstance(solid, cad.Solid)

    def test_three_point_arc_accepts_expression_points(self):
        x = cad.var("ax", 1.0)
        edge = cad.make_three_point_arc_redge(
            (0.0, 0.0, 0.0), (x, 1.0, 0.0), (2.0, 0.0, 0.0)
        )
        self.assertIsInstance(edge, cad.Edge)

    def test_angle_arc_accepts_expression_radius_and_angles(self):
        r = cad.var("ar", 2.0)
        start = cad.var("a0", 0.0)
        end = cad.var("a1", 1.57)
        edge = cad.make_angle_arc_redge((0.0, 0.0, 0.0), r, start, end)
        self.assertIsInstance(edge, cad.Edge)

    def test_spline_accepts_expression_points(self):
        y = cad.var("sy", 1.0)
        edge = cad.make_spline_redge(
            control_points=[
                (0.0, 0.0, 0.0),
                (0.6, y, 0.0),
                (1.4, y, 0.0),
                (2.0, 0.0, 0.0),
            ]
        )
        self.assertIsInstance(edge, cad.Edge)


class TestRemainingTransformExpressionSupport(unittest.TestCase):
    def test_translate_accepts_expression_vector(self):
        dx = cad.var("dx", 1.0)
        box = cad.make_box_rsolid(1.0, 1.0, 1.0)
        moved = cad.translate_shape(box, (dx, 0.0, 0.0))
        self.assertIsInstance(moved, cad.Solid)

    def test_rotate_accepts_expression_angle_and_axis(self):
        angle = cad.var("rot", 30.0)
        box = cad.make_box_rsolid(1.0, 1.0, 1.0)
        moved = cad.rotate_shape(box, angle, (0.0, 0.0, 1.0))
        self.assertIsInstance(moved, cad.Solid)

    def test_mirror_accepts_expression_plane_origin(self):
        x = cad.var("mx", 0.0)
        box = cad.make_box_rsolid(1.0, 1.0, 1.0)
        mirrored = cad.mirror_shape(box, (x, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertIsInstance(mirrored, cad.Solid)


class TestSemanticDeltaProduction(unittest.TestCase):
    def test_operation_nodes_can_carry_semantic_delta_for_primitives(self):
        with GraphSession() as session:
            cad.make_box_rsolid(1.0, 1.0, 1.0)

        leaf = session.graph.leaf_nodes()[0]
        self.assertIsNotNone(leaf.semantic_delta)
        self.assertGreaterEqual(len(leaf.semantic_delta.created), 1)


if __name__ == "__main__":
    unittest.main()
