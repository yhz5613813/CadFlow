from __future__ import annotations

import math

import pytest

import cadflow


def test_router_uses_native_handles_and_complete_fallback() -> None:
    router = cadflow.Router()
    try:
        native_box = router.call("box", 2, 3, 4)
        assert router.call("volume", native_box) == pytest.approx(24)

        lower = router.call("circle_profile", 2, center=(0, 0, 0))
        upper = router.call("circle_profile", 1, center=(0, 0, 3))
        lofted = router.call("loft", [lower, upper])
        assert router.call("volume", shape=lofted) == pytest.approx(7 * math.pi)

        old_box = router.call("make_box_rsolid", 2, 3, 4)
        assert old_box.wrapped is not None
    finally:
        router.close()


def test_every_old_top_level_export_is_visible_from_cadflow() -> None:
    old = cadflow.legacy_api()
    missing = [name for name in old.__all__ if not hasattr(cadflow, name)]
    assert missing == []


def test_native_capabilities_cover_all_bound_operations() -> None:
    native = set(cadflow.capabilities()["native"])
    assert {
        "polyline",
        "circle_profile",
        "arc",
        "interpolate",
        "helix",
        "face",
        "bezier_surface",
        "fit_surface",
        "extrude",
        "revolve",
        "fillet",
        "chamfer",
        "shell",
        "loft",
        "sweep",
        "mirror",
        "scale",
        "length",
        "center_of_mass",
        "distance",
        "mesh",
        "export_step",
        "export_stl",
        "export_dxf",
        "import_step",
    } <= native
