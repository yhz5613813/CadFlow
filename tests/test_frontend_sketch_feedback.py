from __future__ import annotations

import pytest

import cadflow


def _fixed_rectangle(model: cadflow.Model):
    sketch = model.sketch("plate")
    sketch = (
        sketch.add_point("p0", 0, 0)
        .add_point("p1", 4, 0)
        .add_point("p2", 4, 2)
        .add_point("p3", 0, 2)
    )
    sketch = (
        sketch.add_line("bottom", "p0", "p1")
        .add_line("right", "p1", "p2")
        .add_line("top", "p2", "p3")
        .add_line("left", "p3", "p0")
    )
    for point in ("p0", "p1", "p2", "p3"):
        sketch = sketch.constrain_fix(point)
    return sketch


def test_workplane_is_explicit_nested_and_does_not_leak() -> None:
    with cadflow.Model() as model:
        outer = model.workplane(origin=(10, 20, 30), normal=(0, 1, 0))
        with outer:
            assert cadflow.current_frame().origin == pytest.approx((10, 20, 30))
            with model.workplane(origin=(2, 3, 4), normal=(1, 0, 0)) as inner:
                assert inner.point((0, 0, 0)) == pytest.approx((12, 24, 27))
                sketch = inner.sketch("nested")
            assert sketch.frame.origin == pytest.approx((12, 24, 27))
        assert cadflow.current_frame().origin == pytest.approx((0, 0, 0))


def test_modern_sketch_uses_existing_solver_and_lowers_native_face() -> None:
    with cadflow.Model() as model:
        sketch = _fixed_rectangle(model)
        result = sketch.inspect(require_fully_constrained=True)
        assert result.status == "solved"
        assert result.dof == 0
        assert result.backend == "py-slvs"
        face = sketch.to_native_face(model, require_fully_constrained=True)
        assert face.kind == "face"
        assert face.area == pytest.approx(8.0)
        assert face.bbox == pytest.approx((0, 0, 0, 4, 2, 0), abs=1e-6)


def test_shape_and_operation_feedback_are_machine_readable() -> None:
    with cadflow.Model() as model:
        base = model.box(2, 3, 4)
        description = base.describe()
        assert description["topology"]["solids"] == 1
        assert base.validate().status == "valid"

        result = model.apply("translate", base, 1, 2, 3)
        assert result.report.ok
        assert result.shape.bbox == pytest.approx((1, 2, 3, 3, 5, 7))

        blocked = model.preflight("shell", base, thickness=-1)
        assert blocked.status == "blocked"
        assert blocked.diagnostics[0].code == "parameter.invalid"


def test_capabilities_advertise_feedback_and_python_sketch_boundary() -> None:
    with cadflow.Model() as model:
        capabilities = model.capabilities()
        assert "sketch" in capabilities["frontend"]
        assert "feedback" in capabilities["frontend"]
        assert capabilities["selection"] == {"indices": True, "semantic": False}
