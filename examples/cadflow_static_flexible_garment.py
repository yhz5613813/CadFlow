"""Build and render a high-density static flexible jumpsuit model."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from cadflow.flexible import (
    FlexibleMaterial,
    FlexibleMesh,
    FlexibleModel,
    RingSection,
    sectioned_panel,
)


OUT = Path(__file__).resolve().parent / "out" / "cadflow_static_flexible_garment"
PNG_PATH = OUT / "flexible_garment_views.png"
OBJ_PATH = OUT / "flexible_garment.obj"
STL_PATH = OUT / "flexible_garment.stl"
JSON_PATH = OUT / "flexible_garment.json"

FABRIC = FlexibleMaterial(
    name="navy stretch twill",
    thickness=3.0,
    color=(0.10, 0.25, 0.39),
    roughness=0.72,
)


def _vertical_section(
    z: float,
    center_x: float,
    radius_x: float,
    radius_y: float,
    *,
    wrinkle: float,
    phase: float,
) -> RingSection:
    return RingSection(
        center=(center_x, 0.0, z),
        axis_u=(1.0, 0.0, 0.0),
        axis_v=(0.0, 1.0, 0.0),
        radius_u=radius_x,
        radius_v=radius_y,
        wrinkle_amplitude=wrinkle,
        wrinkle_count=7,
        wrinkle_phase=phase,
    )


def _sleeve_section(
    x: float,
    z: float,
    radius_y: float,
    radius_z: float,
    *,
    phase: float,
) -> RingSection:
    return RingSection(
        center=(x, 0.0, z),
        axis_u=(0.0, 1.0, 0.0),
        axis_v=(0.0, 0.0, 1.0),
        radius_u=radius_y,
        radius_v=radius_z,
        wrinkle_amplitude=0.018,
        wrinkle_count=6,
        wrinkle_phase=phase,
    )


def build_garment() -> FlexibleMesh:
    model = FlexibleModel("short-sleeve jumpsuit")
    model.add_panel(
        sectioned_panel(
            "torso",
            (
                _vertical_section(790, 0, 270, 155, wrinkle=0.018, phase=0.0),
                _vertical_section(900, 0, 286, 165, wrinkle=0.018, phase=0.3),
                _vertical_section(1020, 0, 252, 148, wrinkle=0.022, phase=0.6),
                _vertical_section(1190, 0, 305, 167, wrinkle=0.024, phase=0.9),
                _vertical_section(1390, 0, 332, 178, wrinkle=0.018, phase=1.2),
                _vertical_section(1515, 0, 310, 166, wrinkle=0.014, phase=1.5),
                _vertical_section(1590, 0, 142, 94, wrinkle=0.010, phase=1.8),
            ),
            control_columns=24,
            sample_rows=52,
            sample_columns=84,
            material=FABRIC,
        )
    )

    for side, sign in (("left", -1.0), ("right", 1.0)):
        model.add_panel(
            sectioned_panel(
                f"{side}_leg",
                (
                    _vertical_section(40, sign * 205, 178, 122, wrinkle=0.030, phase=0.1),
                    _vertical_section(160, sign * 203, 174, 127, wrinkle=0.030, phase=0.5),
                    _vertical_section(390, sign * 190, 162, 137, wrinkle=0.025, phase=0.9),
                    _vertical_section(610, sign * 171, 145, 145, wrinkle=0.022, phase=1.3),
                    _vertical_section(745, sign * 151, 132, 150, wrinkle=0.018, phase=1.7),
                    _vertical_section(840, sign * 134, 146, 151, wrinkle=0.016, phase=2.1),
                ),
                control_columns=20,
                sample_rows=44,
                sample_columns=64,
                material=FABRIC,
            )
        )

        shoulder = sign * 150.0
        outer = sign * 555.0
        sleeve_sections = (
            _sleeve_section(shoulder, 1435, 170, 195, phase=0.0),
            _sleeve_section(sign * 315, 1420, 160, 162, phase=0.45),
            _sleeve_section(sign * 445, 1390, 142, 143, phase=0.9),
            _sleeve_section(outer, 1350, 125, 128, phase=1.35),
        )
        if sign < 0.0:
            sleeve_sections = tuple(reversed(sleeve_sections))
        model.add_panel(
            sectioned_panel(
                f"{side}_sleeve",
                sleeve_sections,
                control_columns=18,
                sample_rows=30,
                sample_columns=56,
                material=FABRIC,
            )
        )
    return model.build()


def _outer_faces(mesh: FlexibleMesh) -> np.ndarray:
    outer_triangles = []
    for panel in mesh.panels:
        grid_vertices = (
            panel.vertex_count
            if panel.material.thickness == 0.0
            else panel.vertex_count // 2
        )
        panel_triangles = mesh.triangles[
            panel.triangle_start : panel.triangle_start + panel.triangle_count
        ]
        is_outer = np.all(
            (panel_triangles >= panel.vertex_start)
            & (panel_triangles < panel.vertex_start + grid_vertices),
            axis=1,
        )
        outer_triangles.extend(panel_triangles[is_outer])
    return mesh.vertices[np.asarray(outer_triangles, dtype=np.uint32)]


def _face_colors(faces: np.ndarray) -> np.ndarray:
    face_normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    normal_lengths = np.linalg.norm(face_normals, axis=1)
    valid = normal_lengths > 0.0
    face_normals[valid] /= normal_lengths[valid, None]
    light = np.array((0.25, -0.45, 0.86), dtype=float)
    light /= np.linalg.norm(light)
    intensity = np.clip(0.42 + 0.55 * np.abs(face_normals @ light), 0.32, 0.98)
    base_color = np.array((0.10, 0.31, 0.43), dtype=float)
    return np.column_stack(
        (np.clip(intensity[:, None] * base_color, 0.0, 1.0), np.full(len(faces), 0.98))
    )


def _render_orthographic(
    axis,
    faces: np.ndarray,
    colors: np.ndarray,
    *,
    horizontal_axis: int,
    vertical_axis: int,
    depth_axis: int,
    depth_ascending: bool,
    title: str,
) -> None:
    order = np.argsort(faces[:, :, depth_axis].mean(axis=1))
    if not depth_ascending:
        order = order[::-1]
    polygons = faces[order][:, :, [horizontal_axis, vertical_axis]]
    collection = PolyCollection(
        polygons,
        facecolors=colors[order],
        edgecolors="#163747",
        linewidths=0.05,
    )
    axis.add_collection(collection)
    lower = polygons.reshape((-1, 2)).min(axis=0)
    upper = polygons.reshape((-1, 2)).max(axis=0)
    margin = np.maximum((upper - lower) * 0.06, 1.0)
    axis.set_xlim(lower[0] - margin[0], upper[0] + margin[0])
    axis.set_ylim(lower[1] - margin[1], upper[1] + margin[1])
    axis.set_aspect("equal", adjustable="box")
    axis.set_title(title, fontsize=11)
    axis.set_axis_off()


def _render_perspective(axis, mesh: FlexibleMesh, faces: np.ndarray, colors: np.ndarray) -> None:
    collection = Poly3DCollection(
        faces,
        facecolors=colors,
        edgecolor="#163747",
        linewidth=0.08,
        alpha=0.96,
    )
    axis.add_collection3d(collection)
    lower = mesh.vertices.min(axis=0)
    upper = mesh.vertices.max(axis=0)
    center = 0.5 * (lower + upper)
    radius = 0.53 * float(np.max(upper - lower))
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[1] - radius, center[1] + radius)
    axis.set_zlim(max(0.0, center[2] - radius), center[2] + radius)
    axis.set_box_aspect((1.0, 0.55, 1.45))
    axis.set_proj_type("persp")
    axis.view_init(elev=18, azim=-60)
    axis.set_title("Geometry", fontsize=11)
    axis.set_axis_off()


def render_garment(mesh: FlexibleMesh, output_path: Path = PNG_PATH) -> Path:
    fig = plt.figure(figsize=(13.5, 8.8), dpi=150, facecolor="#f6f7f8")
    faces = _outer_faces(mesh)
    colors = _face_colors(faces)
    views = (
        (0, 2, 1, False, "Front"),
        (1, 2, 0, True, "Side"),
        (0, 1, 2, True, "Top"),
    )
    for index, (horizontal, vertical, depth, ascending, title) in enumerate(views, start=1):
        axis = fig.add_subplot(2, 2, index, facecolor="#f6f7f8")
        _render_orthographic(
            axis,
            faces,
            colors,
            horizontal_axis=horizontal,
            vertical_axis=vertical,
            depth_axis=depth,
            depth_ascending=ascending,
            title=title,
        )
    perspective = fig.add_subplot(2, 2, 4, projection="3d", facecolor="#f6f7f8")
    _render_perspective(perspective, mesh, faces, colors)
    fig.suptitle("CadFlow Static Flexible Garment", fontsize=16, weight="bold")
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


def write_outputs(mesh: FlexibleMesh, output_dir: Path = OUT) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "png": output_dir / PNG_PATH.name,
        "obj": output_dir / OBJ_PATH.name,
        "stl": output_dir / STL_PATH.name,
        "json": output_dir / JSON_PATH.name,
    }
    mesh.write_obj(paths["obj"])
    mesh.write_stl(paths["stl"])
    mesh.write_json(paths["json"])
    render_garment(mesh, paths["png"])
    return paths


def main() -> None:
    mesh = build_garment()
    paths = write_outputs(mesh)
    metrics = {
        "vertices": mesh.vertex_count,
        "triangles": mesh.triangle_count,
        "panels": len(mesh.panels),
        "surface_area_mm2": mesh.surface_area,
        "watertight_panels": mesh.is_watertight,
        "bounds_mm": [list(mesh.bounds[0]), list(mesh.bounds[1])],
        "png": str(paths["png"]),
        "obj": str(paths["obj"]),
        "stl": str(paths["stl"]),
    }
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
