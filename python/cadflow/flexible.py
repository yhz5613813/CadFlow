"""Static modeling tools for flexible surfaces and thin garment shells.

This module deliberately describes geometry, not motion.  A panel is a control
surface with explicit sampling density; a model is a collection of such panels
that can be exported as one indexed triangle mesh.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ._flexible_native import FlexibleNativeError, build_shell_mesh


def _finite_array(value: object, shape: tuple[int, ...], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {result.shape}")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain only finite values")
    return np.ascontiguousarray(result)


@dataclass(frozen=True)
class FlexibleMaterial:
    """Static shell properties used for thickness and appearance metadata."""

    name: str = "stretch-knit"
    thickness: float = 1.2
    color: tuple[float, float, float] = (0.17, 0.34, 0.52)
    roughness: float = 0.68

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("material name must not be empty")
        if not math.isfinite(float(self.thickness)) or self.thickness < 0.0:
            raise ValueError("material thickness must be finite and non-negative")
        color = _finite_array(self.color, (3,), "material color")
        if np.any(color < 0.0) or np.any(color > 1.0):
            raise ValueError("material color channels must be between 0 and 1")
        if not math.isfinite(float(self.roughness)) or not 0.0 <= self.roughness <= 1.0:
            raise ValueError("material roughness must be between 0 and 1")
        object.__setattr__(self, "color", tuple(float(value) for value in color))
        object.__setattr__(self, "thickness", float(self.thickness))
        object.__setattr__(self, "roughness", float(self.roughness))


@dataclass(frozen=True)
class FlexiblePanel:
    """One static flexible panel represented by a rectangular control grid."""

    name: str
    control_points: Sequence[Sequence[Sequence[float]]]
    sample_rows: int = 12
    sample_columns: int = 12
    periodic_columns: bool = False
    material: FlexibleMaterial = field(default_factory=FlexibleMaterial)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("panel name must not be empty")
        controls = np.asarray(self.control_points, dtype=np.float64)
        if controls.ndim != 3 or controls.shape[2] != 3:
            raise ValueError("control_points must have shape (rows, columns, 3)")
        if controls.shape[0] < 2 or controls.shape[1] < 2:
            raise ValueError("control_points must contain at least a 2 by 2 grid")
        if self.periodic_columns and controls.shape[1] < 3:
            raise ValueError("periodic panels require at least three control columns")
        if not np.all(np.isfinite(controls)):
            raise ValueError("control_points must contain only finite values")
        for name, value, minimum in (
            ("sample_rows", self.sample_rows, controls.shape[0]),
            ("sample_columns", self.sample_columns, controls.shape[1]),
        ):
            if int(value) != value or int(value) < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        object.__setattr__(self, "control_points", np.ascontiguousarray(controls))
        object.__setattr__(self, "sample_rows", int(self.sample_rows))
        object.__setattr__(self, "sample_columns", int(self.sample_columns))

    @property
    def control_rows(self) -> int:
        return int(self.control_points.shape[0])

    @property
    def control_columns(self) -> int:
        return int(self.control_points.shape[1])

    def build(self) -> "FlexiblePanelMesh":
        vertices, normals, triangles = build_shell_mesh(
            self.control_points,
            self.sample_rows,
            self.sample_columns,
            self.periodic_columns,
            self.material.thickness,
        )
        return FlexiblePanelMesh(
            name=self.name,
            vertices=vertices,
            normals=normals,
            triangles=triangles,
            material=self.material,
        )


@dataclass(frozen=True)
class FlexiblePanelMesh:
    name: str
    vertices: np.ndarray
    normals: np.ndarray
    triangles: np.ndarray
    material: FlexibleMaterial

    def __post_init__(self) -> None:
        vertices = _finite_array(self.vertices, (len(self.vertices), 3), "vertices")
        normals = _finite_array(self.normals, vertices.shape, "normals")
        triangles = np.asarray(self.triangles, dtype=np.uint32)
        if triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("triangles must have shape (M, 3)")
        if len(triangles) and int(triangles.max()) >= len(vertices):
            raise ValueError("triangle index is out of range")
        lengths = np.linalg.norm(normals, axis=1)
        if not np.allclose(lengths, 1.0, atol=1e-5):
            raise ValueError("normals must be unit length")
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "normals", normals)
        object.__setattr__(self, "triangles", np.ascontiguousarray(triangles))

    @property
    def vertex_count(self) -> int:
        return int(len(self.vertices))

    @property
    def triangle_count(self) -> int:
        return int(len(self.triangles))

    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return (
            tuple(float(value) for value in self.vertices.min(axis=0)),
            tuple(float(value) for value in self.vertices.max(axis=0)),
        )


@dataclass(frozen=True)
class FlexiblePanelRange:
    name: str
    vertex_start: int
    vertex_count: int
    triangle_start: int
    triangle_count: int
    material: FlexibleMaterial


@dataclass(frozen=True)
class FlexibleMesh:
    vertices: np.ndarray
    normals: np.ndarray
    triangles: np.ndarray
    panels: tuple[FlexiblePanelRange, ...]

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices, dtype=np.float64)
        normals = np.asarray(self.normals, dtype=np.float64)
        triangles = np.asarray(self.triangles, dtype=np.uint32)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
            raise ValueError("vertices must have shape (N, 3) with N > 0")
        if normals.shape != vertices.shape:
            raise ValueError("normals must have the same shape as vertices")
        if triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) == 0:
            raise ValueError("triangles must have shape (M, 3) with M > 0")
        if not np.all(np.isfinite(vertices)) or not np.all(np.isfinite(normals)):
            raise ValueError("vertices and normals must be finite")
        if int(triangles.max()) >= len(vertices):
            raise ValueError("triangle index is out of range")
        object.__setattr__(self, "vertices", np.ascontiguousarray(vertices))
        object.__setattr__(self, "normals", np.ascontiguousarray(normals))
        object.__setattr__(self, "triangles", np.ascontiguousarray(triangles))

    @property
    def vertex_count(self) -> int:
        return int(len(self.vertices))

    @property
    def triangle_count(self) -> int:
        return int(len(self.triangles))

    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return (
            tuple(float(value) for value in self.vertices.min(axis=0)),
            tuple(float(value) for value in self.vertices.max(axis=0)),
        )

    @property
    def surface_area(self) -> float:
        points = self.vertices[self.triangles]
        cross_products = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
        return float(0.5 * np.linalg.norm(cross_products, axis=1).sum())

    @property
    def is_watertight(self) -> bool:
        edges = np.concatenate(
            (
                self.triangles[:, [0, 1]],
                self.triangles[:, [1, 2]],
                self.triangles[:, [2, 0]],
            ),
            axis=0,
        )
        edges.sort(axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        return bool(np.all(counts == 2))

    def write_obj(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            handle.write("# CadFlow flexible static shell mesh\n")
            for vertex in self.vertices:
                handle.write("v " + " ".join(f"{float(value):.9g}" for value in vertex) + "\n")
            for normal in self.normals:
                handle.write("vn " + " ".join(f"{float(value):.9g}" for value in normal) + "\n")
            for panel in self.panels:
                handle.write(f"g {panel.name}\n")
                panel_triangles = self.triangles[
                    panel.triangle_start : panel.triangle_start + panel.triangle_count
                ]
                for left, right, third in panel_triangles:
                    a, b, c = (int(left) + 1, int(right) + 1, int(third) + 1)
                    handle.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")
        return destination

    def write_stl(self, path: str | Path) -> Path:
        """Write a binary STL containing the complete static shell model."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        header = b"CadFlow flexible static shell mesh".ljust(80, b"\0")
        with destination.open("wb") as handle:
            handle.write(header)
            handle.write(struct.pack("<I", self.triangle_count))
            points = self.vertices[self.triangles]
            face_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
            lengths = np.linalg.norm(face_normals, axis=1)
            face_normals[lengths > 0.0] /= lengths[lengths > 0.0, None]
            for normal, triangle in zip(face_normals, points):
                values = np.concatenate((normal, triangle.reshape(-1))).astype("<f4")
                handle.write(values.tobytes())
                handle.write(struct.pack("<H", 0))
        return destination

    def write_json(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "vertex_count": self.vertex_count,
            "triangle_count": self.triangle_count,
            "panels": [
                {
                    "name": panel.name,
                    "vertex_start": panel.vertex_start,
                    "vertex_count": panel.vertex_count,
                    "triangle_start": panel.triangle_start,
                    "triangle_count": panel.triangle_count,
                    "material": {
                        "name": panel.material.name,
                        "thickness": panel.material.thickness,
                        "color": list(panel.material.color),
                        "roughness": panel.material.roughness,
                    },
                }
                for panel in self.panels
            ],
            "bounds": [list(self.bounds[0]), list(self.bounds[1])],
            "surface_area": self.surface_area,
            "watertight": self.is_watertight,
        }
        destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return destination


