"""The new Python-first CAD surface.

This layer intentionally contains no OCC imports. It uses opaque handles for
the native backend while compatibility-only operations remain in the bundled
Python engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .native import NativeSession, ShapeHandle


@dataclass(frozen=True)
class Shape:
    _session: NativeSession
    _handle: ShapeHandle

    @property
    def kind(self) -> str:
        return self._session.kind(self._handle)

    @property
    def volume(self) -> float:
        return self._session.volume(self._handle)

    @property
    def area(self) -> float:
        return self._session.area(self._handle)

    @property
    def length(self) -> float:
        return self._session.length(self._handle)

    @property
    def center_of_mass(self) -> tuple[float, float, float]:
        return self._session.center_of_mass(self._handle)

    def distance_to(self, other: "Shape") -> float:
        if other._session is not self._session:
            raise ValueError("both shapes must belong to the same Model")
        return self._session.distance(self._handle, other._handle)

    @property
    def bbox(self) -> tuple[float, float, float, float, float, float]:
        return self._session.bbox(self._handle)

    @property
    def topology(self) -> dict[str, int]:
        return self._session.topology(self._handle)

    def mesh(self, deflection: float = 0.1) -> dict[str, list[float] | list[int]]:
        return self._session.mesh(self._handle, deflection)

    def export_step(self, path: str) -> None:
        self._session.export_step(self._handle, path)

    def export_stl(self, path: str, *, binary: bool = True) -> None:
        self._session.export_stl(self._handle, path, binary=binary)


class Model:
    """Explicit-session frontend analogous to a small CAD model context."""

    def __init__(self, session: NativeSession | None = None) -> None:
        self.session = session or NativeSession()
        self._owns_session = session is None

    def box(self, width: float, depth: float, height: float) -> Shape:
        return Shape(self.session, self.session.box(width, depth, height))

    def cylinder(self, radius: float, height: float) -> Shape:
        return Shape(self.session, self.session.cylinder(radius, height))

    def sphere(self, radius: float) -> Shape:
        return Shape(self.session, self.session.sphere(radius))

    def cone(self, radius1: float, radius2: float, height: float) -> Shape:
        return Shape(self.session, self.session.cone(radius1, radius2, height))

    def import_step(self, path: str) -> Shape:
        return Shape(self.session, self.session.import_step(path))

    def polyline(
        self,
        points: Sequence[Sequence[float]],
        *,
        closed: bool = False,
    ) -> Shape:
        return Shape(self.session, self.session.polyline(points, closed=closed))

    def circle_profile(
        self,
        radius: float,
        center: tuple[float, float, float] = (0, 0, 0),
        normal: tuple[float, float, float] = (0, 0, 1),
    ) -> Shape:
        return Shape(self.session, self.session.circle_profile(radius, center, normal))

    def arc(
        self,
        start: Sequence[float],
        middle: Sequence[float],
        end: Sequence[float],
    ) -> Shape:
        return Shape(self.session, self.session.arc((start, middle, end)))

    def interpolate(
        self,
        points: Sequence[Sequence[float]],
        *,
        periodic: bool = False,
        tolerance: float = 1e-6,
    ) -> Shape:
        return Shape(
            self.session,
            self.session.interpolate(
                points,
                periodic=periodic,
                tolerance=tolerance,
            ),
        )

    def helix(
        self,
        pitch: float,
        height: float,
        radius: float,
        center: tuple[float, float, float] = (0, 0, 0),
        direction: tuple[float, float, float] = (0, 0, 1),
    ) -> Shape:
        return Shape(
            self.session,
            self.session.helix(pitch, height, radius, center, direction),
        )

    def face(self, wire: Shape) -> Shape:
        self._same_model(wire)
        return Shape(self.session, self.session.face(wire._handle))

    def bezier_surface(
        self,
        points: Sequence[Sequence[Sequence[float]]],
        *,
        weights: Sequence[Sequence[float]] | None = None,
    ) -> Shape:
        return Shape(
            self.session,
            self.session.bezier_surface(points, weights=weights),
        )

    def fit_surface(
        self,
        points: Sequence[Sequence[Sequence[float]]],
        *,
        tolerance: float = 1e-3,
        degree_min: int = 3,
        degree_max: int = 8,
    ) -> Shape:
        return Shape(
            self.session,
            self.session.fit_surface(
                points,
                tolerance=tolerance,
                degree_min=degree_min,
                degree_max=degree_max,
            ),
        )

    def extrude(self, profile: Shape, x: float, y: float, z: float) -> Shape:
        self._same_model(profile)
        return Shape(self.session, self.session.extrude(profile._handle, x, y, z))

    def revolve(
        self,
        profile: Shape,
        degrees: float = 360.0,
        axis: tuple[float, float, float] = (0, 0, 1),
        origin: tuple[float, float, float] = (0, 0, 0),
    ) -> Shape:
        self._same_model(profile)
        return Shape(
            self.session,
            self.session.revolve(profile._handle, origin, axis, degrees),
        )

    def fillet(
        self,
        shape: Shape,
        radius: float,
        edge_indices: Sequence[int] | None = None,
        *,
        edges: Sequence[int] | None = None,
    ) -> Shape:
        self._same_model(shape)
        return Shape(
            self.session,
            self.session.fillet(
                shape._handle, radius, edge_indices, edges=edges
            ),
        )

    def chamfer(
        self,
        shape: Shape,
        distance: float,
        edge_indices: Sequence[int] | None = None,
        *,
        edges: Sequence[int] | None = None,
    ) -> Shape:
        self._same_model(shape)
        return Shape(
            self.session,
            self.session.chamfer(
                shape._handle, distance, edge_indices, edges=edges
            ),
        )

    def shell(
        self,
        shape: Shape,
        thickness: float,
        face_indices: Sequence[int] | None = None,
        *,
        tolerance: float = 1e-3,
        faces: Sequence[int] | None = None,
    ) -> Shape:
        self._same_model(shape)
        return Shape(
            self.session,
            self.session.shell(
                shape._handle,
                thickness,
                face_indices,
                tolerance=tolerance,
                faces=faces,
            ),
        )

    def loft(
        self,
        profiles: Sequence[Shape],
        *,
        solid: bool = True,
        ruled: bool = False,
    ) -> Shape:
        self._same_model(*profiles)
        return Shape(
            self.session,
            self.session.loft(
                [profile._handle for profile in profiles],
                solid=solid,
                ruled=ruled,
            ),
        )

    def sweep(
        self,
        profile: Shape,
        path: Shape,
        *,
        solid: bool = True,
        frenet: bool = False,
    ) -> Shape:
        self._same_model(profile, path)
        return Shape(
            self.session,
            self.session.sweep(
                profile._handle,
                path._handle,
                solid=solid,
                frenet=frenet,
            ),
        )

    def cut(self, body: Shape, tool: Shape) -> Shape:
        self._same_model(body, tool)
        return Shape(self.session, self.session.cut(body._handle, tool._handle))

    def union(self, left: Shape, right: Shape) -> Shape:
        self._same_model(left, right)
        return Shape(self.session, self.session.union(left._handle, right._handle))

    def intersect(self, left: Shape, right: Shape) -> Shape:
        self._same_model(left, right)
        return Shape(self.session, self.session.intersect(left._handle, right._handle))

    def distance(self, left: Shape, right: Shape) -> float:
        self._same_model(left, right)
        return self.session.distance(left._handle, right._handle)

    def translate(self, shape: Shape, x: float, y: float, z: float) -> Shape:
        self._same_model(shape)
        return Shape(self.session, self.session.translate(shape._handle, x, y, z))

    def rotate(
        self,
        shape: Shape,
        degrees: float,
        axis: tuple[float, float, float] = (0, 0, 1),
        origin: tuple[float, float, float] = (0, 0, 0),
    ) -> Shape:
        self._same_model(shape)
        return Shape(self.session, self.session.rotate(shape._handle, origin, axis, degrees))

    def mirror(
        self,
        shape: Shape,
        normal: tuple[float, float, float],
        origin: tuple[float, float, float] = (0, 0, 0),
    ) -> Shape:
        self._same_model(shape)
        return Shape(self.session, self.session.mirror(shape._handle, origin, normal))

    def scale(
        self,
        shape: Shape,
        factor: float,
        center: tuple[float, float, float] = (0, 0, 0),
    ) -> Shape:
        self._same_model(shape)
        return Shape(self.session, self.session.scale(shape._handle, factor, center))

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def _same_model(self, *shapes: Shape) -> None:
        if any(shape._session is not self.session for shape in shapes):
            raise ValueError("all shapes must belong to this Model")

    def __enter__(self) -> "Model":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def native_model() -> Model:
    return Model()


def legacy_api() -> Any:
    """Return the complete pre-refactor API for compatibility operations."""
    from .legacy import api

    return api()
