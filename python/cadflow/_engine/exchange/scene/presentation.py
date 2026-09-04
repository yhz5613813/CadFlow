"""Evaluate and apply Scene Presentation documents without touching geometry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from cadflow._presentation_native import evaluate_presentation_native
from cadflow._engine.exchange.scene.canonical import canonical_json_bytes, with_scene_revision
from cadflow._engine.exchange.scene.documents import PresentationDocument


PRESENTATION_URI = "presentation/presentation.json"


@dataclass(frozen=True, slots=True)
class EvaluatedPresentation:
    document: PresentationDocument
    appearances: tuple[Mapping[str, Any], ...]
    node_visibility: tuple[bool, ...]
    node_appearance_ids: tuple[str | None, ...]
    cameras: tuple[Mapping[str, Any], ...]

    def source_record(self, *, embedded: bool) -> dict[str, Any]:
        value = self.document.value
        record: dict[str, Any] = {
            "presentation_id": value["presentation_id"],
            "schema_version": value["schema_version"],
            "artifact_hash": self.document.canonical_hash,
        }
        if embedded:
            record.update(
                {
                    "embedded_artifact_uri": PRESENTATION_URI,
                    "embedded_artifact_byte_length": len(self.document.canonical_bytes),
                }
            )
        return record


def evaluate_presentation(
    *,
    scene_id: str,
    presentation: PresentationDocument | Mapping[str, Any],
    nodes: Sequence[Mapping[str, Any]],
    definitions: Sequence[Mapping[str, Any]],
) -> EvaluatedPresentation:
    """Evaluate a validated Presentation against one compiled scene structure."""

    document = (
        presentation
        if isinstance(presentation, PresentationDocument)
        else PresentationDocument.from_value(presentation)
    )
    value = document.to_mutable()
    definition_kinds = {
        definition["definition_id"]: definition["kind"] for definition in definitions
    }
    native_nodes = []
    for node in nodes:
        definition_id = node["definition_id"]
        if definition_id not in definition_kinds:
            raise ValueError(f"scene node references an unknown definition: {definition_id}")
        native_nodes.append(
            {
                "node_id": node["node_id"],
                "appearance_capable": definition_kinds[definition_id] in {"part", "shape"},
                "visible": node.get("visible", True),
            }
        )

    native = evaluate_presentation_native(
        presentation_source_scene_id=value["source_scene_id"],
        scene_id=scene_id,
        appearances=value["appearances"],
        nodes=native_nodes,
        overrides=value["node_overrides"],
        cameras=value["cameras"],
    )

    evaluated_appearances: list[dict[str, Any]] = []
    for authored in value["appearances"]:
        evaluated = {
            "alpha_mode": authored["alpha_mode"],
            "base_color": authored["base_color"],
            "double_sided": authored["double_sided"],
            "edge_color": authored["edge_color"],
            "metallic": authored["metallic"],
            "name": authored["name"],
            "roughness": authored["roughness"],
            "sdk_metadata": {},
            "source": {
                "appearance_name": authored["name"],
                "kind": "presentation",
                "presentation_id": value["presentation_id"],
            },
        }
        appearance_id = "appearance/evaluated/" + hashlib.sha256(
            canonical_json_bytes(evaluated)
        ).hexdigest()
        evaluated_appearances.append(
            {"appearance_id": appearance_id, **evaluated}
        )

    node_appearance_ids = tuple(
        None
        if index is None
        else evaluated_appearances[index]["appearance_id"]
        for index in native.node_appearance_indices
    )
    evaluated_cameras: list[dict[str, Any]] = []
    for index, authored in enumerate(value["cameras"]):
        camera = dict(authored)
        parent_index = native.camera_parent_indices[index]
        camera["parent_node_id"] = (
            None if parent_index is None else nodes[parent_index]["node_id"]
        )
        encoded_name = quote(
            str(authored["name"]),
            safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~",
        )
        evaluated_cameras.append(
            {
                "camera_id": f"camera/{value['presentation_id']}/{encoded_name}",
                **camera,
            }
        )

    return EvaluatedPresentation(
        document=document,
        appearances=tuple(evaluated_appearances),
        node_visibility=native.node_visibility,
        node_appearance_ids=node_appearance_ids,
        cameras=tuple(evaluated_cameras),
    )


def apply_presentation_values(
    *,
    manifest: Mapping[str, Any],
    blobs: Mapping[str, bytes],
    presentation: PresentationDocument | Mapping[str, Any],
    embed_presentation: bool,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Return detached Scene values with one Presentation applied or replaced."""

    scene = _copy_json(manifest)
    next_blobs = {str(uri): bytes(payload) for uri, payload in blobs.items()}
    scene.pop("presentation_source", None)
    scene["appearances"] = [
        appearance
        for appearance in scene["appearances"]
        if not (
            isinstance(appearance.get("source"), dict)
            and appearance["source"].get("kind") == "presentation"
        )
    ]
    for node in scene["nodes"]:
        node["visible"] = True
        node["appearance_override_id"] = None
    scene["cameras"] = []
    scene["compile_options"]["embed_presentation"] = False
    next_blobs.pop(PRESENTATION_URI, None)

    evaluated = evaluate_presentation(
        scene_id=scene["scene_id"],
        presentation=presentation,
        nodes=scene["nodes"],
        definitions=scene["definitions"],
    )
    appearances_by_id = {
        appearance["appearance_id"]: appearance
        for appearance in scene["appearances"]
    }
    for appearance in evaluated.appearances:
        mutable = dict(appearance)
        existing = appearances_by_id.get(mutable["appearance_id"])
        if existing is not None and existing != mutable:
            raise ValueError("presentation appearance hash collision")
        appearances_by_id[mutable["appearance_id"]] = mutable
    scene["appearances"] = sorted(
        appearances_by_id.values(), key=lambda item: item["appearance_id"].encode("utf-8")
    )
    for index, node in enumerate(scene["nodes"]):
        node["visible"] = evaluated.node_visibility[index]
        node["appearance_override_id"] = evaluated.node_appearance_ids[index]
    scene["cameras"] = [dict(camera) for camera in evaluated.cameras]
    scene["presentation_source"] = evaluated.source_record(
        embedded=embed_presentation
    )
    scene["compile_options"]["embed_presentation"] = embed_presentation
    if embed_presentation:
        next_blobs[PRESENTATION_URI] = evaluated.document.canonical_bytes
    return with_scene_revision(scene), next_blobs


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_copy_json(item) for item in value]
    return value


__all__ = [
    "EvaluatedPresentation",
    "PRESENTATION_URI",
    "apply_presentation_values",
    "evaluate_presentation",
]
