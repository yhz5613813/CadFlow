"""Small, explicit coordinate-frame API used by the Python frontend.

Frames are value objects.  A Workplane only changes how its own point and
vector arguments are interpreted; it never mutates existing shapes.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
from typing import Iterator, Sequence


def _vec(value: Sequence[float], name: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError(f"{name} must contain three coordinates")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must contain finite coordinates")
    return result


def _unit(value: Sequence[float], name: str) -> tuple[float, float, float]:
    x, y, z = _vec(value, name)
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 1e-12:
        raise ValueError(f"{name} must be non-zero")
    return (x / length, y / length, z / length)


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(left * right for left, right in zip(a, b))


@dataclass(frozen=True)
class CoordinateFrame:
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    x_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    y_axis: tuple[float, float, float] = (0.0, 1.0, 0.0)
    z_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)

    def __post_init__(self) -> None:
        origin = _vec(self.origin, "origin")
        x_axis = _unit(self.x_axis, "x_axis")
        y_axis = _unit(self.y_axis, "y_axis")
        if abs(_dot(x_axis, y_axis)) > 1e-8:
            raise ValueError("x_axis and y_axis must be perpendicular")
        z_axis = _unit(_cross(x_axis, y_axis), "z_axis")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "x_axis", x_axis)
        object.__setattr__(self, "y_axis", y_axis)
        object.__setattr__(self, "z_axis", z_axis)

    def point(self, value: Sequence[float]) -> tuple[float, float, float]:
        x, y, z = _vec(value, "point")
        return tuple(
            self.origin[i] + x * self.x_axis[i] + y * self.y_axis[i] + z * self.z_axis[i]
            for i in range(3)
        )

    def vector(self, value: Sequence[float]) -> tuple[float, float, float]:
        x, y, z = _vec(value, "vector")
        return tuple(
            x * self.x_axis[i] + y * self.y_axis[i] + z * self.z_axis[i]
            for i in range(3)
        )

    def to_dict(self) -> dict[str, list[float]]:
        return {key: list(value) for key, value in {
            "origin": self.origin, "x_axis": self.x_axis,
            "y_axis": self.y_axis, "z_axis": self.z_axis,
        }.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Sequence[float]]) -> "CoordinateFrame":
        return cls(
            origin=tuple(data.get("origin", (0, 0, 0))),
            x_axis=tuple(data.get("x_axis", (1, 0, 0))),
            y_axis=tuple(data.get("y_axis", (0, 1, 0))),
        )


WORLD_FRAME = CoordinateFrame()
_frames: ContextVar[tuple[CoordinateFrame, ...]] = ContextVar(
    "cadflow_frontend_frames", default=(WORLD_FRAME,)
)


def current_frame() -> CoordinateFrame:
    return _frames.get()[-1]


class Workplane:
    """Context manager and factory for local sketches."""

    def __init__(
        self,
        origin: Sequence[float] = (0, 0, 0),
        normal: Sequence[float] = (0, 0, 1),
        x_dir: Sequence[float] = (1, 0, 0),
        *,
        parent: CoordinateFrame | None = None,
        model: object | None = None,
    ) -> None:
        parent = parent or current_frame()
        global_origin = parent.point(origin)
        global_normal = _unit(parent.vector(normal), "normal")
        global_x = parent.vector(x_dir)
        # Project x_dir onto the plane, then derive a right-handed y axis.
        projection = _dot(global_x, global_normal)
        global_x = tuple(global_x[i] - projection * global_normal[i] for i in range(3))
        if math.sqrt(_dot(global_x, global_x)) <= 1e-12:
            # A default X direction is commonly parallel to a YZ workplane.
            # Pick a deterministic parent axis in that case, matching normal
            # CAD workplane ergonomics while retaining a right-handed frame.
            candidates = (parent.x_axis, parent.y_axis, parent.z_axis)
            global_x = min(
                candidates,
                key=lambda candidate: abs(_dot(candidate, global_normal)),
            )
        global_x = _unit(global_x, "x_dir")
        global_y = _unit(_cross(global_normal, global_x), "workplane y axis")
        self.frame = CoordinateFrame(global_origin, global_x, global_y)
        self._model = model
        self._token = None
        self._engine_context = None

    def __enter__(self) -> "Workplane":
        self._token = _frames.set((*_frames.get(), self.frame))
        # Keep the compatibility domain's ambient frame synchronized while
        # retaining this frontend's explicit value object as the source of
        # truth. Existing functional operations therefore compose correctly.
        from .legacy import module
        self._engine_context = module("core").use_coordinate_system(self.frame.to_dict())
        self._engine_context.__enter__()
        return self

    def __exit__(self, *_: object) -> None:
        if self._token is not None:
            if self._engine_context is not None:
                self._engine_context.__exit__(None, None, None)
                self._engine_context = None
            _frames.reset(self._token)
            self._token = None

    def point(self, value: Sequence[float]) -> tuple[float, float, float]:
        return self.frame.point(value)

    def vector(self, value: Sequence[float]) -> tuple[float, float, float]:
        return self.frame.vector(value)

    def sketch(self, name: str | None = None):
        from .sketch_api import SketchDocument
        return SketchDocument.create(name, frame=self.frame)

    def _require_model(self):
        if self._model is None:
            raise RuntimeError("this Workplane is not attached to a Model")
        return self._model

    def polyline(self, points: Sequence[Sequence[float]], *, closed: bool = False):
        model = self._require_model()
        return model.polyline([self.point(point) for point in points], closed=closed)

    def circle_profile(self, radius: float, center: Sequence[float] = (0, 0, 0)):
        model = self._require_model()
        return model.circle_profile(
            radius, center=self.point(center), normal=self.frame.z_axis
        )

    def arc(self, start: Sequence[float], middle: Sequence[float], end: Sequence[float]):
        model = self._require_model()
        return model.arc(self.point(start), self.point(middle), self.point(end))

    def interpolate(self, points: Sequence[Sequence[float]], **kwargs: object):
        model = self._require_model()
        return model.interpolate([self.point(point) for point in points], **kwargs)

    def helix(self, pitch: float, height: float, radius: float, **kwargs: object):
        model = self._require_model()
        center = self.point(kwargs.pop("center", (0, 0, 0)))
        direction = self.vector(kwargs.pop("direction", (0, 0, 1)))
        return model.helix(pitch, height, radius, center=center, direction=direction)

    def extrude(self, profile, vector: Sequence[float]):
        model = self._require_model()
        direction = self.vector(vector)
        return model.extrude(profile, *direction)


@contextmanager
def use_frame(frame: CoordinateFrame) -> Iterator[None]:
    token = _frames.set((*_frames.get(), frame))
    try:
        yield
    finally:
        _frames.reset(token)
