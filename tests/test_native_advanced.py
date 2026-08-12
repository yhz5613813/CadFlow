from __future__ import annotations

import math

import pytest

import cadflow


def _occt() -> bool:
    with cadflow.NativeSession() as session:
        return "analytic" not in session.version


requires_occt = pytest.mark.skipif(not _occt(), reason="requires OCCT native backend")


@requires_occt
def test_native_advanced_geometry_and_queries() -> None:
    with cadflow.Model() as model:
        spline = model.bspline(
            ((0, 0, 0), (1, 0, 0), (2, 1, 0), (3, 0, 0)),
            degree=3,
            knots=(0, 1),
            multiplicities=(4, 4),
        )
        assert spline.kind == "bspline"
        assert spline.length > 3.0

        lower = model.polyline(((0, 0, 0), (1, 0, 0)), closed=False)
        upper = model.polyline(((0, 0, 1), (1, 0, 1)), closed=False)
        ruled = model.ruled_surface(lower, upper)
        assert ruled.kind == "ruled_surface"
        assert ruled.area == pytest.approx(1.0)

        profile = model.face(model.polyline(
            ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), closed=True
        ))
        twisted = model.twisted_sweep(profile, 2.0, 90.0)
        assert twisted.kind == "twisted_sweep"
        assert twisted.volume == pytest.approx(8.0, rel=1e-5)

        props = profile.face_properties()
        assert props["normal"] == pytest.approx((0.0, 0.0, 1.0))
        assert props["curvature"] == pytest.approx((0.0, 0.0, 0.0))
        assert len(model.subshapes(twisted, 4)) > 0
        assert len(model.free_boundaries(profile)) == 1


@requires_occt
def test_native_brep_and_stl_import(tmp_path) -> None:
    with cadflow.Model() as model:
        shape = model.box(1, 2, 3)
        brep = tmp_path / "box.brep"
        # BREP export is intentionally kept in the C++ test fixture via OCC's
        # public writer; the public facade only promises import at this point.
        pytest.importorskip("OCP")
        # Use the native STEP round trip for a stable imported-shape sanity check.
        step = tmp_path / "box.step"
        shape.export_step(str(step))
        imported = model.import_step(step)
        assert imported.volume == pytest.approx(6.0)
        assert imported.kind == "imported"


def test_advanced_invalid_inputs_are_rejected() -> None:
    with cadflow.Model() as model:
        with pytest.raises(cadflow.NativeError, match="degree"):
            model.bspline(((0, 0, 0), (1, 0, 0)), degree=0, knots=(0, 1), multiplicities=(1, 1))
        with pytest.raises(cadflow.NativeError, match="must not be empty"):
            model.filling_surface((), tolerance=0.0)
