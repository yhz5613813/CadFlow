"""Private ctypes boundary for static flexible-shell mesh construction."""

from __future__ import annotations

import ctypes as C
import os
from pathlib import Path

import numpy as np


class FlexibleNativeError(RuntimeError):
    """Raised when the native flexible-shell builder rejects an input."""


def _library_candidates():
    explicit = os.environ.get("CADFLOW_CORE_LIBRARY")
    if explicit:
        yield Path(explicit)
    package_dir = Path(__file__).resolve().parent
    yield package_dir / "libcadflow_core.so"
    yield package_dir / "cadflow_core.dll"
    yield package_dir / "libcadflow_core.dylib"
    root = Path(__file__).resolve().parents[2]
    yield root / "build" / "native" / "libcadflow_core.so"
    yield root / "build-fallback" / "native" / "libcadflow_core.so"
    yield root / "build" / "native" / "cadflow_core.dll"
    yield root / "build" / "native" / "libcadflow_core.dylib"


def _load_library() -> C.CDLL:
    for candidate in _library_candidates():
        if candidate.exists():
            return C.CDLL(str(candidate))
    tried = ", ".join(str(path) for path in _library_candidates())
    raise FlexibleNativeError(f"cadflow native library was not found; tried: {tried}")


def _pointer(array: np.ndarray, ctype):
    if array.size == 0:
        return C.POINTER(ctype)()
    return array.ctypes.data_as(C.POINTER(ctype))


def _configure(library: C.CDLL) -> None:
    library.cadflow_flexible_shell_mesh_counts.argtypes = [
        C.c_size_t,
        C.c_size_t,
        C.c_int,
        C.c_double,
        C.POINTER(C.c_size_t),
    ]
    library.cadflow_flexible_shell_mesh_counts.restype = C.c_int
    library.cadflow_build_flexible_shell_mesh.argtypes = [
        C.POINTER(C.c_double),
        C.c_size_t,
        C.c_size_t,
        C.c_size_t,
        C.c_size_t,
        C.c_int,
        C.c_double,
        C.POINTER(C.c_double),
        C.POINTER(C.c_double),
        C.POINTER(C.c_uint),
    ]
    library.cadflow_build_flexible_shell_mesh.restype = C.c_int
    library.cadflow_last_error.restype = C.c_char_p


def build_shell_mesh(
    control_xyz: np.ndarray,
    sample_rows: int,
    sample_columns: int,
    periodic_columns: bool,
    thickness: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    library = _load_library()
    _configure(library)
    counts = np.empty(2, dtype=np.uintp)
    ok = library.cadflow_flexible_shell_mesh_counts(
        int(sample_rows),
        int(sample_columns),
        int(periodic_columns),
        float(thickness),
        _pointer(counts, C.c_size_t),
    )
    if not ok:
        _raise_last_error(library, "failed to query flexible shell mesh size")
    vertices = np.empty((int(counts[0]), 3), dtype=np.float64)
    normals = np.empty_like(vertices)
    triangles = np.empty((int(counts[1]), 3), dtype=np.uint32)
    ok = library.cadflow_build_flexible_shell_mesh(
        _pointer(control_xyz, C.c_double),
        int(control_xyz.shape[0]),
        int(control_xyz.shape[1]),
        int(sample_rows),
        int(sample_columns),
        int(periodic_columns),
        float(thickness),
        _pointer(vertices, C.c_double),
        _pointer(normals, C.c_double),
        _pointer(triangles, C.c_uint),
    )
    if not ok:
        _raise_last_error(library, "failed to build flexible shell mesh")
    return vertices, normals, triangles


def _raise_last_error(library: C.CDLL, fallback: str) -> None:
    message = library.cadflow_last_error()
    detail = message.decode("utf-8", "replace") if message else fallback
    raise FlexibleNativeError(detail)
