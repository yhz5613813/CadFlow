"""Small, typed ctypes facade for the native session store.

The public CAD objects never expose an OCC pointer.  They carry a session-scoped
integer handle, which leaves room for a future in-process OCCT binding without
changing the Python API.
"""

from __future__ import annotations

import ctypes as C
import operator
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


class NativeError(RuntimeError):
    """Raised when the C++ backend rejects an operation."""


def _surface_grid(
    points: Sequence[Sequence[Sequence[float]]],
) -> tuple[int, int, list[float]]:
    rows = [list(row) for row in points]
    if len(rows) < 2:
        raise NativeError("surface point grid requires at least two rows")
    columns = len(rows[0])
    if columns < 2 or any(len(row) != columns for row in rows):
        raise NativeError("surface point grid must be rectangular and at least 2 by 2")
    flat: list[float] = []
    for row in rows:
        for point in row:
            if len(point) != 3:
                raise NativeError("surface points must contain three coordinates")
            flat.extend(float(value) for value in point)
    return len(rows), columns, flat


def _subshape_indices(
    indices: Sequence[int] | None,
) -> tuple[C.Array[C.c_size_t] | None, int]:
    """Validate and materialize a zero-based subshape index array."""
    if indices is None:
        values: list[int] = []
    else:
        values = []
        try:
            iterator = iter(indices)
        except TypeError as error:
            raise NativeError("subshape indices must be a sequence of integers") from error
        for index in iterator:
            if isinstance(index, bool):
                raise NativeError("subshape indices must be integers")
            try:
                value = operator.index(index)
            except TypeError as error:
                raise NativeError("subshape indices must be integers") from error
            if value < 0:
                raise NativeError("subshape indices must be non-negative")
            values.append(value)
    if len(set(values)) != len(values):
        raise NativeError("subshape indices must be unique")
    if not values:
        return None, 0
    try:
        return (C.c_size_t * len(values))(*values), len(values)
    except OverflowError as error:
        raise NativeError("subshape index exceeds the platform size limit") from error


def _library_candidates() -> Iterable[Path]:
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
    paths = ", ".join(str(path) for path in _library_candidates())
    raise NativeError(f"cadflow native library was not found; tried: {paths}")


