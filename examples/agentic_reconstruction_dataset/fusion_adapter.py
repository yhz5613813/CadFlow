"""Adapter from Fusion 360 Gallery reconstruction records to CadFlow calls."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

import cadflow as cad
from cadflow import ql


Vector3 = tuple[float, float, float]
CM_TO_KERNEL_LENGTH = 10.0
KERNEL_VOLUME_TO_CM3 = 1.0 / 1000.0


def _vector(data: dict[str, Any]) -> Vector3:
    return (float(data["x"]), float(data["y"]), float(data["z"]))


def _add(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a + b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _scale(vector: Vector3, factor: float) -> Vector3:
    return tuple(value * factor for value in vector)  # type: ignore[return-value]


def _distance(left: Vector3, right: Vector3) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return str(value)


class FusionReconstructionDesign:
    """Parsed source design with stable feature and artifact lookup."""

    def __init__(self, source_json: str | Path) -> None:
        self.source_json = Path(source_json).resolve()
        self.data = json.loads(self.source_json.read_text(encoding="utf-8"))
        self.entities: dict[str, dict[str, Any]] = self.data["entities"]
        self.sequence_by_entity = {
            item["entity"]: item
            for item in self.data.get("sequence", [])
            if item.get("type") == "ExtrudeFeature"
        }

    def entity(self, entity_id: str) -> dict[str, Any]:
        try:
            return self.entities[entity_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Fusion entity UUID: {entity_id}") from exc

    def feature_plan(self) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for timeline_item in sorted(self.data["timeline"], key=lambda item: item["index"]):
            entity_id = timeline_item["entity"]
            entity = self.entity(entity_id)
            if entity["type"] != "ExtrudeFeature":
                continue
            profile_refs = entity.get("profiles", [])
            if not profile_refs:
                raise ValueError(f"Extrude feature {entity_id} has no selected profiles")
            profile_ref = profile_refs[0]
            sketch = self.entity(profile_ref["sketch"])
            sequence_item = self.sequence_by_entity.get(entity_id, {})
            extent = entity["extent_one"]
            plan.append(
                {
                    "timeline_index": timeline_item["index"],
                    "sequence_index": sequence_item.get("index"),
                    "sketch_id": profile_ref["sketch"],
                    "sketch_name": sketch["name"],
                    "profile_id": profile_ref["profile"],
                    "extrude_id": entity_id,
                    "extrude_name": entity["name"],
                    "operation": entity["operation"],
                    "extent_type": entity["extent_type"],
                    "distance_cm": float(extent["distance"]["value"]),
                    "taper_angle_rad": float(extent["taper_angle"]["value"]),
                    "source_step": sequence_item.get("step"),
                    "source_png": sequence_item.get("png"),
                    "profile_refs": [
                        {
                            "sketch_id": ref["sketch"],
                            "profile_id": ref["profile"],
                        }
                        for ref in profile_refs
                    ],
                }
            )
        return plan

    def summary(self) -> dict[str, Any]:
        curve_types: dict[str, int] = {}
        ignored_reference_curves = 0
        ignored_construction_curves = 0
        for entity in self.entities.values():
            if entity["type"] != "Sketch":
                continue
            for curve in entity.get("curves", {}).values():
                curve_type = curve["type"]
                curve_types[curve_type] = curve_types.get(curve_type, 0) + 1
                ignored_reference_curves += int(bool(curve.get("reference")))
                ignored_construction_curves += int(bool(curve.get("construction_geom")))
        return {
            "source_json": str(self.source_json),
            "units": {
                "source_length": "cm",
                "source_angle": "radian",
                "cadflow_step_length": "mm",
                "cm_to_cadflow_scale": CM_TO_KERNEL_LENGTH,
            },
            "timeline_items": len(self.data["timeline"]),
            "feature_count": len(self.feature_plan()),
            "curve_types": curve_types,
            "ignored_non_profile_geometry": {
                "reference_curves": ignored_reference_curves,
                "construction_curves": ignored_construction_curves,
            },
            "feature_plan": self.feature_plan(),
        }

    def world_point(self, sketch_id: str, local_point: dict[str, Any]) -> Vector3:
        sketch = self.entity(sketch_id)
        transform = sketch["transform"]
        origin = _vector(transform["origin"])
        x_axis = _vector(transform["x_axis"])
        y_axis = _vector(transform["y_axis"])
        z_axis = _vector(transform["z_axis"])
        point = _vector(local_point)
        world_cm = _add(
            origin,
            _add(
                _scale(x_axis, point[0]),
                _add(_scale(y_axis, point[1]), _scale(z_axis, point[2])),
            ),
        )
        return _scale(world_cm, CM_TO_KERNEL_LENGTH)

    def sketch_normal(self, sketch_id: str) -> Vector3:
        return _vector(self.entity(sketch_id)["transform"]["z_axis"])


class CadFlowFusionAdapter:
    """Stateful tool runtime that lowers Fusion features to CadFlow."""

    def __init__(self, design: FusionReconstructionDesign) -> None:
        self.design = design
        self.profiles: dict[str, Any] = {}
        self.profile_normals: dict[str, Vector3] = {}
        self.solids: dict[str, Any] = {}
        self.current: Any | None = None
        self.current_handle: str | None = None

    def _ordered_line_segments(
        self, sketch_id: str, profile_curves: Iterable[dict[str, Any]]
    ) -> list[tuple[Vector3, Vector3]]:
        segments = [
            (
                self.design.world_point(sketch_id, curve["start_point"]),
                self.design.world_point(sketch_id, curve["end_point"]),
            )
            for curve in profile_curves
        ]
        if not segments:
            raise ValueError("Fusion profile loop has no curves")
        ordered = [segments.pop(0)]
        while segments:
            endpoint = ordered[-1][1]
            for index, (start, end) in enumerate(segments):
                if _distance(endpoint, start) <= 1.0e-6:
                    ordered.append((start, end))
                    segments.pop(index)
                    break
                if _distance(endpoint, end) <= 1.0e-6:
                    ordered.append((end, start))
                    segments.pop(index)
                    break
            else:
                raise ValueError("Fusion profile curves do not form one connected loop")
        if _distance(ordered[-1][1], ordered[0][0]) > 1.0e-6:
            raise ValueError("Fusion profile loop is not closed")
        return ordered

    @cad.requires_session
    def _make_loop_wire(self, sketch_id: str, loop: dict[str, Any]) -> Any:
        profile_curves = loop["profile_curves"]
        unsupported = sorted(
            {curve["type"] for curve in profile_curves if curve["type"] != "Line3D"}
        )
        if unsupported:
            raise NotImplementedError(
                "This executable example supports Line3D profile loops only; "
                f"unsupported profile carriers: {unsupported}"
            )
        segments = self._ordered_line_segments(sketch_id, profile_curves)
        edges = [
            cad.make_line_redge(start=start, end=end) for start, end in segments
        ]
        return cad.make_wire_from_edges_rwire(edges=edges)

    def create_profile(self, *, sketch_id: str, profile_id: str) -> dict[str, Any]:
        sketch = self.design.entity(sketch_id)
        try:
            profile = sketch["profiles"][profile_id]
        except KeyError as exc:
            raise KeyError(
                f"Sketch {sketch_id} does not contain profile {profile_id}"
            ) from exc
        loops = profile["loops"]
        outer_loops = [loop for loop in loops if loop["is_outer"]]
        inner_loops = [loop for loop in loops if not loop["is_outer"]]
        if len(outer_loops) != 1:
            raise NotImplementedError(
                f"Expected one outer loop, found {len(outer_loops)}"
            )
        outer_wire = self._make_loop_wire(sketch_id, outer_loops[0])
        inner_wires = [self._make_loop_wire(sketch_id, loop) for loop in inner_loops]
        normal = self.design.sketch_normal(sketch_id)
        face = cad.make_face_from_wires_rface(
            outer_wire=outer_wire,
            inner_wires=inner_wires,
            normal=normal,
        )
        handle = f"profile_{len(self.profiles) + 1}"
        self.profiles[handle] = face
        self.profile_normals[handle] = normal
        return {
            "profile_handle": handle,
            "loop_count": len(loops),
            "outer_loop_count": len(outer_loops),
            "inner_loop_count": len(inner_loops),
            "normal": list(normal),
            "area_cm2": float(profile["properties"]["area"]),
            "adapter": {
                "local_to_world": "Fusion sketch transform basis",
                "profile_selection": "Fusion trimmed profile loops",
                "ignored": "construction and reference curves outside selected profile",
            },
            "backend_calls": [
                "make_line_redge",
                "make_wire_from_edges_rwire",
                "make_face_from_wires_rface",
            ],
        }

    def extrude_profile(
        self,
        *,
        profile_handle: str,
        solid_handle: str,
        distance_cm: float,
        extent_type: str,
    ) -> dict[str, Any]:
        profile = self.profiles[profile_handle]
        normal = self.profile_normals[profile_handle]
        distance = float(distance_cm)
        if math.isclose(distance, 0.0, abs_tol=1.0e-12):
            raise ValueError("Extrude distance must be non-zero")
        direction = normal if distance > 0 else _scale(normal, -1.0)
        length_cm = abs(distance)
        length_kernel = length_cm * CM_TO_KERNEL_LENGTH
        solid = cad.extrude_rsolid(
            profile=profile,
            direction=direction,
            distance=length_kernel,
            result_tag="role.feature.tool",
        )
        backend_calls = ["extrude_rsolid"]
        adapter: dict[str, Any] | None = None
        if extent_type == "SymmetricFeatureExtentType":
            offset = _scale(direction, -0.5 * length_kernel)
            solid = cad.translate_shape(shape=solid, vector=offset)
            backend_calls.append("translate_shape")
            adapter = {
                "lowering": "symmetric = one-sided total-length extrusion + half-length negative translation",
                "translation_mm": list(offset),
            }
        elif extent_type != "OneSideFeatureExtentType":
            raise NotImplementedError(f"Unsupported Fusion extent type: {extent_type}")
        self.solids[solid_handle] = solid
        return {
            "solid_handle": solid_handle,
            "distance_cm": length_cm,
            "distance_mm": length_kernel,
            "direction": list(direction),
            "extent_type": extent_type,
            "volume_cm3": solid.get_volume() * KERNEL_VOLUME_TO_CM3,
            "adapter": adapter,
            "backend_calls": backend_calls,
        }

    def apply_feature(
        self, *, feature_handle: str | Iterable[str], operation: str
    ) -> dict[str, Any]:
        handles = [feature_handle] if isinstance(feature_handle, str) else list(feature_handle)
        if not handles:
            raise ValueError("At least one feature handle is required")
        features = [self.solids[handle] for handle in handles]
        backend_call: str
        if operation == "NewBodyFeatureOperation":
            if self.current is not None:
                raise NotImplementedError(
                    "Multiple Fusion bodies are outside this single-body example"
                )
            self.current = features[0]
            if len(features) > 1:
                for feature in features[1:]:
                    self.current = cad.union_rsolid(self.current, feature)
            backend_call = "set_current_body"
        elif operation == "JoinFeatureOperation":
            if self.current is None:
                raise RuntimeError("Join requires an existing current body")
            for feature in features:
                self.current = cad.union_rsolid(
                    self.current,
                    feature,
                    clean=True,
                    tol=1.0e-6,
                )
            backend_call = "union_rsolid"
        elif operation == "CutFeatureOperation":
            if self.current is None:
                raise RuntimeError("Cut requires an existing current body")
            for feature in features:
                self.current = cad.cut_rsolid(
                    self.current,
                    feature,
                    skip_non_intersecting=False,
                )
            backend_call = "cut_rsolid"
        else:
            raise NotImplementedError(f"Unsupported Fusion operation: {operation}")
        self.current_handle = "current_body"
        return {
            "current_handle": self.current_handle,
            "operation": operation,
            "volume_cm3": self.current.get_volume() * KERNEL_VOLUME_TO_CM3,
            "backend_call": backend_call,
        }

    def inspect_current(self) -> dict[str, Any]:
        if self.current is None:
            raise RuntimeError("No current body to inspect")
        faces = ql.faces().resolve(self.current)
        edges = ql.edges().resolve(self.current)
        vertices = ql.vertices().resolve(self.current)
        result = {
            "current_handle": self.current_handle,
            "volume_cm3": self.current.get_volume() * KERNEL_VOLUME_TO_CM3,
            "face_count": len(faces),
            "edge_count": len(edges),
            "vertex_count": len(vertices),
            "grounding": "CadFlow ql.faces/edges/vertices",
        }
        print(
            "grounding",
            f"volume={result['volume_cm3']:.9f}",
            f"faces={result['face_count']}",
            f"edges={result['edge_count']}",
        )
        return result

    def require_current(self) -> Any:
        if self.current is None:
            raise RuntimeError("No reconstructed body is available")
        return self.current


def json_safe(value: Any) -> Any:
    """Normalize CadFlow inspection values for JSON artifacts."""

    return _json_safe(value)
