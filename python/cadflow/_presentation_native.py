"""Thin ctypes bridge for the stateless native Presentation evaluator."""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Sequence

from .native import NativeError, _load_library


_UNSET_INDEX = C.c_size_t(-1).value


class _Appearance(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("base_color", C.c_double * 4),
        ("metallic", C.c_double),
        ("roughness", C.c_double),
        ("alpha_mode", C.c_int),
        ("double_sided", C.c_int),
        ("edge_color", C.c_double * 4),
    ]


class _SceneNode(C.Structure):
    _fields_ = [
        ("node_id", C.c_char_p),
        ("appearance_capable", C.c_int),
        ("visible", C.c_int),
    ]


class _NodeOverride(C.Structure):
    _fields_ = [
        ("node_id", C.c_char_p),
        ("has_visible", C.c_int),
        ("visible", C.c_int),
        ("appearance_name", C.c_char_p),
    ]


class _Camera(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("parent_node_id", C.c_char_p),
        ("projection", C.c_int),
        ("near_plane", C.c_double),
        ("far_plane", C.c_double),
        ("projection_value", C.c_double),
    ]


@dataclass(frozen=True, slots=True)
class NativePresentationEvaluation:
    node_visibility: tuple[bool, ...]
    node_appearance_indices: tuple[int | None, ...]
    camera_parent_indices: tuple[int | None, ...]


def _text(value: Any) -> bytes:
    return str(value).encode("utf-8")


@lru_cache(maxsize=1)
def _library() -> C.CDLL:
    lib = _load_library()
    lib.cadflow_evaluate_presentation.argtypes = [
        C.c_char_p,
        C.c_char_p,
        C.POINTER(_Appearance),
        C.c_size_t,
        C.POINTER(_SceneNode),
        C.c_size_t,
        C.POINTER(_NodeOverride),
        C.c_size_t,
        C.POINTER(_Camera),
        C.c_size_t,
        C.POINTER(C.c_int),
        C.POINTER(C.c_size_t),
        C.POINTER(C.c_size_t),
    ]
    lib.cadflow_evaluate_presentation.restype = C.c_int
    lib.cadflow_last_error.restype = C.c_char_p
    return lib


def evaluate_presentation_native(
    *,
    presentation_source_scene_id: str,
    scene_id: str,
    appearances: Sequence[Mapping[str, Any]],
    nodes: Sequence[Mapping[str, Any]],
    overrides: Sequence[Mapping[str, Any]],
    cameras: Sequence[Mapping[str, Any]],
) -> NativePresentationEvaluation:
    """Resolve validated Presentation records against validated scene records."""

    encoded_appearance_names = [_text(item["name"]) for item in appearances]
    native_appearances = (_Appearance * len(appearances))(
        *(
            _Appearance(
                encoded_appearance_names[index],
                (C.c_double * 4)(*map(float, item["base_color"])),
                float(item["metallic"]),
                float(item["roughness"]),
                {"opaque": 0, "mask": 1, "blend": 2}[str(item["alpha_mode"])],
                int(bool(item["double_sided"])),
                (C.c_double * 4)(*map(float, item["edge_color"])),
            )
            for index, item in enumerate(appearances)
        )
    )

    encoded_node_ids = [_text(item["node_id"]) for item in nodes]
    native_nodes = (_SceneNode * len(nodes))(
        *(
            _SceneNode(
                encoded_node_ids[index],
                int(bool(item["appearance_capable"])),
                int(bool(item.get("visible", True))),
            )
            for index, item in enumerate(nodes)
        )
    )

    encoded_override_node_ids = [_text(item["node_id"]) for item in overrides]
    encoded_override_appearances = [
        _text(item["appearance_name"])
        if item.get("appearance_name") is not None
        else None
        for item in overrides
    ]
    native_overrides = (_NodeOverride * len(overrides))(
        *(
            _NodeOverride(
                encoded_override_node_ids[index],
                int("visible" in item),
                int(bool(item.get("visible", False))),
                encoded_override_appearances[index],
            )
            for index, item in enumerate(overrides)
        )
    )

    encoded_camera_names = [_text(item["name"]) for item in cameras]
    encoded_camera_parents = [
        _text(item["parent_node_id"])
        if item.get("parent_node_id") is not None
        else None
        for item in cameras
    ]
    native_cameras = (_Camera * len(cameras))(
        *(
            _Camera(
                encoded_camera_names[index],
                encoded_camera_parents[index],
                0 if item["projection"] == "perspective" else 1,
                float(item["near"]),
                float(item["far"]),
                float(
                    item["vertical_fov_degrees"]
                    if item["projection"] == "perspective"
                    else item["vertical_span"]
                ),
            )
            for index, item in enumerate(cameras)
        )
    )

    visibility = (C.c_int * len(nodes))()
    appearance_indices = (C.c_size_t * len(nodes))()
    camera_parent_indices = (C.c_size_t * len(cameras))()
    lib = _library()
    ok = lib.cadflow_evaluate_presentation(
        _text(presentation_source_scene_id),
        _text(scene_id),
        native_appearances,
        len(native_appearances),
        native_nodes,
        len(native_nodes),
        native_overrides,
        len(native_overrides),
        native_cameras,
        len(native_cameras),
        visibility,
        appearance_indices,
        camera_parent_indices,
    )
    error = lib.cadflow_last_error()
    if not ok or error:
        message = error.decode("utf-8", "replace") if error else "native presentation evaluation failed"
        raise NativeError(message)
    return NativePresentationEvaluation(
        node_visibility=tuple(bool(value) for value in visibility),
        node_appearance_indices=tuple(
            None if value == _UNSET_INDEX else int(value)
            for value in appearance_indices
        ),
        camera_parent_indices=tuple(
            None if value == _UNSET_INDEX else int(value)
            for value in camera_parent_indices
        ),
    )


__all__ = ["NativePresentationEvaluation", "evaluate_presentation_native"]