def _configure(lib: C.CDLL) -> None:
    handle = C.c_void_p
    u64 = C.c_ulonglong
    f64 = C.c_double
    lib.cadflow_session_create.restype = handle
    lib.cadflow_session_destroy.argtypes = [handle]
    for name, args in {
        "cadflow_box": [handle, f64, f64, f64],
        "cadflow_cylinder": [handle, f64, f64],
        "cadflow_sphere": [handle, f64],
        "cadflow_cone": [handle, f64, f64, f64],
        "cadflow_import_step": [handle, C.c_char_p],
        "cadflow_polyline": [handle, C.POINTER(f64), C.c_size_t, C.c_int],
        "cadflow_circle_profile": [handle, f64, f64, f64, f64, f64, f64, f64],
        "cadflow_arc": [handle, C.POINTER(f64)],
        "cadflow_interpolate": [handle, C.POINTER(f64), C.c_size_t, C.c_int, f64],
        "cadflow_helix": [handle, f64, f64, f64, f64, f64, f64, f64, f64, f64],
        "cadflow_face": [handle, u64],
        "cadflow_bezier_surface": [
            handle, C.POINTER(f64), C.c_size_t, C.c_size_t, C.POINTER(f64)
        ],
        "cadflow_fit_surface": [
            handle, C.POINTER(f64), C.c_size_t, C.c_size_t, f64, C.c_int, C.c_int
        ],
        "cadflow_extrude": [handle, u64, f64, f64, f64],
        "cadflow_revolve": [handle, u64, f64, f64, f64, f64, f64, f64, f64],
        "cadflow_fillet": [handle, u64, f64, C.POINTER(C.c_size_t), C.c_size_t],
        "cadflow_chamfer": [handle, u64, f64, C.POINTER(C.c_size_t), C.c_size_t],
        "cadflow_shell": [
            handle, u64, f64, C.POINTER(C.c_size_t), C.c_size_t, f64
        ],
        "cadflow_loft": [handle, C.POINTER(u64), C.c_size_t, C.c_int, C.c_int],
        "cadflow_sweep": [handle, u64, u64, C.c_int, C.c_int],
        "cadflow_cut": [handle, u64, u64],
        "cadflow_union": [handle, u64, u64],
        "cadflow_intersect": [handle, u64, u64],
        "cadflow_translate": [handle, u64, f64, f64, f64],
        "cadflow_rotate": [handle, u64, f64, f64, f64, f64, f64, f64, f64],
        "cadflow_mirror": [handle, u64, f64, f64, f64, f64, f64, f64],
        "cadflow_scale": [handle, u64, f64, f64, f64, f64],
        "cadflow_volume": [handle, u64],
        "cadflow_area": [handle, u64],
        "cadflow_length": [handle, u64],
        "cadflow_distance": [handle, u64, u64],
        "cadflow_kind": [handle, u64],
        "cadflow_export_step": [handle, u64, C.c_char_p],
        "cadflow_export_stl": [handle, u64, C.c_char_p, C.c_int],
        "cadflow_mesh_json": [handle, u64, f64, C.POINTER(C.c_char_p)],
        "cadflow_execute": [handle, C.c_char_p, C.POINTER(C.c_char_p)],
    }.items():
        getattr(lib, name).argtypes = args
    for name in (
        "cadflow_box", "cadflow_cylinder", "cadflow_sphere", "cadflow_cone",
        "cadflow_import_step",
        "cadflow_polyline", "cadflow_circle_profile", "cadflow_face",
        "cadflow_bezier_surface", "cadflow_fit_surface",
        "cadflow_arc", "cadflow_interpolate",
        "cadflow_helix",
        "cadflow_extrude", "cadflow_revolve",
        "cadflow_fillet", "cadflow_chamfer", "cadflow_shell",
        "cadflow_loft",
        "cadflow_sweep",
        "cadflow_cut", "cadflow_union", "cadflow_intersect", "cadflow_translate",
        "cadflow_rotate", "cadflow_mirror", "cadflow_scale",
    ):
        getattr(lib, name).restype = u64
    for name in ("cadflow_volume", "cadflow_area", "cadflow_length", "cadflow_distance"):
        getattr(lib, name).restype = f64
    lib.cadflow_kind.restype = C.c_char_p
    lib.cadflow_export_step.restype = C.c_int
    lib.cadflow_export_stl.restype = C.c_int
    lib.cadflow_mesh_json.restype = C.c_int
    lib.cadflow_bbox.argtypes = [handle, u64, C.POINTER(f64)]
    lib.cadflow_bbox.restype = C.c_int
    lib.cadflow_center_of_mass.argtypes = [handle, u64, C.POINTER(f64)]
    lib.cadflow_center_of_mass.restype = C.c_int
    lib.cadflow_topology_counts.argtypes = [handle, u64, C.POINTER(u64)]
    lib.cadflow_topology_counts.restype = C.c_int
    lib.cadflow_execute.restype = C.c_int
    lib.cadflow_free_string.argtypes = [C.c_char_p]
    lib.cadflow_last_error.restype = C.c_char_p
    lib.cadflow_version.restype = C.c_char_p


@dataclass(frozen=True)
class ShapeHandle:
    """An opaque, session-owned native shape reference."""

    session_token: int
    value: int


