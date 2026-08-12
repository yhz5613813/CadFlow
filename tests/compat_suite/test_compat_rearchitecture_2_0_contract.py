"""Contract tests for the CadFlow 2.0 rearchitecture.

These tests intentionally focus on stable public behavior and on a small number
of future-facing expression contracts. The future-facing tests are skipped until
the corresponding 2.0 APIs exist.
"""

from __future__ import annotations

import unittest

import cadflow as cad
from cadflow.graph import GraphSession


REQUIRED_GEOMETRY_TYPES = (
    "Vertex",
    "Edge",
    "Wire",
    "Face",
    "Solid",
)


REQUIRED_RSTYLE_APIS = (
    "make_point_rvertex",
    "make_line_redge",
    "make_rectangle_rface",
    "make_box_rsolid",
    "make_cylinder_rsolid",
    "extrude_rsolid",
    "revolve_rsolid",
    "fillet_rsolid",
    "chamfer_rsolid",
    "shell_rsolid",
    "cut_rsolid",
    "union_rsolid",
    "intersect_rsolid",
)


class TestRearchitecture20ApiContracts(unittest.TestCase):
    """Contracts derived from REQ-API-* in the 2.0 requirements doc."""

    def test_shape_first_geometry_types_remain_public(self):
        for type_name in REQUIRED_GEOMETRY_TYPES:
            with self.subTest(type_name=type_name):
                self.assertTrue(hasattr(cad, type_name))

    def test_rstyle_modeling_api_remains_public(self):
        for name in REQUIRED_RSTYLE_APIS:
            with self.subTest(name=name):
                self.assertTrue(hasattr(cad, name))

    def test_constant_only_modeling_requires_no_expression_wrapper(self):
        box = cad.make_box_rsolid(4.0, 5.0, 6.0)
        self.assertIsInstance(box, cad.Solid)
        self.assertGreater(box.get_volume(), 0.0)

    def test_shape_operations_remain_type_closed_for_core_workflow(self):
        face = cad.make_rectangle_rface(2.0, 1.0)
        self.assertIsInstance(face, cad.Face)

        solid = cad.extrude_rsolid(face, (0, 0, 1), 3.0)
        self.assertIsInstance(solid, cad.Solid)

        moved = cad.translate_shape(solid, (1.0, 2.0, 3.0))
        self.assertIsInstance(moved, cad.Solid)

        rotated = cad.rotate_shape(moved, 30.0, (0, 0, 1))
        self.assertIsInstance(rotated, cad.Solid)

    def test_boolean_pipeline_keeps_returning_solids(self):
        body = cad.make_box_rsolid(4.0, 4.0, 4.0)
        tool = cad.make_cylinder_rsolid(0.75, 6.0, bottom_face_center=(0.0, 0.0, -1.0))

        result = cad.cut_rsolid(body, tool)
        self.assertIsInstance(result, cad.Solid)


class TestRearchitecture20ExpressionContracts(unittest.TestCase):
    """Future contracts derived from REQ-EXPR-* in the 2.0 requirements doc."""

    def test_explicit_variable_api_exists(self):
        var = cad.var("r", 10.0)
        self.assertIsNotNone(var)
        self.assertIsInstance(var, cad.Var)

    def test_variable_name_is_explicit_and_preserved(self):
        var = cad.var("radius", 10.0)
        self.assertEqual(var.name, "radius")

    def test_expression_supports_standard_arithmetic(self):
        r = cad.var("r", 10.0)
        expr = ((r + 2) * 3 - 4) / 2
        self.assertIsInstance(expr, cad.Expr)
        self.assertAlmostEqual(float(expr), 16.0)

    def test_expression_system_preserves_legacy_unitless_variables(self):
        r = cad.var("r", 10.0)
        self.assertIsNone(r.unit)
        self.assertIsNone(r.tolerance_unit)
        self.assertIsNone(cad.infer_dimension(r))
        self.assertEqual(r.evaluate(), 10.0)

    def test_expression_values_can_flow_into_public_modeling_apis(self):
        r = cad.var("r", 10.0)
        face = cad.make_circle_rface((0, 0, 0), r)
        self.assertIsInstance(face, cad.Face)

        solid = cad.extrude_rsolid(face, (0, 0, 1), r * 2)
        self.assertIsInstance(solid, cad.Solid)

    def test_expression_graph_is_public_and_round_trippable(self):
        graph = cad.ExpressionGraph()
        r = cad.var("r", 10.0)
        graph.register(r * 2 + 1)

        payload = graph.to_dict()
        rebuilt = cad.ExpressionGraph.from_dict(payload)

        self.assertGreaterEqual(rebuilt.node_count, 4)
        expr_nodes = [node for node in payload["nodes"] if node["kind"] == "expr"]
        self.assertGreaterEqual(len(expr_nodes), 2)

    def test_graph_session_tracks_expression_graph_separately(self):
        r = cad.var("r", 5.0)
        with GraphSession() as session:
            face = cad.make_circle_rface((0, 0, 0), r)
            solid = cad.extrude_rsolid(face, (0, 0, 1), r * 2)

        self.assertIsInstance(solid, cad.Solid)
        self.assertGreaterEqual(session.graph.node_count, 2)
        self.assertGreaterEqual(session.expression_graph.node_count, 3)

        leaf = session.graph.leaf_nodes()[0]
        self.assertIn("distance", leaf.param_exprs)
        self.assertIn("expr_id", leaf.param_exprs["distance"])

    def test_session_export_includes_expression_graph(self):
        r = cad.var("r", 3.0)
        with GraphSession() as session:
            cad.make_circle_rface((0, 0, 0), r)

        payload = cad.import_session_json(cad.export_session_json(session))
        self.assertIn("graph", payload)
        self.assertIn("expression_graph", payload)
        self.assertGreaterEqual(payload["expression_graph"].node_count, 1)


