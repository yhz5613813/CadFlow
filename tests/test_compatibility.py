from __future__ import annotations

import cadflow
import pytest


def test_complete_legacy_surface_is_available_lazily() -> None:
    legacy = cadflow.compat
    assert legacy.make_box_rsolid is not None
    assert legacy.GraphSession is not None
    assert legacy.export_model_json is not None
    assert cadflow.make_box_rsolid is legacy.make_box_rsolid


def test_legacy_geometry_still_runs() -> None:
    legacy = cadflow.legacy_api()
    shape = legacy.make_box_rsolid(2, 3, 4)
    properties = cadflow.compat.submodule("kernel.ocp_properties")
    assert properties.volume(shape.wrapped) == pytest.approx(24)


def test_legacy_submodule_access() -> None:
    topology = cadflow.compat.submodule("topology")
    assert hasattr(topology, "TopoDelta")
