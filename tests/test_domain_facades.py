from __future__ import annotations

import cadflow


def test_new_domains_expose_old_capabilities_without_copying_modules() -> None:
    assert cadflow.modeling.make_box_rsolid is not None
    assert cadflow.serialization.export_model_json is not None
    assert cadflow.graph_api.GraphSession is not None
    assert cadflow.assembly.Assembly is not None
    assert cadflow.sketch.Sketch is not None
    assert cadflow.stdlib.make_spur_gear_rsolid is not None
    assert cadflow.scene.compile_scene is not None
    assert cadflow.query.ShapeSelector is not None
    assert cadflow.topology.TopoDelta is not None