class TestRearchitecture20GeometryContracts(unittest.TestCase):
    def test_geometry_layer_remains_shape_first_not_scene_graph_first(self):
        box = cad.make_box_rsolid(1.0, 2.0, 3.0)
        self.assertFalse(hasattr(box, "children_nodes"))
        self.assertFalse(hasattr(box, "scene_transform"))

    def test_sketch_can_exist_without_replacing_shape_hierarchy(self):
        self.assertTrue(hasattr(cad, "Sketch"))
        self.assertTrue(hasattr(cad, "Face"))
        self.assertTrue(hasattr(cad, "Solid"))
        sketch = cad.Sketch()
        self.assertIsInstance(sketch, cad.Sketch)


class TestRearchitecture20KernelContracts(unittest.TestCase):
    def test_geometry_wrappers_accept_raw_occ_shapes_and_expose_wrapped_storage(self):
        solid = cad.make_box_rsolid(1.0, 2.0, 3.0)
        clone = cad.Solid(solid.wrapped)
        self.assertIsInstance(clone, cad.Solid)
        self.assertTrue(hasattr(clone, "wrapped"))
        self.assertFalse(hasattr(clone, "cq_solid"))

    def test_public_modeling_path_produces_wrapped_storage_on_shapes(self):
        face = cad.make_circle_rface((0, 0, 0), 2.0)
        solid = cad.extrude_rsolid(face, (0, 0, 1), 3.0)
        self.assertTrue(hasattr(face, "wrapped"))
        self.assertTrue(hasattr(solid, "wrapped"))


class TestRearchitecture20HistoryContracts(unittest.TestCase):
    def test_operation_graph_is_still_recorded_for_public_modeling_calls(self):
        with GraphSession() as session:
            body = cad.make_box_rsolid(4.0, 4.0, 4.0)
            tool = cad.make_cylinder_rsolid(
                0.75, 6.0, bottom_face_center=(0.0, 0.0, -1.0)
            )
            result = cad.cut_rsolid(body, tool)
            payload = cad.import_model_json(cad.export_model_json(session))

        self.assertIsInstance(result, cad.Solid)
        self.assertGreaterEqual(session.graph.node_count, 3)
        allowed_ops = set(payload["canonical_contract"]["core_op_set"])
        self.assertTrue(all(node.op in allowed_ops for node in session.graph.nodes))

    def test_semantic_delta_exists_alongside_topology_delta(self):
        delta = cad.SemanticDelta()
        self.assertTrue(hasattr(delta, "created"))
        self.assertTrue(hasattr(delta, "modified"))
        self.assertTrue(hasattr(delta, "deleted"))

    def test_topology_delta_types_still_exposed_in_data_model(self):
        from cadflow.topology import TopoDelta

        delta = TopoDelta()
        self.assertTrue(hasattr(delta, "preserved"))
        self.assertTrue(hasattr(delta, "modified"))
        self.assertTrue(hasattr(delta, "generated"))
        self.assertTrue(hasattr(delta, "deleted"))

    def test_semantic_ref_exists_beside_topo_ref(self):
        ref = cad.SemanticRef(
            graph_id="g0", node_id="n0", entity_type="Sketch", entity_id="sk0"
        )
        self.assertEqual(ref.entity_type, "Sketch")


