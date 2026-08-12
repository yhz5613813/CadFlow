"""TDD coverage for remaining Phase 1 expressionized primitive/profile APIs."""

from __future__ import annotations

import unittest

import cadflow as cad
from cadflow.graph import GraphSession


class TestRemainingPrimitiveProfileExpressionSupport(unittest.TestCase):
    def test_point_accepts_expression_coordinates_and_records_param_exprs(self):
        x = cad.var("px", 1.0)
        y = cad.var("py", 2.0)

        with GraphSession() as session:
            point = cad.make_point_rvertex(x, y, 3.0)

        self.assertIsInstance(point, cad.Vertex)
        leaf = session.graph.leaf_nodes()[0]
        self.assertIn("x", leaf.param_exprs)
        self.assertIn("y", leaf.param_exprs)

    def test_line_accepts_expression_points_and_records_param_exprs(self):
        x = cad.var("lx", 2.0)

        with GraphSession() as session:
            edge = cad.make_line_redge((0.0, 0.0, 0.0), (x, 0.0, 0.0))

        self.assertIsInstance(edge, cad.Edge)
        leaf = session.graph.leaf_nodes()[0]
        self.assertIn("end", leaf.param_exprs)

    def test_rectangle_wire_accepts_expression_dimensions_and_records_param_exprs(self):
        w = cad.var("rw", 3.0)
        h = cad.var("rh", 2.0)

        with GraphSession() as session:
            wire = cad.make_rectangle_rwire(w, h)

        self.assertIsInstance(wire, cad.Wire)
        ops = session.graph.topological_order()
        self.assertTrue(any(node.op == "make_line_redge" for node in ops))
        self.assertTrue(any(node.op == "make_wire_from_edges_rwire" for node in ops))
        line_nodes = [node for node in ops if node.op == "make_line_redge"]
        self.assertTrue(
            any(
                "start" in node.param_exprs or "end" in node.param_exprs
                for node in line_nodes
            )
        )

    def test_polyline_accepts_expression_points_and_records_param_exprs(self):
        y = cad.var("ply", 1.0)

        with GraphSession() as session:
            wire = cad.make_polyline_rwire(
                [(0.0, 0.0, 0.0), (1.0, y, 0.0), (2.0, 0.0, 0.0)],
                closed=False,
            )

        self.assertIsInstance(wire, cad.Wire)
        ops = session.graph.topological_order()
        line_nodes = [node for node in ops if node.op == "make_line_redge"]
        self.assertGreaterEqual(len(line_nodes), 2)
        self.assertTrue(
            any(
                "start" in node.param_exprs or "end" in node.param_exprs
                for node in line_nodes
            )
        )


if __name__ == "__main__":
    unittest.main()