class FlexibleModel:
    """Collection of static panels with deterministic indexed concatenation."""

    def __init__(self, name: str = "flexible-model") -> None:
        if not name.strip():
            raise ValueError("model name must not be empty")
        self.name = name
        self._panels: list[FlexiblePanel] = []

    @property
    def panels(self) -> tuple[FlexiblePanel, ...]:
        return tuple(self._panels)

    def add_panel(self, panel: FlexiblePanel) -> FlexiblePanel:
        if not isinstance(panel, FlexiblePanel):
            raise TypeError("add_panel expects a FlexiblePanel")
        if any(existing.name == panel.name for existing in self._panels):
            raise ValueError(f"duplicate panel name: {panel.name}")
        self._panels.append(panel)
        return panel

    def build(self) -> FlexibleMesh:
        if not self._panels:
            raise ValueError("flexible model has no panels")
        meshes = [panel.build() for panel in self._panels]
        vertices: list[np.ndarray] = []
        normals: list[np.ndarray] = []
        triangles: list[np.ndarray] = []
        panel_ranges: list[FlexiblePanelRange] = []
        vertex_offset = 0
        triangle_offset = 0
        for mesh in meshes:
            vertices.append(mesh.vertices)
            normals.append(mesh.normals)
            triangles.append(mesh.triangles.astype(np.uint64) + vertex_offset)
            panel_ranges.append(
                FlexiblePanelRange(
                    name=mesh.name,
                    vertex_start=vertex_offset,
                    vertex_count=mesh.vertex_count,
                    triangle_start=triangle_offset,
                    triangle_count=mesh.triangle_count,
                    material=mesh.material,
                )
            )
            vertex_offset += mesh.vertex_count
            triangle_offset += mesh.triangle_count
        return FlexibleMesh(
            vertices=np.ascontiguousarray(np.concatenate(vertices, axis=0)),
            normals=np.ascontiguousarray(np.concatenate(normals, axis=0)),
            triangles=np.ascontiguousarray(np.concatenate(triangles, axis=0).astype(np.uint32)),
            panels=tuple(panel_ranges),
        )