class NativeSession:
    """Owns native shapes and exposes batched primitive operations."""

    def __init__(self) -> None:
        self._lib = _load_library()
        _configure(self._lib)
        raw = self._lib.cadflow_session_create()
        if not raw:
            raise NativeError(self._error())
        self._raw = raw
        self._token = id(self)
        self._closed = False

    def _error(self) -> str:
        value = self._lib.cadflow_last_error()
        return value.decode("utf-8", "replace") if value is not None else ""

    def _ensure_open(self) -> None:
        if self._closed:
            raise NativeError("native session is closed")

    def _check(self) -> None:
        error = self._error()
        if error:
            raise NativeError(error)

    def _handle(self, value: int) -> ShapeHandle:
        self._ensure_open()
        self._check()
        if not value:
            raise NativeError("native operation returned a null shape handle")
        return ShapeHandle(self._token, int(value))

    def _id(self, shape: ShapeHandle) -> int:
        self._ensure_open()
        if shape.session_token != self._token:
            raise NativeError("shape handle belongs to another session")
        return shape.value

    def box(self, width: float, depth: float, height: float) -> ShapeHandle:
        self._ensure_open()
        return self._handle(self._lib.cadflow_box(self._raw, width, depth, height))

    def cylinder(self, radius: float, height: float) -> ShapeHandle:
        self._ensure_open()
        return self._handle(self._lib.cadflow_cylinder(self._raw, radius, height))

    def sphere(self, radius: float) -> ShapeHandle:
        self._ensure_open()
        return self._handle(self._lib.cadflow_sphere(self._raw, radius))

    def cone(self, radius1: float, radius2: float, height: float) -> ShapeHandle:
        self._ensure_open()
        return self._handle(self._lib.cadflow_cone(self._raw, radius1, radius2, height))

    def import_step(self, path: str | os.PathLike[str]) -> ShapeHandle:
        self._ensure_open()
        return self._handle(
            self._lib.cadflow_import_step(self._raw, os.fspath(path).encode("utf-8"))
        )

    def polyline(
        self,
        points: Sequence[Sequence[float]],
        *,
        closed: bool = False,
    ) -> ShapeHandle:
        self._ensure_open()
        coordinates = [tuple(float(value) for value in point) for point in points]
        if any(len(point) != 3 for point in coordinates):
            raise NativeError("polyline points must contain three coordinates")
        flat = [value for point in coordinates for value in point]
        values = (C.c_double * len(flat))(*flat)
        return self._handle(
            self._lib.cadflow_polyline(self._raw, values, len(coordinates), int(closed))
        )

    def circle_profile(
        self,
        radius: float,
        center: Sequence[float] = (0, 0, 0),
        normal: Sequence[float] = (0, 0, 1),
    ) -> ShapeHandle:
        self._ensure_open()
        if len(center) != 3 or len(normal) != 3:
            raise NativeError("circle center and normal must contain three values")
        return self._handle(
            self._lib.cadflow_circle_profile(
                self._raw, *map(float, center), *map(float, normal), radius
            )
        )

    def arc(self, points: Sequence[Sequence[float]]) -> ShapeHandle:
        self._ensure_open()
        coordinates = [tuple(float(value) for value in point) for point in points]
        if len(coordinates) != 3 or any(len(point) != 3 for point in coordinates):
            raise NativeError("arc requires exactly three 3D points")
        flat = [value for point in coordinates for value in point]
        values = (C.c_double * 9)(*flat)
        return self._handle(self._lib.cadflow_arc(self._raw, values))

    def interpolate(
        self,
        points: Sequence[Sequence[float]],
        *,
        periodic: bool = False,
        tolerance: float = 1e-6,
    ) -> ShapeHandle:
        self._ensure_open()
        coordinates = [tuple(float(value) for value in point) for point in points]
        if any(len(point) != 3 for point in coordinates):
            raise NativeError("interpolation points must contain three coordinates")
        flat = [value for point in coordinates for value in point]
        values = (C.c_double * len(flat))(*flat)
        return self._handle(
            self._lib.cadflow_interpolate(
                self._raw,
                values,
                len(coordinates),
                int(periodic),
                tolerance,
            )
        )

    def helix(
        self,
        pitch: float,
        height: float,
        radius: float,
        center: Sequence[float] = (0, 0, 0),
        direction: Sequence[float] = (0, 0, 1),
    ) -> ShapeHandle:
        self._ensure_open()
        if len(center) != 3 or len(direction) != 3:
            raise NativeError("helix center and direction must contain three values")
        return self._handle(
            self._lib.cadflow_helix(
                self._raw,
                pitch,
                height,
                radius,
                *map(float, center),
                *map(float, direction),
            )
        )

    def face(self, wire: ShapeHandle) -> ShapeHandle:
        return self._handle(self._lib.cadflow_face(self._raw, self._id(wire)))

    def bezier_surface(
        self,
        points: Sequence[Sequence[Sequence[float]]],
        *,
        weights: Sequence[Sequence[float]] | None = None,
    ) -> ShapeHandle:
        self._ensure_open()
        rows, columns, flat = _surface_grid(points)
        point_values = (C.c_double * len(flat))(*flat)
        weight_values = None
        if weights is not None:
            weight_rows = [list(row) for row in weights]
            if len(weight_rows) != rows or any(len(row) != columns for row in weight_rows):
                raise NativeError("Bezier weights must match the point grid")
            flattened_weights = [float(value) for row in weight_rows for value in row]
            weight_values = (C.c_double * len(flattened_weights))(*flattened_weights)
        return self._handle(
            self._lib.cadflow_bezier_surface(
                self._raw, point_values, rows, columns, weight_values
            )
        )

    def fit_surface(
        self,
        points: Sequence[Sequence[Sequence[float]]],
        *,
        tolerance: float = 1e-3,
        degree_min: int = 3,
        degree_max: int = 8,
    ) -> ShapeHandle:
        self._ensure_open()
        rows, columns, flat = _surface_grid(points)
        point_values = (C.c_double * len(flat))(*flat)
        return self._handle(
            self._lib.cadflow_fit_surface(
                self._raw,
                point_values,
                rows,
                columns,
                tolerance,
                degree_min,
                degree_max,
            )
        )

    def extrude(self, profile: ShapeHandle, x: float, y: float, z: float) -> ShapeHandle:
        return self._handle(
            self._lib.cadflow_extrude(self._raw, self._id(profile), x, y, z)
        )

    def revolve(
        self,
        profile: ShapeHandle,
        origin: Sequence[float],
        axis: Sequence[float],
        degrees: float = 360.0,
    ) -> ShapeHandle:
        if len(origin) != 3 or len(axis) != 3:
            raise NativeError("revolve origin and axis must contain three values")
        return self._handle(
            self._lib.cadflow_revolve(
                self._raw, self._id(profile), *origin, *axis, degrees
            )
        )

    def fillet(
        self,
        shape: ShapeHandle,
        radius: float,
        edge_indices: Sequence[int] | None = None,
        *,
        edges: Sequence[int] | None = None,
    ) -> ShapeHandle:
        if edge_indices is not None and edges is not None:
            raise NativeError("provide either edge_indices or edges, not both")
        selected = edge_indices if edge_indices is not None else edges
        values, count = _subshape_indices(selected)
        return self._handle(
            self._lib.cadflow_fillet(
                self._raw, self._id(shape), float(radius), values, count
            )
        )

    def chamfer(
        self,
        shape: ShapeHandle,
        distance: float,
        edge_indices: Sequence[int] | None = None,
        *,
        edges: Sequence[int] | None = None,
    ) -> ShapeHandle:
        if edge_indices is not None and edges is not None:
            raise NativeError("provide either edge_indices or edges, not both")
        selected = edge_indices if edge_indices is not None else edges
        values, count = _subshape_indices(selected)
        return self._handle(
            self._lib.cadflow_chamfer(
                self._raw, self._id(shape), float(distance), values, count
            )
        )

    def shell(
        self,
        shape: ShapeHandle,
        thickness: float,
        face_indices: Sequence[int] | None = None,
        *,
        tolerance: float = 1e-3,
        faces: Sequence[int] | None = None,
    ) -> ShapeHandle:
        if faces is not None:
            if face_indices is not None:
                raise NativeError("provide either face_indices or faces, not both")
            face_indices = faces
        values, count = _subshape_indices(face_indices)
        return self._handle(
            self._lib.cadflow_shell(
                self._raw,
                self._id(shape),
                float(thickness),
                values,
                count,
                float(tolerance),
            )
        )

    def loft(
        self,
        profiles: Sequence[ShapeHandle],
        *,
        solid: bool = True,
        ruled: bool = False,
    ) -> ShapeHandle:
        profile_ids = [self._id(profile) for profile in profiles]
        values = (C.c_ulonglong * len(profile_ids))(*profile_ids)
        return self._handle(
            self._lib.cadflow_loft(
                self._raw, values, len(profile_ids), int(solid), int(ruled)
            )
        )

    def sweep(
        self,
        profile: ShapeHandle,
        path: ShapeHandle,
        *,
        solid: bool = True,
        frenet: bool = False,
    ) -> ShapeHandle:
        return self._handle(
            self._lib.cadflow_sweep(
                self._raw,
                self._id(profile),
                self._id(path),
                int(solid),
                int(frenet),
            )
        )

    def cut(self, body: ShapeHandle, tool: ShapeHandle) -> ShapeHandle:
        return self._handle(self._lib.cadflow_cut(self._raw, self._id(body), self._id(tool)))

    def union(self, left: ShapeHandle, right: ShapeHandle) -> ShapeHandle:
        return self._handle(self._lib.cadflow_union(self._raw, self._id(left), self._id(right)))

    def intersect(self, left: ShapeHandle, right: ShapeHandle) -> ShapeHandle:
        return self._handle(self._lib.cadflow_intersect(self._raw, self._id(left), self._id(right)))

    def translate(self, shape: ShapeHandle, x: float, y: float, z: float) -> ShapeHandle:
        return self._handle(self._lib.cadflow_translate(self._raw, self._id(shape), x, y, z))

    def rotate(
        self,
        shape: ShapeHandle,
        origin: Sequence[float],
        axis: Sequence[float],
        degrees: float,
    ) -> ShapeHandle:
        if len(origin) != 3 or len(axis) != 3:
            raise NativeError("rotation origin and axis must contain three values")
        return self._handle(
            self._lib.cadflow_rotate(self._raw, self._id(shape), *origin, *axis, degrees)
        )

    def mirror(
        self,
        shape: ShapeHandle,
        origin: Sequence[float],
        normal: Sequence[float],
    ) -> ShapeHandle:
        if len(origin) != 3 or len(normal) != 3:
            raise NativeError("mirror origin and normal must contain three values")
        return self._handle(
            self._lib.cadflow_mirror(self._raw, self._id(shape), *origin, *normal)
        )

    def scale(
        self,
        shape: ShapeHandle,
        factor: float,
        center: Sequence[float] = (0, 0, 0),
    ) -> ShapeHandle:
        if len(center) != 3:
            raise NativeError("scale center must contain three values")
        return self._handle(
            self._lib.cadflow_scale(self._raw, self._id(shape), *center, factor)
        )

    def volume(self, shape: ShapeHandle) -> float:
        value = float(self._lib.cadflow_volume(self._raw, self._id(shape)))
        self._check()
        return value

    def area(self, shape: ShapeHandle) -> float:
        value = float(self._lib.cadflow_area(self._raw, self._id(shape)))
        self._check()
        return value

    def length(self, shape: ShapeHandle) -> float:
        value = float(self._lib.cadflow_length(self._raw, self._id(shape)))
        self._check()
        return value

    def distance(self, left: ShapeHandle, right: ShapeHandle) -> float:
        value = float(
            self._lib.cadflow_distance(self._raw, self._id(left), self._id(right))
        )
        self._check()
        return value

    def center_of_mass(self, shape: ShapeHandle) -> tuple[float, float, float]:
        output = (C.c_double * 3)()
        ok = self._lib.cadflow_center_of_mass(self._raw, self._id(shape), output)
        self._check()
        if not ok:
            raise NativeError("native center-of-mass query failed")
        return tuple(float(item) for item in output)  # type: ignore[return-value]

    def bbox(self, shape: ShapeHandle) -> tuple[float, float, float, float, float, float]:
        output = (C.c_double * 6)()
        ok = self._lib.cadflow_bbox(self._raw, self._id(shape), output)
        self._check()
        if not ok:
            raise NativeError("native bounding-box query failed")
        return tuple(float(item) for item in output)  # type: ignore[return-value]

    def topology(self, shape: ShapeHandle) -> dict[str, int]:
        output = (C.c_ulonglong * 4)()
        ok = self._lib.cadflow_topology_counts(self._raw, self._id(shape), output)
        self._check()
        if not ok:
            raise NativeError("native topology query failed")
        return dict(zip(("vertices", "edges", "faces", "solids"), map(int, output)))

    def kind(self, shape: ShapeHandle) -> str:
        value = self._lib.cadflow_kind(self._raw, self._id(shape))
        self._check()
        return value.decode("ascii") if value else "unknown"

    def export_step(self, shape: ShapeHandle, path: str | os.PathLike[str]) -> None:
        ok = self._lib.cadflow_export_step(self._raw, self._id(shape), os.fspath(path).encode("utf-8"))
        self._check()
        if not ok:
            raise NativeError("native STEP export failed")

    def export_stl(
        self,
        shape: ShapeHandle,
        path: str | os.PathLike[str],
        *,
        binary: bool = True,
    ) -> None:
        ok = self._lib.cadflow_export_stl(
            self._raw,
            self._id(shape),
            os.fspath(path).encode("utf-8"),
            int(binary),
        )
        self._check()
        if not ok:
            raise NativeError("native STL export failed")

    def mesh(self, shape: ShapeHandle, deflection: float = 0.1) -> dict[str, list[float] | list[int]]:
        import json

        result = C.c_char_p()
        ok = self._lib.cadflow_mesh_json(self._raw, self._id(shape), deflection, C.byref(result))
        self._check()
        if not ok or not result.value:
            raise NativeError("native mesh generation failed")
        try:
            return json.loads(result.value.decode("utf-8"))
        finally:
            self._lib.cadflow_free_string(result)

    def execute(self, program: str) -> list[str]:
        self._ensure_open()
        result = C.c_char_p()
        ok = self._lib.cadflow_execute(self._raw, program.encode("utf-8"), C.byref(result))
        self._check()
        if not ok or not result.value:
            raise NativeError("native graph execution returned no result")
        try:
            return result.value.decode("utf-8").splitlines()
        finally:
            self._lib.cadflow_free_string(result)

    @property
    def version(self) -> str:
        self._ensure_open()
        return self._lib.cadflow_version().decode("ascii")

    def close(self) -> None:
        if not self._closed:
            self._lib.cadflow_session_destroy(self._raw)
            self._closed = True

    def __enter__(self) -> "NativeSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - interpreter shutdown path
        try:
            self.close()
        except Exception:
            pass
