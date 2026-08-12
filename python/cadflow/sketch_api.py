"""Modern, session-independent facade for CadFlow's declarative sketches.

The compatibility engine owns the constraint vocabulary and the py-slvs
adapter.  This module only supplies a small object-oriented entry point for
``Model.sketch()`` and keeps lowering/export decisions out of the solver.
"""

from __future__ import annotations

from typing import Any, Sequence

from .frame import CoordinateFrame, current_frame
from .legacy import module


_ops = module("operations")
_sketch_types = module("sketch")
EngineSketch = _sketch_types.Sketch
SketchRef = _sketch_types.SketchRef
SketchSolveResult = _sketch_types.SketchSolveResult


def _plane_payload(frame: CoordinateFrame) -> dict[str, tuple[float, float, float]]:
    return {
        "origin": frame.origin,
        "x_axis": frame.x_axis,
        "y_axis": frame.y_axis,
    }


class SketchDocument:
    """Design-intent sketch with stable entity references and constraints.

    Methods return a new document, matching the existing functional sketch
    operations.  ``to_face()`` produces the compatibility OCP face; use
    ``to_native_face(model)`` for profiles supported by the C++ session.
    """

    def __init__(self, engine_sketch: EngineSketch):
        self._engine = engine_sketch

    @classmethod
    def create(
        cls,
        name: str | None = None,
        *,
        frame: CoordinateFrame | None = None,
        sketch_id: str | None = None,
    ) -> "SketchDocument":
        frame = frame or current_frame()
        # ``frame`` is already expressed in world coordinates. Calling the
        # compatibility operation here would apply the ambient frame a second
        # time when this factory is used inside a Workplane context.
        return cls(EngineSketch(name=name, plane=_plane_payload(frame), sketch_id=sketch_id))

    @property
    def name(self) -> str | None:
        return self._engine.name

    @property
    def sketch_id(self) -> str:
        return self._engine.sketch_id

    @property
    def frame(self) -> CoordinateFrame:
        origin, x_axis, y_axis, _normal = self._engine._plane_frame()
        return CoordinateFrame(tuple(origin), tuple(x_axis), tuple(y_axis))

    @property
    def entities(self):
        return self._engine.entities

    @property
    def constraints(self):
        return self._engine.constraints

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "sketch",
            "id": self.sketch_id,
            "name": self.name,
            "frame": self.frame.to_dict(),
            "entities": len(self.entities),
            "constraints": len(self.constraints),
        }

    def _updated(self, value: EngineSketch) -> "SketchDocument":
        return type(self)(value)

    def add_point(self, point_id: str, x: Any, y: Any) -> "SketchDocument":
        return self._updated(_ops.add_point_rsketch(self._engine, point_id, x, y))

    def add_line(
        self, entity_id: str, start: SketchRef | str, end: SketchRef | str,
        *, construction: bool = False,
    ) -> "SketchDocument":
        return self._updated(_ops.add_line_rsketch(
            self._engine, entity_id, start, end, construction=construction
        ))

    def add_circle(
        self, entity_id: str, center: SketchRef | str, radius: Any,
        *, construction: bool = False,
    ) -> "SketchDocument":
        return self._updated(_ops.add_circle_rsketch(
            self._engine, entity_id, center, radius, construction=construction
        ))

    def add_arc(
        self, entity_id: str, start: SketchRef | str, end: SketchRef | str,
        center: SketchRef | str, *, construction: bool = False,
    ) -> "SketchDocument":
        return self._updated(_ops.add_arc_rsketch(
            self._engine, entity_id, start, end, center, construction=construction
        ))

    def add_bspline(
        self, entity_id: str, start: SketchRef | str, end: SketchRef | str,
        control_points: Sequence[Any], degree: int = 3, **kwargs: Any,
    ) -> "SketchDocument":
        return self._updated(_ops.add_bspline_rsketch(
            self._engine, entity_id, start, end, control_points,
            degree=degree, **kwargs,
        ))

    point = add_point
    line = add_line
    circle = add_circle
    arc = add_arc

    def point_ref(self, point_id: str) -> SketchRef:
        return _ops.get_sketch_point_rsketchref(self._engine, point_id)

    def ref(self, entity_id: str) -> SketchRef:
        return _ops.get_sketch_entity_rsketchref(self._engine, entity_id)

    def solve(self, **options: Any) -> SketchSolveResult:
        return self._engine.solve(**options)

    def inspect(self, **options: Any) -> SketchSolveResult:
        return _ops.inspect_sketch_rsketchresult(self._engine, **options)

    def to_face(self, **options: Any):
        return _ops.make_face_from_sketch_rface(self._engine, **options)

    def to_wire(self, **options: Any):
        return _ops.make_wire_from_sketch_rwire(self._engine, **options)

    def to_native_face(self, model: Any, *, profile: int | str = 0, **options: Any):
        """Lower a single circle or polygon profile through ``cad.Model``.

        Rich curves remain available through ``to_face``.  Keeping this
        lowering explicit prevents compatibility OCP objects from crossing the
        opaque native-handle boundary.
        """
        result = self.inspect(**options)
        profiles = self._engine._profiles_from_solution(result)
        if isinstance(profile, int):
            selected = profiles[int(profile)]
        else:
            try:
                selected = next(item for item in profiles if item["id"] == profile)
            except StopIteration as error:
                raise ValueError(f"unknown sketch profile: {profile}") from error
        if selected["kind"] == "circle":
            wire = model.circle_profile(
                selected["radius"],
                center=selected["center"],
                normal=selected["normal"],
            )
        elif selected["kind"] in {"line_loop", "edge_loop"} and all(
            self.entities[entity_id].kind == "line"
            for entity_id in selected["entity_ids"]
        ):
            wire = model.polyline(selected["points"], closed=True)
        else:
            raise ValueError(
                "native lowering currently supports circle and line-loop profiles; "
                "use to_face() for arc/B-spline profiles"
            )
        return model.face(wire)

    # Keep the full established constraint vocabulary without duplicating it.
    def _constraint(self, operation: str, *args: Any, **kwargs: Any) -> "SketchDocument":
        return self._updated(getattr(_ops, operation)(self._engine, *args, **kwargs))

    def constrain_coincident(self, a, b, **kwargs):
        return self._constraint("constrain_coincident_rsketch", a, b, **kwargs)

    def constrain_connect(self, a, b, **kwargs):
        return self._constraint("constrain_connect_rsketch", a, b, **kwargs)

    def constrain_point_on(self, point, entity, **kwargs):
        return self._constraint("constrain_point_on_rsketch", point, entity, **kwargs)

    def constrain_horizontal(self, line, **kwargs):
        return self._constraint("constrain_horizontal_rsketch", line, **kwargs)

    def constrain_vertical(self, line, **kwargs):
        return self._constraint("constrain_vertical_rsketch", line, **kwargs)

    def constrain_parallel(self, a, b, **kwargs):
        return self._constraint("constrain_parallel_rsketch", a, b, **kwargs)

    def constrain_perpendicular(self, a, b, **kwargs):
        return self._constraint("constrain_perpendicular_rsketch", a, b, **kwargs)

    def constrain_collinear(self, a, b, **kwargs):
        return self._constraint("constrain_collinear_rsketch", a, b, **kwargs)

    def constrain_tangent(self, a, b, **kwargs):
        return self._constraint("constrain_tangent_rsketch", a, b, **kwargs)

    def constrain_concentric(self, a, b, **kwargs):
        return self._constraint("constrain_concentric_rsketch", a, b, **kwargs)

    def constrain_midpoint(self, point, line, **kwargs):
        return self._constraint("constrain_midpoint_rsketch", point, line, **kwargs)

    def constrain_symmetric(self, a, b, axis, **kwargs):
        return self._constraint("constrain_symmetric_rsketch", a, b, axis, **kwargs)

    def constrain_equal_length(self, a, b, **kwargs):
        return self._constraint("constrain_equal_length_rsketch", a, b, **kwargs)

    def constrain_equal_radius(self, a, b, **kwargs):
        return self._constraint("constrain_equal_radius_rsketch", a, b, **kwargs)

    def constrain_distance(self, a, b, value, **kwargs):
        return self._constraint("constrain_distance_rsketch", a, b, value, **kwargs)

    def constrain_distance_x(self, a, b, value, **kwargs):
        return self._constraint("constrain_distance_x_rsketch", a, b, value, **kwargs)

    def constrain_distance_y(self, a, b, value, **kwargs):
        return self._constraint("constrain_distance_y_rsketch", a, b, value, **kwargs)

    def constrain_length(self, entity, value, **kwargs):
        return self._constraint("constrain_length_rsketch", entity, value, **kwargs)

    def constrain_angle(self, a, b, value, **kwargs):
        return self._constraint("constrain_angle_rsketch", a, b, value, **kwargs)

    def constrain_radius(self, entity, value, **kwargs):
        return self._constraint("constrain_radius_rsketch", entity, value, **kwargs)

    def constrain_diameter(self, entity, value, **kwargs):
        return self._constraint("constrain_diameter_rsketch", entity, value, **kwargs)

    def constrain_fix(self, entity, **kwargs):
        return self._constraint("constrain_fix_rsketch", entity, **kwargs)


__all__ = ["SketchDocument", "SketchRef", "SketchSolveResult"]
