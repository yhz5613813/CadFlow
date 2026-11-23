"""Surface-quality visualization over CadFlow's native curvature mesh.

The C++ core tessellates a shape and evaluates exact curvature at every mesh
vertex from the underlying BREP surfaces. This module turns that buffer into
the classic class-A surface inspection views:

* curvature maps (Gaussian, mean, principal, or maximum absolute curvature),
* zebra stripes (reflection lines), whose behaviour across a boundary reveals
  G0 (stripes break), G1 (stripes kink), or G2 (stripes stay smooth),
* isophotes (lines of constant illumination).

Results can be written as a GLB with per-vertex colours or rasterized to a PNG
for agents that inspect images.

Curvature signs follow the oriented face normal (``n . S_uu``), the same
convention as ``Shape.surface_metrics``: a convex solid reads negative.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Sequence

import numpy as np
import rfc8785


_HEADER = struct.Struct("<4sIII")
_MAGIC = b"CFCA"
_VERSION = 1

CURVATURE_FIELDS = ("k_min", "k_max", "mean", "gaussian", "max_abs")


@dataclass(frozen=True)
class CurvatureMesh:
    """Tessellation with exact per-vertex curvature from the BREP surfaces.

    Curvatures use inverse model-length units and are signed against the
    oriented face normal (``n . S_uu`` convention, so a convex solid has
    negative principal curvatures). Vertices at surface poles carry NaN.
    """

    positions: np.ndarray
    normals: np.ndarray
    curvature: np.ndarray
    face_indices: np.ndarray
    triangles: np.ndarray

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])

    def field(self, name: str) -> np.ndarray:
        """Return one per-vertex curvature field by name."""
        if name == "max_abs":
            return np.nanmax(np.abs(self.curvature[:, :2]), axis=1)
        try:
            column = ("k_min", "k_max", "mean", "gaussian").index(name)
        except ValueError:
            raise ValueError(f"curvature field must be one of {CURVATURE_FIELDS}") from None
        return self.curvature[:, column]

    def summary(self) -> dict[str, object]:
        """JSON-safe statistics, including the tightest radius location."""
        result: dict[str, object] = {
            "vertices": self.vertex_count,
            "triangles": self.triangle_count,
            "faces": int(self.face_indices.max()) + 1 if self.vertex_count else 0,
        }
        for name in ("k_min", "k_max", "mean", "gaussian"):
            values = self.field(name)
            finite = values[np.isfinite(values)]
            result[name] = (
                {"min": float(finite.min()), "max": float(finite.max())}
                if finite.size else {"min": None, "max": None}
            )
        magnitude = self.field("max_abs")
        if np.isfinite(magnitude).any() and np.nanmax(magnitude) > 0.0:
            index = int(np.nanargmax(magnitude))
            result["minimum_radius"] = float(1.0 / magnitude[index])
            result["minimum_radius_point"] = [float(value) for value in self.positions[index]]
            result["minimum_radius_face"] = int(self.face_indices[index])
        else:
            result["minimum_radius"] = None
        return result


def parse_curvature_mesh_buffer(data: bytes | bytearray | memoryview) -> CurvatureMesh:
    raw = bytes(data)
    if len(raw) < _HEADER.size:
        raise ValueError("curvature mesh buffer is truncated")
    magic, version, vertices, triangles = _HEADER.unpack_from(raw)
    if magic != _MAGIC or version != _VERSION:
        raise ValueError("unsupported curvature mesh buffer")
    expected = _HEADER.size + vertices * (3 + 3 + 4) * 4 + vertices * 4 + triangles * 12
    if len(raw) != expected or vertices == 0 or triangles == 0:
        raise ValueError("curvature mesh buffer length does not match its header")
    offset = _HEADER.size

    def take(dtype: str, count: int, width: int) -> np.ndarray:
        nonlocal offset
        array = np.frombuffer(raw, dtype=dtype, count=count * width, offset=offset)
        offset += array.nbytes
        return array.reshape(count, width) if width > 1 else array

    positions = take("<f4", vertices, 3)
    normals = take("<f4", vertices, 3)
    curvature = take("<f4", vertices, 4)
    face_indices = take("<u4", vertices, 1)
    indices = take("<u4", triangles, 3)
    if int(indices.max()) >= vertices:
        raise ValueError("curvature mesh triangle index is out of range")
    return CurvatureMesh(
        positions.astype(np.float64),
        normals.astype(np.float64),
        curvature.astype(np.float64),
        face_indices.astype(np.int64),
        indices.astype(np.int64),
    )


def _unit(vector: Sequence[float], name: str) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float64)
    if value.shape != (3,):
        raise ValueError(f"{name} must contain three values")
    length = float(np.linalg.norm(value))
    if not length > 0.0:
        raise ValueError(f"{name} must be non-zero")
    return value / length


def _reflection_phase(
    normals: np.ndarray, view: np.ndarray, axis: np.ndarray, stripes: int
) -> np.ndarray:
    reflected = view - 2.0 * (normals @ view)[..., None] * normals
    angle = np.arccos(np.clip(reflected @ axis, -1.0, 1.0))
    return stripes * angle / math.pi


def zebra(
    mesh: CurvatureMesh,
    *,
    view_direction: Sequence[float] = (-1.0, -1.0, -1.0),
    stripe_axis: Sequence[float] = (0.0, 0.0, 1.0),
    stripes: int = 16,
) -> np.ndarray:
    """Per-vertex reflection-line value in {0, 1} (0 black, 1 white).

    The environment is a set of light bands around ``stripe_axis``; each vertex
    reflects the viewing ray ``view_direction`` (eye towards the model).
    """
    if stripes < 1:
        raise ValueError("stripes must be positive")
    phase = _reflection_phase(
        mesh.normals, _unit(view_direction, "view_direction"),
        _unit(stripe_axis, "stripe_axis"), stripes)
    return (np.floor(phase) % 2).astype(np.float64)


def isophotes(
    mesh: CurvatureMesh,
    *,
    light_direction: Sequence[float] = (1.0, 1.0, 1.0),
    bands: int = 12,
) -> np.ndarray:
    """Per-vertex alternating band index of the Lambert term ``n . L``."""
    if bands < 1:
        raise ValueError("bands must be positive")
    light = _unit(light_direction, "light_direction")
    intensity = (mesh.normals @ light + 1.0) * 0.5
    return (np.floor(bands * intensity) % 2).astype(np.float64)


def curvature_range(values: np.ndarray, percentile: float = 95.0) -> float:
    """Symmetric colour range: a percentile of the non-zero magnitudes.

    Planar faces contribute exact zeros; including them would collapse the
    range on mostly-flat parts and hide every curved region.
    """
    magnitudes = np.abs(np.asarray(values, dtype=np.float64))
    magnitudes = magnitudes[np.isfinite(magnitudes)]
    if not magnitudes.size or magnitudes.max() <= 0.0:
        return 0.0
    nonzero = magnitudes[magnitudes > 1e-9 * magnitudes.max()]
    return float(np.percentile(nonzero, percentile))


def curvature_colors(
    values: np.ndarray, *, clip: float | None = None, percentile: float = 95.0
) -> np.ndarray:
    """Diverging blue-white-red RGB for signed curvature; NaN becomes grey."""
    values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(values)
    if clip is None:
        clip = curvature_range(values, percentile)
    scale = clip if clip and clip > 0.0 else 1.0
    t = np.clip(np.where(finite, values, 0.0) / scale, -1.0, 1.0)
    colors = np.empty(t.shape + (3,))
    negative = t < 0.0
    # Interpolate white -> blue for negative and white -> red for positive.
    colors[..., 0] = np.where(negative, 1.0 + t * 0.85, 1.0)
    colors[..., 1] = 1.0 - np.abs(t) * 0.85
    colors[..., 2] = np.where(negative, 1.0, 1.0 - t * 0.85)
    colors[~finite] = (0.55, 0.55, 0.55)
    return colors


def stripe_colors(values: np.ndarray) -> np.ndarray:
    value = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    return np.repeat((0.08 + 0.9 * value)[..., None], 3, axis=-1)


def to_glb(mesh: CurvatureMesh, colors: np.ndarray) -> bytes:
    """Write an unlit GLB whose vertex colours carry the analysis view."""
    colors = np.asarray(colors, dtype=np.float64)
    if colors.shape != (mesh.vertex_count, 3):
        raise ValueError("colors must have one RGB triple per vertex")
    positions = mesh.positions.astype("<f4")
    normals = mesh.normals.astype("<f4")
    rgb = np.clip(colors, 0.0, 1.0).astype("<f4")
    indices = mesh.triangles.astype("<u4")
    chunks = [positions.tobytes(), normals.tobytes(), rgb.tobytes(), indices.tobytes()]
    views = []
    offset = 0
    for index, chunk in enumerate(chunks):
        views.append({
            "buffer": 0,
            "byteLength": len(chunk),
            "byteOffset": offset,
            "target": 34963 if index == 3 else 34962,
        })
        offset += len(chunk)
    binary = b"".join(chunks)
    document = {
        "accessors": [
            {
                "bufferView": 0, "componentType": 5126, "count": mesh.vertex_count,
                "type": "VEC3",
                "min": [float(value) for value in positions.min(axis=0)],
                "max": [float(value) for value in positions.max(axis=0)],
            },
            {"bufferView": 1, "componentType": 5126, "count": mesh.vertex_count, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": mesh.vertex_count, "type": "VEC3"},
            {
                "bufferView": 3, "componentType": 5125,
                "count": mesh.triangle_count * 3, "type": "SCALAR",
            },
        ],
        "asset": {"generator": "CadFlow surface analysis", "version": "2.0"},
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
        "extensionsUsed": ["KHR_materials_unlit"],
        "materials": [{
            "doubleSided": True,
            "extensions": {"KHR_materials_unlit": {}},
            "pbrMetallicRoughness": {
                "baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 1,
            },
        }],
        "meshes": [{
            "primitives": [{
                "attributes": {"COLOR_0": 2, "NORMAL": 1, "POSITION": 0},
                "indices": 3, "material": 0, "mode": 4,
            }],
        }],
        "nodes": [{"mesh": 0}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    json_bytes = rfc8785.dumps(document)
    json_chunk = json_bytes + b" " * ((-len(json_bytes)) % 4)
    bin_chunk = binary + b"\0" * ((-len(binary)) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return b"".join((
        struct.pack("<III", 0x46546C67, 2, total),
        struct.pack("<II", len(json_chunk), 0x4E4F534A),
        json_chunk,
        struct.pack("<II", len(bin_chunk), 0x004E4942),
        bin_chunk,
    ))


@dataclass(frozen=True)
class _Raster:
    covered: np.ndarray
    face: np.ndarray
    normal: np.ndarray
    values: np.ndarray


def _rasterize(
    mesh: CurvatureMesh,
    attributes: np.ndarray,
    view: np.ndarray,
    up: Sequence[float],
    size: int,
) -> _Raster:
    """Orthographic z-buffer rasterization with per-pixel interpolation."""
    up_vector = np.asarray(up, dtype=np.float64)
    right = np.cross(view, up_vector)
    if np.linalg.norm(right) < 1e-12:
        right = np.cross(view, (1.0, 0.0, 0.0))
    right /= np.linalg.norm(right)
    true_up = np.cross(right, view)

    xy = np.stack((mesh.positions @ right, mesh.positions @ true_up), axis=1)
    depth = mesh.positions @ view
    low = xy.min(axis=0)
    span = float((xy.max(axis=0) - low).max()) or 1.0
    margin = 0.04 * span
    scale = (size - 1) / (span + 2.0 * margin)
    px = (xy[:, 0] - low[0] + margin) * scale
    py = (size - 1) - (xy[:, 1] - low[1] + margin) * scale

    channels = attributes.shape[1]
    zbuffer = np.full((size, size), np.inf)
    face = np.full((size, size), -1, dtype=np.int64)
    values = np.zeros((size, size, channels))
    normal_buffer = np.zeros((size, size, 3))
    per_vertex = np.concatenate((mesh.normals, attributes), axis=1)
    for triangle in mesh.triangles:
        x = px[triangle]
        y = py[triangle]
        x0 = max(int(np.floor(x.min())), 0)
        x1 = min(int(np.ceil(x.max())), size - 1)
        y0 = max(int(np.floor(y.min())), 0)
        y1 = min(int(np.ceil(y.max())), size - 1)
        if x0 > x1 or y0 > y1:
            continue
        denominator = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(denominator) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        w0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / denominator
        w1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        z = w0 * depth[triangle[0]] + w1 * depth[triangle[1]] + w2 * depth[triangle[2]]
        region = zbuffer[y0:y1 + 1, x0:x1 + 1]
        visible = inside & (z < region)
        if not visible.any():
            continue
        region[visible] = z[visible]
        weights = np.stack((w0[visible], w1[visible], w2[visible]), axis=1)
        interpolated = weights @ per_vertex[triangle]
        rows, cols = np.nonzero(visible)
        rows += y0
        cols += x0
        normal_buffer[rows, cols] = interpolated[:, :3]
        values[rows, cols] = interpolated[:, 3:]
        face[rows, cols] = mesh.face_indices[triangle[0]]
    lengths = np.linalg.norm(normal_buffer, axis=-1, keepdims=True)
    normal_buffer = np.divide(
        normal_buffer, lengths, out=np.zeros_like(normal_buffer), where=lengths > 0)
    return _Raster(np.isfinite(zbuffer), face, normal_buffer, values)


def render_png(
    mesh: CurvatureMesh,
    path: str,
    *,
    mode: str = "mean",
    view_direction: Sequence[float] = (-1.0, -1.0, -1.0),
    up: Sequence[float] = (0.0, 0.0, 1.0),
    size: int = 800,
    stripes: int = 20,
    stripe_axis: Sequence[float] | None = None,
    light_direction: Sequence[float] | None = None,
    clip: float | None = None,
    colors: np.ndarray | None = None,
    face_outlines: bool = True,
    title: str | None = None,
) -> dict[str, object]:
    """Render one surface-inspection view to a PNG and describe it.

    ``mode`` is a curvature field name (see ``CURVATURE_FIELDS``), ``"zebra"``,
    ``"isophote"``, ``"shaded"``, or ``"colors"`` for caller-supplied per-vertex
    RGB. Zebra and isophote bands are computed per pixel from the interpolated
    exact surface normal, so their edges reflect the geometry rather than the
    triangle layout. BREP face boundaries are outlined to show patch seams.
    Requires Pillow.
    """
    from PIL import Image, ImageDraw

    if size < 16:
        raise ValueError("size must be at least 16 pixels")
    view = _unit(view_direction, "view_direction")
    if mode in CURVATURE_FIELDS:
        field = mesh.field(mode)
        clip = curvature_range(field) if clip is None else clip
        attributes = field[:, None]
    elif mode == "colors":
        if colors is None or np.asarray(colors).shape != (mesh.vertex_count, 3):
            raise ValueError("mode 'colors' needs one RGB triple per vertex")
        attributes = np.asarray(colors, dtype=np.float64)
    elif mode in {"zebra", "isophote", "shaded"}:
        attributes = np.zeros((mesh.vertex_count, 1))
    else:
        raise ValueError(
            f"mode must be one of {CURVATURE_FIELDS + ('zebra', 'isophote', 'shaded', 'colors')}"
        )

    raster = _rasterize(mesh, attributes, view, up, size)
    normal = raster.normal
    headlight = np.abs(normal @ view)
    if mode in CURVATURE_FIELDS:
        rgb = curvature_colors(raster.values[..., 0], clip=clip)
        rgb *= (0.55 + 0.45 * headlight)[..., None]
    elif mode == "colors":
        rgb = np.clip(raster.values, 0.0, 1.0) * (0.55 + 0.45 * headlight)[..., None]
    elif mode == "zebra":
        axis = _unit(stripe_axis if stripe_axis is not None else up, "stripe_axis")
        phase = _reflection_phase(normal, view, axis, stripes)
        rgb = stripe_colors(np.floor(phase) % 2)
    elif mode == "isophote":
        light = _unit(light_direction if light_direction is not None else -view, "light_direction")
        band = np.floor(stripes * (normal @ light + 1.0) * 0.5) % 2
        rgb = stripe_colors(band)
    else:
        rgb = np.repeat((0.25 + 0.7 * headlight)[..., None], 3, axis=-1)
    rgb[~raster.covered] = 1.0

    if face_outlines:
        boundary = np.zeros_like(raster.covered)
        face = raster.face
        boundary[:-1, :] |= face[:-1, :] != face[1:, :]
        boundary[:, :-1] |= face[:, :-1] != face[:, 1:]
        rgb[boundary] = (0.85, 0.35, 0.0) if mode in {"zebra", "isophote"} else (0.1, 0.1, 0.1)

    image = Image.fromarray((np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8), "RGB")
    if title:
        ImageDraw.Draw(image).text((8, 6), title, fill=(0, 0, 0))
    image.save(path)
    description: dict[str, object] = {"path": str(path), "mode": mode, "size": size}
    if mode in CURVATURE_FIELDS:
        description["color_range"] = [-clip, clip] if clip else [0.0, 0.0]
        description["colors"] = "blue negative, white zero, red positive, grey singular"
    return description


__all__ = [
    "CURVATURE_FIELDS",
    "CurvatureMesh",
    "curvature_colors",
    "curvature_range",
    "isophotes",
    "parse_curvature_mesh_buffer",
    "render_png",
    "stripe_colors",
    "to_glb",
    "zebra",
]