class TestRearchitecture20AssemblyContracts(unittest.TestCase):
    def test_single_body_part_assembly_mvp_public_surface_is_exposed(self):
        self.assertTrue(hasattr(cad, "Assembly"))
        self.assertTrue(hasattr(cad, "Part"))
        self.assertTrue(hasattr(cad, "Material"))
        self.assertTrue(hasattr(cad, "Placement"))
        self.assertTrue(hasattr(cad, "make_assembly_rassembly"))
        self.assertTrue(hasattr(cad, "make_part_rpart"))
        self.assertTrue(hasattr(cad, "make_material_rmaterial"))
        self.assertTrue(hasattr(cad, "make_placement_rplacement"))
        self.assertTrue(hasattr(cad, "add_component_rassembly"))
        self.assertTrue(hasattr(cad, "place_component_rassembly"))
        self.assertTrue(hasattr(cad, "make_compound_from_assembly_rcompound"))
        self.assertFalse(hasattr(cad, "PartHandle"))
        self.assertFalse(hasattr(cad, "PointAnchor"))
        self.assertFalse(hasattr(cad, "AxisAnchor"))
        self.assertFalse(hasattr(cad, "AssemblyResult"))
        self.assertFalse(hasattr(cad, "SolveReport"))
        self.assertFalse(hasattr(cad, "clone_assembly_rassembly"))
        self.assertFalse(hasattr(cad, "add_part_rassembly"))
        self.assertFalse(hasattr(cad, "translate_part_rassembly"))
        self.assertFalse(hasattr(cad, "rotate_part_rassembly"))
        self.assertFalse(hasattr(cad, "solve_assembly_rresult"))
        self.assertFalse(hasattr(cad, "constrain_offset_rassembly"))
        self.assertFalse(hasattr(cad, "constrain_concentric_rassembly"))
        self.assertFalse(hasattr(cad, "constrain_distance_rassembly"))
        self.assertFalse(hasattr(cad, "stack_rassembly"))

    def test_model_json_export_has_no_assembly_keyword(self):
        with GraphSession() as session:
            cad.make_box_rsolid(1.0, 1.0, 1.0)

        with self.assertRaises(TypeError):
            cad.export_model_json(session, assembly=object())


class TestRearchitecture20IoContracts(unittest.TestCase):
    def test_session_export_becomes_canonical_json_seed(self):
        r = cad.var("r", 2.0)
        with GraphSession() as session:
            cad.make_circle_rface((0, 0, 0), r)

        payload = cad.import_session_json(cad.export_session_json(session))
        self.assertGreaterEqual(payload["graph"].node_count, 1)
        self.assertGreaterEqual(payload["expression_graph"].node_count, 1)

    def test_step_export_still_exists_as_final_geometry_export(self):
        self.assertTrue(hasattr(cad, "export_step"))
        self.assertTrue(hasattr(cad, "export_stl"))

    def test_model_json_export_exists_as_canonical_seed(self):
        r = cad.var("r", 2.0)
        with GraphSession() as session:
            cad.make_circle_rface((0, 0, 0), r)

        payload = cad.import_model_json(cad.export_model_json(session))
        self.assertIn("graph", payload)
        self.assertIn("expression_graph", payload)

    def test_model_json_declares_final_state_canonical_contract(self):
        with GraphSession() as session:
            cad.make_box_rsolid(1.0, 2.0, 3.0)

        payload = cad.import_model_json(cad.export_model_json(session))

        self.assertIn("canonical_contract", payload)
        contract = payload["canonical_contract"]
        self.assertEqual(contract["contract_version"], "2.0")
        self.assertEqual(contract["graph_roles"]["graph"], "canonical_low_level_graph")
        self.assertEqual(contract["graph_roles"]["leaf_ids"], "explicit_result_set")
        self.assertEqual(contract["replay_policy"]["preferred_graph"], "graph")
        self.assertEqual(contract["replay_policy"]["default_mode"], "strict")
        self.assertEqual(
            contract["replay_policy"]["permissive_mode"], "explicit_opt_in"
        )

    def test_model_json_declares_selection_ref_resolution_order(self):
        with GraphSession() as session:
            box = cad.make_box_rsolid(4.0, 4.0, 4.0)
            cad.fillet_rsolid(box, [box.get_edges(i) for i in range(2)], 0.2)

        payload = cad.import_model_json(cad.export_model_json(session))
        selection_schema = payload["canonical_contract"]["selection_ref_schema"]

        self.assertEqual(
            selection_schema["replay_resolution_order"],
            [
                "geo_select_nodes",
                "selection_query",
                "explicit_topo_refs",
                "stable_indices",
                "selector_hint",
            ],
        )
