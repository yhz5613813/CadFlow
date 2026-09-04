from __future__ import annotations

from collections.abc import Mapping

import pytest

import cadflow as cad
from cadflow.scene import (
    parse_canonical_json,
    preflight_zip_bytes,
    validate_scene_package,
)


IDENTITY = {
    "origin": [0.0, 0.0, 0.0],
    "x_axis": [1.0, 0.0, 0.0],
    "y_axis": [0.0, 1.0, 0.0],
    "z_axis": [0.0, 0.0, 1.0],
}


def _presentation(
    *,
    presentation_id: str = "optimus-red",
    scene_id: str = "optimus",
    appearance_name: str = "hero-red",
    color: list[float] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "presentation_id": presentation_id,
        "source_scene_id": scene_id,
        "appearances": [
            {
                "name": appearance_name,
                "base_color": color or [0.72, 0.03, 0.02, 1.0],
                "metallic": 0.75,
                "roughness": 0.22,
                "alpha_mode": "opaque",
                "double_sided": False,
                "edge_color": [0.05, 0.05, 0.05, 1.0],
            }
        ],
        "node_overrides": [
            {
                "node_id": "instance/main",
                "visible": True,
                "appearance_name": appearance_name,
            }
        ],
        "cameras": [
            {
                "name": "hero",
                "projection": "perspective",
                "parent_node_id": "instance/main",
                "transform": IDENTITY,
                "vertical_fov_degrees": 42.0,
                "near": 0.1,
                "far": 500.0,
            }
        ],
    }


def _compile(*, presentation=None, embedded: bool = False):
    return cad.compile_scene(
        scene_id="optimus",
        roots=(
            cad.SceneRoot(
                root_id="main",
                value=cad.make_box_rsolid(width=10, height=20, depth=30),
            ),
        ),
        source=cad.SceneSource(kind="manual", source_id="presentation-test"),
        presentation=presentation,
        options=cad.SceneCompileOptions(embed_presentation=embedded),
    )


def _node_appearance(package):
    node = next(
        node
        for node in package.manifest["nodes"]
        if node["node_id"] == "instance/main"
    )
    appearance = next(
        appearance
        for appearance in package.manifest["appearances"]
        if appearance["appearance_id"] == node["appearance_override_id"]
    )
    return node, appearance


def test_compile_scene_embeds_evaluated_presentation(tmp_path) -> None:
    package = _compile(presentation=_presentation(), embedded=True)
    node, appearance = _node_appearance(package)

    assert node["visible"] is True
    assert appearance["base_color"] == pytest.approx((0.72, 0.03, 0.02, 1.0))
    assert appearance["metallic"] == pytest.approx(0.75)
    assert appearance["roughness"] == pytest.approx(0.22)
    assert appearance["source"] == {
        "kind": "presentation",
        "presentation_id": "optimus-red",
        "appearance_name": "hero-red",
    }
    assert package.manifest["cameras"][0]["parent_node_id"] == "instance/main"
    source = package.manifest["presentation_source"]
    assert source["embedded_artifact_uri"] == "presentation/presentation.json"
    assert parse_canonical_json(package.blobs[source["embedded_artifact_uri"]]) == _presentation()
    assert validate_scene_package(package.manifest, package.blobs).valid

    output = tmp_path / "optimus.scene.zip"
    cad.export_scene(package=package, path=output)
    archive = preflight_zip_bytes(output.read_bytes())
    exported = parse_canonical_json(archive.members["scene.json"])
    exported_node = next(
        item for item in exported["nodes"] if item["node_id"] == "instance/main"
    )
    assert exported_node["appearance_override_id"] == appearance["appearance_id"]