@dataclass(frozen=True)
class RingSection:
    """Static elliptical garment section in an arbitrary 3D plane."""

    center: Sequence[float]
    axis_u: Sequence[float]
    axis_v: Sequence[float]
    radius_u: float
    radius_v: float
    wrinkle_amplitude: float = 0.0
    wrinkle_count: int = 6
    wrinkle_phase: float = 0.0

    def __post_init__(self) -> None:
        center = _finite_array(self.center, (3,), "section center")
        axis_u = _finite_array(self.axis_u, (3,), "section axis_u")
        axis_v = _finite_array(self.axis_v, (3,), "section axis_v")
        length_u = float(np.linalg.norm(axis_u))
        length_v = float(np.linalg.norm(axis_v))
        if length_u <= 1e-12 or length_v <= 1e-12:
            raise ValueError("section axes must be non-zero")
        unit_u = axis_u / length_u
        unit_v = axis_v / length_v
        if abs(float(np.dot(unit_u, unit_v))) > 1e-6:
            raise ValueError("section axes must be orthogonal")
        for name, value in (("radius_u", self.radius_u), ("radius_v", self.radius_v)):
            if not math.isfinite(float(value)) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(float(self.wrinkle_amplitude)) or not 0.0 <= self.wrinkle_amplitude < 0.5:
            raise ValueError("wrinkle_amplitude must be in [0, 0.5)")
        if int(self.wrinkle_count) != self.wrinkle_count or self.wrinkle_count < 1:
            raise ValueError("wrinkle_count must be a positive integer")
        if not math.isfinite(float(self.wrinkle_phase)):
            raise ValueError("wrinkle_phase must be finite")
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "axis_u", unit_u)
        object.__setattr__(self, "axis_v", unit_v)
        object.__setattr__(self, "radius_u", float(self.radius_u))
        object.__setattr__(self, "radius_v", float(self.radius_v))
        object.__setattr__(self, "wrinkle_amplitude", float(self.wrinkle_amplitude))
        object.__setattr__(self, "wrinkle_count", int(self.wrinkle_count))
        object.__setattr__(self, "wrinkle_phase", float(self.wrinkle_phase))

    def points(self, columns: int) -> np.ndarray:
        if int(columns) != columns or columns < 3:
            raise ValueError("section columns must be an integer >= 3")
        angles = 2.0 * np.pi * np.arange(columns, dtype=np.float64) / columns
        primary = np.sin(self.wrinkle_count * angles + self.wrinkle_phase)
        secondary = np.sin(
            (self.wrinkle_count + 3) * angles - self.wrinkle_phase * 0.61
        )
        fold = 1.0 + self.wrinkle_amplitude * (0.68 * primary + 0.32 * secondary)
        return np.ascontiguousarray(
            self.center
            + np.outer(self.radius_u * fold * np.cos(angles), self.axis_u)
            + np.outer(self.radius_v * fold * np.sin(angles), self.axis_v)
        )


def sectioned_panel(
    name: str,
    sections: Iterable[RingSection],
    *,
    control_columns: int = 20,
    sample_rows: int = 40,
    sample_columns: int = 64,
    material: FlexibleMaterial | None = None,
) -> FlexiblePanel:
    """Build a periodic garment panel from designed static cross-sections."""
    section_values = tuple(sections)
    if len(section_values) < 2:
        raise ValueError("sectioned_panel requires at least two sections")
    if int(control_columns) != control_columns or control_columns < 3:
        raise ValueError("control_columns must be an integer >= 3")
    controls = np.stack(
        [section.points(int(control_columns)) for section in section_values], axis=0
    )
    return FlexiblePanel(
        name=name,
        control_points=controls,
        sample_rows=sample_rows,
        sample_columns=sample_columns,
        periodic_columns=True,
        material=material or FlexibleMaterial(),
    )


__all__ = [
    "FlexibleMaterial",
    "FlexibleMesh",
    "FlexibleModel",
    "FlexibleNativeError",
    "FlexiblePanel",
    "FlexiblePanelMesh",
    "FlexiblePanelRange",
    "RingSection",
    "sectioned_panel",
]
