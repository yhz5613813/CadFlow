"""Complete coverage for physical units and dimensional expression inference."""

from __future__ import annotations

import json
import math
import unittest

import cadflow as cad
from cadflow.units import _infer, unit_to_payload


class TestDimensionsAndUnits(unittest.TestCase):
    def test_named_dimensions_and_dimension_algebra(self):
        self.assertEqual(cad.DIMENSIONLESS.name, "Dimensionless")
        self.assertEqual(cad.LENGTH.name, "Length")
        self.assertEqual(cad.AREA.name, "Area")
        self.assertEqual(cad.VOLUME.name, "Volume")
        self.assertEqual(cad.ANGLE.name, "Angle")
        self.assertEqual(cad.LENGTH.multiply(cad.LENGTH), cad.AREA)
        self.assertEqual(cad.VOLUME.divide(cad.LENGTH), cad.AREA)
        self.assertEqual(cad.LENGTH.power(3), cad.VOLUME)
        self.assertEqual(cad.AREA.square_root(), cad.LENGTH)
        self.assertEqual(cad.Dimension(length=-1, angle=2).symbol, "L^-1 A^2")
        self.assertTrue(cad.DIMENSIONLESS.is_dimensionless)
        self.assertTrue(cad.LENGTH.is_design_dimension)
        self.assertTrue(cad.ANGLE.is_design_dimension)
        self.assertFalse(cad.AREA.is_design_dimension)

    def test_dimension_serialization_and_validation(self):
        self.assertEqual(
            cad.Dimension.from_dict(cad.VOLUME.to_dict()), cad.VOLUME
        )
        invalid = [
            None,
            {},
            {"length": 1},
            {"length": True, "angle": 0},
            {"length": 1, "angle": 0.5},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(
                (TypeError, ValueError)
            ):
                cad.Dimension.from_dict(payload)
        with self.assertRaises(TypeError):
            cad.LENGTH.power(0.5)
        with self.assertRaises(cad.UnitValidationError):
            cad.LENGTH.square_root()

    def test_every_registered_unit_converts_to_canonical_units(self):
        conversions = [
            (cad.MM, 1.0),
            (cad.CM, 10.0),
            (cad.M, 1000.0),
            (cad.INCH, 25.4),
            (cad.FOOT, 304.8),
            (cad.DEGREE, 1.0),
            (cad.RADIAN, 180.0 / math.pi),
            (cad.ONE, 1.0),
            (cad.PERCENT, 0.01),
            (cad.SQUARE_MM, 1.0),
            (cad.SQUARE_CM, 100.0),
            (cad.SQUARE_M, 1_000_000.0),
            (cad.SQUARE_INCH, 25.4**2),
            (cad.SQUARE_FOOT, 304.8**2),
            (cad.CUBIC_MM, 1.0),
            (cad.CUBIC_CM, 1000.0),
            (cad.CUBIC_M, 1_000_000_000.0),
            (cad.CUBIC_INCH, 25.4**3),
            (cad.CUBIC_FOOT, 304.8**3),
        ]
        for unit, expected in conversions:
            with self.subTest(unit=unit.symbol):
                self.assertAlmostEqual(unit.to_canonical(1.0), expected)
                self.assertAlmostEqual(unit.from_canonical(expected), 1.0)
                self.assertIs(cad.get_unit(unit), unit)
                self.assertEqual(cad.get_unit(unit.symbol), unit)
                self.assertEqual(
                    cad.canonical_unit_for_dimension(unit.dimension).dimension,
                    unit.dimension,
                )

    def test_unit_aliases_and_conversion(self):
        aliases = {
            "millimeters": cad.MM,
            "centimeter": cad.CM,
            "meters": cad.M,
            "inches": cad.INCH,
            "feet": cad.FOOT,
            "degrees": cad.DEGREE,
            "radians": cad.RADIAN,
            "percent": cad.PERCENT,
            "square feet": cad.SQUARE_FOOT,
            "cubic inches": cad.CUBIC_INCH,
            "ml": cad.CUBIC_CM,
        }
        for alias, unit in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(cad.get_unit(alias), unit)
        self.assertAlmostEqual(cad.convert_value(1.0, "in", "mm"), 25.4)
        self.assertAlmostEqual(cad.convert_value(180.0, "deg", "rad"), math.pi)
        self.assertAlmostEqual(cad.convert_value(1.0, "ft^2", "in^2"), 144.0)
        with self.assertRaises(cad.UnitValidationError):
            cad.convert_value(1.0, "mm", "deg")
        with self.assertRaisesRegex(ValueError, "Unknown unit"):
            cad.get_unit("parsec")

    def test_unit_validation_and_custom_unit_roundtrip(self):
        invalid_calls = [
            lambda: cad.Unit("", cad.LENGTH, 1.0),
            lambda: cad.Unit("bad", "Length", 1.0),
            lambda: cad.Unit("bad", cad.LENGTH, True),
            lambda: cad.Unit("bad", cad.LENGTH, 0.0),
            lambda: cad.Unit("bad", cad.LENGTH, math.inf),
            lambda: cad.MM.to_canonical(math.inf),
            lambda: cad.MM.to_canonical(True),
            lambda: cad.M.to_canonical(1e308),
            lambda: cad.Unit("tiny", cad.LENGTH, 5e-324).to_canonical(0.5),
            lambda: cad.Unit("tiny", cad.LENGTH, 5e-324).from_canonical(1.0),
            lambda: cad.Unit("huge", cad.LENGTH, 1e308).from_canonical(5e-324),
            lambda: cad.MM.to_canonical(10**10000),
            lambda: cad.get_unit(None),
            lambda: cad.get_unit(""),
            lambda: cad.Unit.from_dict(None),
            lambda: unit_to_payload(None),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

        thou = cad.Unit("thou", cad.LENGTH, 0.0254)
        width = cad.var(
            "width", 1000.0, unit=thou, tolerance=2.0, tolerance_unit=thou
        )
        graph = cad.ExpressionGraph()
        graph.register(width)
        payload = graph.to_dict()
        self.assertIsInstance(payload["nodes"][0]["unit"], dict)

        rebuilt = cad.ExpressionGraph.from_dict(payload).get(width.expr_id)
        self.assertIsInstance(rebuilt, cad.Var)
        self.assertEqual(rebuilt.unit, thou)
        self.assertEqual(rebuilt.tolerance_unit, thou)
        self.assertAlmostEqual(rebuilt.evaluate(), 25.4)
        self.assertAlmostEqual(rebuilt.canonical_tolerance.upper_deviation, 0.0508)

    def test_unknown_compound_dimension_uses_a_canonical_scale_one_unit(self):
        dimension = cad.Dimension(length=-1, angle=2)
        unit = cad.canonical_unit_for_dimension(dimension)

        self.assertEqual(unit.symbol, "L^-1 A^2")
        self.assertEqual(unit.dimension, dimension)
        self.assertEqual(unit.scale_to_canonical, 1.0)

    def test_malformed_custom_unit_payloads_are_rejected(self):
        base = {
            "nodes": [
                {
                    "expr_id": "var_x",
                    "kind": "var",
                    "name": "x",
                    "default": 1.0,
                    "unit": {
                        "symbol": "custom",
                        "dimension": {"length": 1, "angle": 0},
                        "scale_to_canonical": 2.0,
                    },
                }
            ]
        }
        for field in ("symbol", "dimension", "scale_to_canonical"):
            payload = json.loads(json.dumps(base))
            del payload["nodes"][0]["unit"][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                cad.ExpressionGraph.from_dict(payload)


class TestUnitAwareVariables(unittest.TestCase):
    def test_nominal_and_tolerance_units_are_canonicalized_independently(self):
        width = cad.var(
            "width",
            1.0,
            unit="in",
            tolerance=(-0.1, 0.2),
            tolerance_unit="mm",
        )
        inherited = cad.var("inherited", 1.0, unit="in", tolerance=0.01)

        self.assertEqual(width.default, 1.0)
        self.assertEqual(width.tolerance, cad.DimensionTolerance(-0.1, 0.2))
        self.assertEqual(width.unit, cad.INCH)
        self.assertEqual(width.tolerance_unit, cad.MM)
        self.assertAlmostEqual(width.canonical_default, 25.4)
        self.assertEqual(
            width.canonical_tolerance, cad.DimensionTolerance(-0.1, 0.2)
        )
        self.assertEqual(inherited.tolerance_unit, cad.INCH)
        self.assertAlmostEqual(
            inherited.canonical_tolerance.upper_deviation, 0.254
        )

    def test_bindings_use_the_variable_declaration_unit(self):
        width = cad.var("width", 1.0, unit="in")
        self.assertAlmostEqual(width.evaluate({"width": 2.0}), 50.8)
        self.assertAlmostEqual((width + 1.0).evaluate({"width": 2.0}), 51.8)

    def test_invalid_variable_unit_combinations_are_rejected(self):
        invalid_calls = [
            lambda: cad.var("x", 1.0, tolerance=0.1, tolerance_unit="mm"),
            lambda: cad.var("x", 1.0, unit="mm", tolerance_unit="mm"),
            lambda: cad.var(
                "x", 1.0, unit="mm", tolerance=0.1, tolerance_unit="deg"
            ),
            lambda: cad.var("x", 1.0, unit="unknown"),
            lambda: cad.var("x", 1e308, unit="m"),
            lambda: cad.var("x", 1.0, unit="mm", tolerance=1e308, tolerance_unit="m"),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

    def test_expression_graph_roundtrip_preserves_registered_units(self):
        angle = cad.var(
            "angle", math.pi / 2.0, unit="rad", tolerance=0.5, tolerance_unit="deg"
        )
        expression = cad.sin(angle)
        graph = cad.ExpressionGraph()
        graph.register(expression)

        payload = graph.to_dict()
        rebuilt = cad.ExpressionGraph.from_dict(payload)
        rebuilt_angle = rebuilt.get(angle.expr_id)

        self.assertEqual(rebuilt_angle.unit, cad.RADIAN)
        self.assertEqual(rebuilt_angle.tolerance_unit, cad.DEGREE)
        self.assertAlmostEqual(rebuilt.get(expression.expr_id).evaluate(), 1.0)

    def test_geometry_parameters_use_canonical_cad_values(self):
        width = cad.var("width", 1.0, unit="in")
        with cad.GraphSession() as session:
            cad.make_box_rsolid(width, 2.0, 3.0)

        node = session.graph.topological_order()[0]
        self.assertAlmostEqual(node.params["width"], 25.4)
        self.assertEqual(node.param_exprs["width"]["expr_id"], width.expr_id)


class TestDimensionInference(unittest.TestCase):
    def setUp(self):
        self.length = cad.var("length", 3.0, unit="mm")
        self.other_length = cad.var("other_length", 4.0, unit="cm")
        self.angle = cad.var("angle", 90.0, unit="deg")
        self.scalar = cad.var("scalar", 50.0, unit="%")

    def test_addition_subtraction_and_contextual_constants(self):
        self.assertEqual(cad.infer_dimension(self.length + self.other_length), cad.LENGTH)
        self.assertEqual(cad.infer_dimension(self.length - 1.0), cad.LENGTH)
        self.assertEqual(cad.infer_dimension(1.0 + self.angle), cad.ANGLE)
        self.assertAlmostEqual((self.length + self.other_length).evaluate(), 43.0)

    def test_multiplication_division_and_powers(self):
        area = self.length * self.other_length
        volume = area * self.length
        ratio = self.length / self.other_length
        inverse = 1.0 / self.length

        self.assertEqual(cad.infer_dimension(area), cad.AREA)
        self.assertEqual(cad.infer_dimension(volume), cad.VOLUME)
        self.assertEqual(cad.infer_dimension(ratio), cad.DIMENSIONLESS)
        self.assertEqual(cad.infer_dimension(inverse), cad.Dimension(length=-1))
        self.assertEqual(cad.infer_dimension(self.length**3), cad.VOLUME)
        self.assertEqual(cad.infer_dimension(self.length**0), cad.DIMENSIONLESS)
        self.assertEqual(
            cad.infer_dimension(self.scalar ** cad.var("power", 2.0, unit="1")),
            cad.DIMENSIONLESS,
        )

    def test_square_root_requires_even_dimension_exponents(self):
        diagonal = cad.sqrt(self.length**2 + self.other_length**2)
        self.assertEqual(cad.infer_dimension(diagonal), cad.LENGTH)
        self.assertAlmostEqual(diagonal.evaluate(), math.sqrt(1609.0))
        self.assertEqual(cad.infer_dimension(cad.sqrt(self.scalar)), cad.DIMENSIONLESS)
        with self.assertRaises(cad.UnitValidationError):
            cad.infer_dimension(cad.sqrt(self.length))
        with self.assertRaises(cad.UnitValidationError):
            cad.infer_dimension(self.length**0.5)

    def test_unary_and_trigonometric_dimensions(self):
        self.assertEqual(cad.infer_dimension(-self.length), cad.LENGTH)
        self.assertEqual(cad.infer_dimension(abs(self.length)), cad.LENGTH)
        for expression in (
            cad.sin(self.angle),
            cad.cos(self.angle),
            cad.tan(self.angle),
        ):
            self.assertEqual(cad.infer_dimension(expression), cad.DIMENSIONLESS)
        for expression in (
            cad.asin(self.scalar),
            cad.acos(self.scalar),
            cad.atan(self.scalar),
            cad.atan2(self.length, self.other_length),
        ):
            self.assertEqual(cad.infer_dimension(expression), cad.ANGLE)

    def test_invalid_physical_expressions_are_rejected(self):
        legacy = cad.var("legacy", 1.0)
        invalid = [
            self.length + self.angle,
            self.length + self.scalar,
            self.length + legacy,
            self.length * legacy,
            self.length ** self.scalar,
            self.length ** self.angle,
            self.length ** legacy,
            self.length**0.25,
            cad.sin(self.length),
            cad.asin(self.length),
            cad.atan2(self.length, self.angle),
        ]
        for expression in invalid:
            with self.subTest(op=expression.op), self.assertRaises(
                cad.UnitValidationError
            ):
                cad.infer_dimension(expression)

        with self.assertRaises(cad.UnitValidationError):
            (self.length + self.angle).evaluate()

    def test_inference_cache_does_not_hide_conflicting_duplicate_ids(self):
        length = cad.Var("length", 1.0, expr_id="same", unit=cad.MM)
        angle = cad.Var("angle", 1.0, expr_id="same", unit=cad.DEGREE)
        expression = cad.Expr("add", (length, angle))

        with self.assertRaises(cad.UnitValidationError):
            cad.infer_dimension(expression)
        with self.assertRaisesRegex(ValueError, "different node"):
            cad.ExpressionGraph().register(expression)

    def test_inference_rejects_mutated_cycles_ops_and_node_types(self):
        cycle = cad.Expr("neg", (cad.const(1.0),), expr_id="cycle")
        object.__setattr__(cycle, "args", (cycle,))
        with self.assertRaisesRegex(cad.UnitValidationError, "cycle"):
            cad.infer_dimension(cycle)

        unsupported = cad.Expr("neg", (cad.const(1.0),))
        object.__setattr__(unsupported, "op", "unsupported")
        with self.assertRaisesRegex(cad.UnitValidationError, "Unsupported"):
            cad.infer_dimension(unsupported)

        with self.assertRaisesRegex(TypeError, "Unsupported expression node"):
            _infer(object(), {}, set())

    def test_legacy_expressions_keep_radian_math_and_unknown_dimension(self):
        value = cad.var("legacy", 0.5)
        expression = value ** cad.var("legacy_power", 2.0)

        self.assertIsNone(cad.infer_dimension(expression))
        self.assertFalse(cad.expression_uses_units(expression))
        self.assertAlmostEqual(cad.sin(value).evaluate(), math.sin(0.5))
        self.assertAlmostEqual(cad.asin(value).evaluate(), math.asin(0.5))
        self.assertIsNone(cad.infer_dimension(cad.sin(value)))
        self.assertIsNone(cad.infer_dimension(value + value))
        self.assertIsNone(cad.infer_dimension(cad.atan2(value, value)))


class TestUnitAwareMathAndTolerance(unittest.TestCase):
    def test_trigonometric_evaluation_uses_degrees_canonically(self):
        degrees = cad.var("degrees", 90.0, unit="deg")
        radians = cad.var("radians", math.pi / 2.0, unit="rad")
        ratio = cad.var("ratio", 50.0, unit="%")
        y = cad.var("y", 1.0, unit="in")
        x = cad.var("x", 25.4, unit="mm")

        self.assertAlmostEqual(cad.sin(degrees).evaluate(), 1.0)
        self.assertAlmostEqual(cad.sin(radians).evaluate(), 1.0)
        self.assertAlmostEqual(cad.asin(ratio).evaluate(), 30.0)
        self.assertAlmostEqual(cad.atan2(y, x).evaluate(), 45.0)

    def test_diagonal_tolerance_chain_reports_length_in_mm(self):
        width = cad.var(
            "width", 3.0, unit="cm", tolerance=0.1, tolerance_unit="mm"
        )
        height = cad.var("height", 40.0, unit="mm", tolerance=0.2)
        diagonal = cad.sqrt(width**2 + height**2)

        worst_case = cad.analyze_tolerance(diagonal)
        rss = cad.analyze_tolerance(diagonal, method="rss")

        self.assertEqual(worst_case.dimension, cad.LENGTH)
        self.assertEqual(worst_case.unit, cad.MM)
        self.assertAlmostEqual(worst_case.nominal, 50.0)
        self.assertLess(worst_case.lower_deviation, 0.0)
        self.assertGreater(worst_case.upper_deviation, 0.0)
        expected_rss = math.hypot(0.6 * 0.1, 0.8 * 0.2)
        self.assertAlmostEqual(rss.upper_deviation, expected_rss, places=12)
        self.assertTrue(all(item.source_unit == cad.MM for item in rss.contributions))

    def test_angle_tolerance_propagation_converts_derivatives(self):
        angle = cad.var("angle", 30.0, unit="deg", tolerance=1.0)
        result = cad.analyze_tolerance(cad.sin(angle), method="rss")
        expected = math.cos(math.radians(30.0)) * math.pi / 180.0

        self.assertEqual(result.dimension, cad.DIMENSIONLESS)
        self.assertEqual(result.unit, cad.ONE)
        self.assertAlmostEqual(result.nominal, 0.5)
        self.assertAlmostEqual(result.upper_deviation, expected, places=12)

    def test_inverse_trig_and_atan2_tolerances_report_degrees(self):
        ratio = cad.var("ratio", 50.0, unit="%", tolerance=1.0)
        y = cad.var("y", 10.0, unit="mm", tolerance=0.1)
        x = cad.var("x", 10.0, unit="mm", tolerance=0.1)

        asin_result = cad.analyze_tolerance(cad.asin(ratio), method="rss")
        atan2_result = cad.analyze_tolerance(cad.atan2(y, x), method="rss")

        self.assertEqual(asin_result.unit, cad.DEGREE)
        self.assertAlmostEqual(asin_result.nominal, 30.0)
        self.assertEqual(atan2_result.unit, cad.DEGREE)
        self.assertAlmostEqual(atan2_result.nominal, 45.0)

    def test_area_and_volume_analysis_are_inferred_but_not_requirements(self):
        width = cad.var("width", 2.0, unit="mm", tolerance=0.1)
        area = width**2
        volume = width**3

        self.assertEqual(cad.analyze_tolerance(area).dimension, cad.AREA)
        self.assertEqual(cad.analyze_tolerance(volume).dimension, cad.VOLUME)
        with self.assertRaisesRegex(ValueError, "Length or Angle"):
            cad.check_tolerance(area, 0.5, tolerance_unit="mm^2")


class TestUnitAwareRequirementsAndPersistence(unittest.TestCase):
    def test_requirement_tolerance_units_are_converted_before_comparison(self):
        width = cad.var(
            "width", 1.0, unit="in", tolerance=0.1, tolerance_unit="mm"
        )
        passing = cad.check_tolerance(width, 0.004, tolerance_unit="in")
        failing = cad.check_tolerance(width, 0.003, tolerance_unit="in")

        self.assertTrue(passing.passed)
        self.assertFalse(failing.passed)
        self.assertEqual(passing.requirement.tolerance_unit, cad.INCH)
        self.assertAlmostEqual(
            passing.requirement.canonical_tolerance.upper_deviation, 0.1016
        )

    def test_requirement_unit_validation(self):
        length = cad.var("length", 10.0, unit="mm", tolerance=0.1)
        legacy = cad.var("legacy", 10.0, tolerance=0.1)
        scalar = cad.var("scalar", 1.0, unit="1", tolerance=0.1)

        with self.assertRaisesRegex(ValueError, "incompatible"):
            cad.check_tolerance(length, 1.0, tolerance_unit="deg")
        with self.assertRaisesRegex(ValueError, "unit-aware"):
            cad.check_tolerance(legacy, 1.0, tolerance_unit="mm")
        with self.assertRaisesRegex(ValueError, "Length or Angle"):
            cad.check_tolerance(scalar, 0.1)

    def test_session_model_and_tolerance_graph_roundtrip_units(self):
        width = cad.var(
            "width", 1.0, unit="in", tolerance=0.1, tolerance_unit="mm"
        )
        with cad.GraphSession() as session:
            cad.make_box_rsolid(width, 2.0, 3.0)
            requirement = session.require_tolerance(
                width, 0.004, tolerance_unit="in", name="width"
            )

        raw = json.loads(cad.export_model_json(session))
        self.assertEqual(raw["expression_graph"]["nodes"][0]["unit"], "in")
        self.assertEqual(
            raw["expression_graph"]["nodes"][0]["tolerance_unit"], "mm"
        )
        self.assertEqual(
            raw["tolerance_graph"]["requirements"][0]["tolerance_unit"], "in"
        )
        self.assertEqual(
            raw["tolerance_graph"]["requirements"][0]["target_dimension"],
            cad.LENGTH.to_dict(),
        )

        imported = cad.import_model_json(json.dumps(raw))
        rebuilt = imported["tolerance_graph"].requirements[0]
        self.assertEqual(rebuilt, requirement)
        self.assertTrue(imported["tolerance_graph"].validate().passed)
        self.assertEqual(len(cad.replay_model_json(json.dumps(raw))), 1)

    def test_import_rejects_tampered_requirement_units_and_dimensions(self):
        width = cad.var("width", 10.0, unit="mm", tolerance=0.1)
        expressions = cad.ExpressionGraph()
        tolerances = cad.ToleranceGraph(expressions)
        tolerances.require(width, 0.1, tolerance_unit="mm", requirement_id="req")
        expression_payload = expressions.to_dict()

        wrong_unit = tolerances.to_dict()
        wrong_unit["requirements"][0]["tolerance_unit"] = "deg"
        with self.assertRaisesRegex(ValueError, "incompatible"):
            cad.ToleranceGraph.from_dict(
                wrong_unit, cad.ExpressionGraph.from_dict(expression_payload)
            )

        wrong_dimension = tolerances.to_dict()
        wrong_dimension["requirements"][0]["target_dimension"] = cad.ANGLE.to_dict()
        with self.assertRaisesRegex(ValueError, "does not match"):
            cad.ToleranceGraph.from_dict(
                wrong_dimension, cad.ExpressionGraph.from_dict(expression_payload)
            )

        missing_dimension = tolerances.to_dict()
        missing_dimension["requirements"][0]["target_dimension"] = None
        with self.assertRaisesRegex(ValueError, "does not match"):
            cad.ToleranceGraph.from_dict(
                missing_dimension, cad.ExpressionGraph.from_dict(expression_payload)
            )

    def test_legacy_payloads_and_requirements_remain_compatible(self):
        width = cad.var("width", 10.0, tolerance=0.1)
        graph = cad.ExpressionGraph()
        tolerance_graph = cad.ToleranceGraph(graph)
        tolerance_graph.require(width, 0.1, requirement_id="legacy")
        payload = tolerance_graph.to_dict()
        payload["requirements"][0].pop("tolerance_unit")
        payload["requirements"][0].pop("target_dimension")

        rebuilt = cad.ToleranceGraph.from_dict(payload, graph)
        requirement = rebuilt.requirements[0]
        self.assertIsNone(requirement.tolerance_unit)
        self.assertIsNone(requirement.target_dimension)
        self.assertTrue(rebuilt.validate().passed)


if __name__ == "__main__":
    unittest.main()
