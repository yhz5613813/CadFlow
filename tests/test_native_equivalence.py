from __future__ import annotations

import pytest

import cadflow


def _old_volume(shape) -> float:
    properties = cadflow.compat.submodule("kernel.ocp_properties")
    return properties.volume(shape.wrapped)


@pytest.mark.parametrize(
    ("native_factory", "old_factory"),
    [
        (lambda model: model.box(2, 3, 4), lambda old: old.make_box_rsolid(2, 3, 4)),
        (lambda model: model.cylinder(2, 5), lambda old: old.make_cylinder_rsolid(2, 5)),
        (lambda model: model.sphere(2), lambda old: old.make_sphere_rsolid(2)),
        (lambda model: model.cone(2, 1, 3), lambda old: old.make_cone_rsolid(2, 3, 1)),
    ],
)
def test_native_primitive_volume_matches_compatibility(native_factory, old_factory) -> None:
    with cadflow.Model() as model:
        native = native_factory(model)
        old = old_factory(cadflow.legacy_api())
        assert native.volume == pytest.approx(_old_volume(old))
