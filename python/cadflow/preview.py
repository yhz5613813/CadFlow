"""Render-asset helpers for CadFlow's native preview mesh buffer."""

from __future__ import annotations

from dataclasses import dataclass
import struct

import rfc8785


_HEADER = struct.Struct("<4sIIII6f")
_MAGIC = b"CFMB"
_VERSION = 1
_UNSIGNED_SHORT = 5123
_UNSIGNED_INT = 5125


@dataclass(frozen=True, slots=True)
class PreviewMeshBuffer:
    """Validated zero-copy views over one native preview mesh buffer."""

    data: bytes
    vertex_count: int
    triangle_count: int
    index_component_type: int
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    positions: memoryview
    normals: memoryview
    indices: memoryview


def parse_preview_mesh_buffer(data: bytes | bytearray | memoryview) -> PreviewMeshBuffer:
    raw = bytes(data)
    if len(raw) < _HEADER.size:
        raise ValueError("preview mesh buffer is truncated")
    (
        magic,
        version,
        vertex_count,
        triangle_count,
        component_type,
        min_x,
        min_y,
        min_z,
        max_x,
        max_y,
        max_z,
    ) = _HEADER.unpack_from(raw)
    if magic != _MAGIC or version != _VERSION:
        raise ValueError("unsupported preview mesh buffer")
    if vertex_count == 0 or triangle_count == 0:
        raise ValueError("preview mesh buffer cannot be empty")
    expected_component = _UNSIGNED_SHORT if vertex_count <= 65536 else _UNSIGNED_INT
    if component_type != expected_component:
        raise ValueError("preview mesh index component does not match vertex count")
    if any(low > high for low, high in zip((min_x, min_y, min_z), (max_x, max_y, max_z))):
        raise ValueError("preview mesh bounds are invalid")

    position_bytes = vertex_count * 12
    normal_bytes = vertex_count * 12
    index_bytes = triangle_count * 3 * (2 if component_type == _UNSIGNED_SHORT else 4)
    expected_size = _HEADER.size + position_bytes + normal_bytes + index_bytes
    if len(raw) != expected_size:
        raise ValueError("preview mesh buffer length does not match its header")
    view = memoryview(raw)
    position_start = _HEADER.size
    normal_start = position_start + position_bytes
    index_start = normal_start + normal_bytes
    return PreviewMeshBuffer(
        data=raw,
        vertex_count=vertex_count,
        triangle_count=triangle_count,
        index_component_type=component_type,
        bounds=((min_x, min_y, min_z), (max_x, max_y, max_z)),
        positions=view[position_start:normal_start],
        normals=view[normal_start:index_start],
        indices=view[index_start:],
    )


def preview_mesh_buffer_to_glb(data: bytes | bytearray | memoryview) -> bytes:
    """Wrap a native mesh buffer in the closed CadFlow triangle GLB profile."""
    mesh = parse_preview_mesh_buffer(data)
    binary = b"".join((mesh.positions, mesh.normals, mesh.indices))
    position_bytes = len(mesh.positions)
    normal_bytes = len(mesh.normals)
    document = {
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": mesh.vertex_count,
                "max": list(mesh.bounds[1]),
                "min": list(mesh.bounds[0]),
                "type": "VEC3",
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": mesh.vertex_count,
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": mesh.index_component_type,
                "count": mesh.triangle_count * 3,
                "type": "SCALAR",
            },
        ],
        "asset": {"generator": "CadFlow Scene GLB Profile 1", "version": "2.0"},
        "bufferViews": [
            {
                "buffer": 0,
                "byteLength": position_bytes,
                "byteOffset": 0,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteLength": normal_bytes,
                "byteOffset": position_bytes,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteLength": len(mesh.indices),
                "byteOffset": position_bytes + normal_bytes,
                "target": 34963,
            },
        ],
        "buffers": [{"byteLength": len(binary)}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"NORMAL": 1, "POSITION": 0},
                        "indices": 2,
                        "mode": 4,
                    }
                ]
            }
        ],
        "nodes": [{"mesh": 0}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    json_bytes = rfc8785.dumps(document)
    json_chunk = json_bytes + b" " * ((-len(json_bytes)) % 4)
    bin_chunk = binary + b"\0" * ((-len(binary)) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return b"".join(
        (
            struct.pack("<III", 0x46546C67, 2, total_length),
            struct.pack("<II", len(json_chunk), 0x4E4F534A),
            json_chunk,
            struct.pack("<II", len(bin_chunk), 0x004E4942),
            bin_chunk,
        )
    )


__all__ = [
    "PreviewMeshBuffer",
    "parse_preview_mesh_buffer",
    "preview_mesh_buffer_to_glb",
]