def test_apply_presentation_reuses_geometry_and_replaces_old_state() -> None:
    base = _compile()
    red = cad.apply_presentation(
        package=base,
        presentation=_presentation(),
        embed_presentation=True,
    )
    blue_document = _presentation(
        presentation_id="optimus-blue",
        appearance_name="hero-blue",
        color=[0.02, 0.12, 0.75, 1.0],
    )
    blue = cad.apply_presentation(
        package=red,
        presentation=blue_document,
        embed_presentation=False,
    )
    repeated = cad.apply_presentation(
        package=red,
        presentation=blue_document,
        embed_presentation=False,
    )

    _, red_appearance = _node_appearance(red)
    _, blue_appearance = _node_appearance(blue)
    assert blue_appearance["base_color"] == pytest.approx((0.02, 0.12, 0.75, 1.0))
    assert red_appearance["appearance_id"] not in {
        appearance["appearance_id"] for appearance in blue.manifest["appearances"]
    }
    assert [
        appearance
        for appearance in blue.manifest["appearances"]
        if isinstance(appearance.get("source"), Mapping)
        and appearance["source"].get("kind") == "presentation"
    ] == [blue_appearance]
    assert blue.manifest["presentation_source"]["presentation_id"] == "optimus-blue"
    assert "embedded_artifact_uri" not in blue.manifest["presentation_source"]
    assert "presentation/presentation.json" not in blue.blobs

    geometry_uris = {
        record["uri"]
        for key in ("geometry_assets", "edge_assets", "entity_assets")
        for record in base.manifest[key]
    }
    assert all(base.blobs[uri] == red.blobs[uri] == blue.blobs[uri] for uri in geometry_uris)
    assert "presentation_source" not in base.manifest
    assert blue.manifest == repeated.manifest
    assert dict(blue.blobs) == dict(repeated.blobs)
    assert validate_scene_package(blue.manifest, blue.blobs).valid


def test_presentation_context_is_checked_by_native_core() -> None:
    document = _presentation(scene_id="another-scene")
    with pytest.raises(cad.NativeError, match="source_scene_id does not match"):
        _compile(presentation=document)


def test_repeated_part_occurrences_receive_independent_appearances() -> None:
    part = cad.make_part_rpart(
        part_id="robot",
        body=cad.make_box_rsolid(width=4, height=5, depth=6),
    )
    assembly = cad.make_assembly_rassembly(assembly_id="pair")
    assembly = cad.add_component_rassembly(
        assembly=assembly,
        item=part,
        component_id="standing",
        placement=cad.identity_placement_rplacement(),
    )
    assembly = cad.add_component_rassembly(
        assembly=assembly,
        item=part,
        component_id="lying",
        placement=cad.make_placement_rplacement(origin=(10, 0, 0)),
    )
    presentation = {
        "schema_version": "1.0",
        "presentation_id": "robot-pair-colors",
        "source_scene_id": "robot-pair",
        "appearances": [
            {
                "name": "red",
                "base_color": [0.8, 0.03, 0.02, 1.0],
                "metallic": 0.7,
                "roughness": 0.25,
                "alpha_mode": "opaque",
                "double_sided": False,
                "edge_color": [0.05, 0.05, 0.05, 1.0],
            },
            {
                "name": "blue",
                "base_color": [0.02, 0.12, 0.8, 1.0],
                "metallic": 0.7,
                "roughness": 0.25,
                "alpha_mode": "opaque",
                "double_sided": False,
                "edge_color": [0.05, 0.05, 0.05, 1.0],
            },
        ],
        "node_overrides": [
            {"node_id": "instance/main/standing", "appearance_name": "red"},
            {"node_id": "instance/main/lying", "appearance_name": "blue"},
        ],
        "cameras": [],
    }
    package = cad.compile_scene(
        scene_id="robot-pair",
        roots=(cad.SceneRoot(root_id="main", value=assembly),),
        source=cad.SceneSource(kind="manual", source_id="robot-pair-test"),
        presentation=presentation,
    )

    appearances = {
        appearance["appearance_id"]: appearance
        for appearance in package.manifest["appearances"]
    }
    colors = {
        node["node_id"]: appearances[node["appearance_override_id"]]["base_color"]
        for node in package.manifest["nodes"]
        if node["appearance_override_id"] is not None
    }
    assert colors == {
        "instance/main/lying": pytest.approx((0.02, 0.12, 0.8, 1.0)),
        "instance/main/standing": pytest.approx((0.8, 0.03, 0.02, 1.0)),
    }
    assert len(package.manifest["geometry_assets"]) == 1


def test_embed_presentation_requires_a_document() -> None:
    with pytest.raises(ValueError, match="requires a Presentation"):
        _compile(embedded=True)
