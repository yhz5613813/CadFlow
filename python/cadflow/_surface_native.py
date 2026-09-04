"""ctypes bridge for stateless C++ BREP surface-contact measurements."""

from __future__ import annotations

import ctypes as C
from io import BytesIO
from typing import Any

from .native import (
    NativeError,
    _SurfaceFaceMetrics,
    _SurfacePairMetrics,
    _load_library,
    _surface_face_metrics_dict,
    _surface_pair_metrics_dict,
)


def _configure(lib: C.CDLL) -> None:
    transform = C.POINTER(C.c_double)
    lib.cadflow_surface_face_metrics_brep.argtypes = [
        C.POINTER(C.c_char), C.c_size_t, transform,
        C.POINTER(_SurfaceFaceMetrics),
    ]
    lib.cadflow_surface_face_metrics_brep.restype = C.c_int
    lib.cadflow_surface_pair_metrics_brep.argtypes = [
        C.POINTER(C.c_char), C.c_size_t, transform,
        C.POINTER(C.c_char), C.c_size_t, transform,
        C.POINTER(_SurfacePairMetrics),
    ]
    lib.cadflow_surface_pair_metrics_brep.restype = C.c_int
    lib.cadflow_last_error.restype = C.c_char_p


def _error(lib: C.CDLL) -> str:
    value = lib.cadflow_last_error()
    return value.decode("utf-8", "replace") if value else "surface measurement failed"


def brep_bytes(shape: Any) -> bytes:
    """Serialize one public compatibility shape without filesystem I/O."""
    wrapped = getattr(shape, "wrapped", None)
    if wrapped is None:
        raise TypeError("BREP serialization requires a CadFlow compatibility shape")
    from OCP.BRepTools import BRepTools

    stream = BytesIO()
    BRepTools.Write_s(wrapped, stream)
    value = stream.getvalue()
    if not value:
        raise NativeError("OCP produced an empty BREP buffer")
    return value


def placement_transform(placement: Any) -> tuple[float, ...]:
    """Convert a CadFlow Placement to the public C ABI row-major transform."""
    return (
        float(placement.x_axis[0]), float(placement.y_axis[0]), float(placement.z_axis[0]), float(placement.origin[0]),
        float(placement.x_axis[1]), float(placement.y_axis[1]), float(placement.z_axis[1]), float(placement.origin[1]),
        float(placement.x_axis[2]), float(placement.y_axis[2]), float(placement.z_axis[2]), float(placement.origin[2]),
    )


def measure_brep_face(face: Any, placement: Any) -> dict[str, object]:
    lib = _load_library()
    _configure(lib)
    data = brep_bytes(face)
    buffer = C.create_string_buffer(data, len(data))
    transform = (C.c_double * 12)(*placement_transform(placement))
    output = _SurfaceFaceMetrics()
    ok = lib.cadflow_surface_face_metrics_brep(
        buffer, len(data), transform, C.byref(output)
    )
    if not ok:
        raise NativeError(_error(lib))
    return _surface_face_metrics_dict(output)


def measure_brep_pair(
    face_a: Any,
    placement_a: Any,
    face_b: Any,
    placement_b: Any,
) -> dict[str, object]:
    lib = _load_library()
    _configure(lib)
    data_a = brep_bytes(face_a)
    data_b = brep_bytes(face_b)
    buffer_a = C.create_string_buffer(data_a, len(data_a))
    buffer_b = C.create_string_buffer(data_b, len(data_b))
    transform_a = (C.c_double * 12)(*placement_transform(placement_a))
    transform_b = (C.c_double * 12)(*placement_transform(placement_b))
    output = _SurfacePairMetrics()
    ok = lib.cadflow_surface_pair_metrics_brep(
        buffer_a, len(data_a), transform_a,
        buffer_b, len(data_b), transform_b,
        C.byref(output),
    )
    if not ok:
        raise NativeError(_error(lib))
    return _surface_pair_metrics_dict(output)


__all__ = ["brep_bytes", "measure_brep_face", "measure_brep_pair", "placement_transform"]
