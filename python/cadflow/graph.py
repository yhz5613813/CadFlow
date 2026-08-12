"""Typed graph builder that executes through one native call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .native import NativeSession, ShapeHandle, _subshape_indices, _surface_grid


@dataclass(frozen=True)
class Node:
    op: str
    args: tuple[object, ...] = ()


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)

    def add(self, op: str, *args: object) -> int:
        self.nodes.append(Node(op, tuple(args)))
        return len(self.nodes) - 1

    def _compile(self) -> str:
        lines: list[str] = []
        for index, node in enumerate(self.nodes):
            args = node.args
            if node.op == "box":
                lines.append(f"box {float(args[0])} {float(args[1])} {float(args[2])}")
            elif node.op == "cylinder":
                lines.append(f"cylinder {float(args[0])} {float(args[1])}")
            elif node.op == "sphere":
                lines.append(f"sphere {float(args[0])}")
            elif node.op == "cone":
                lines.append(f"cone {float(args[0])} {float(args[1])} {float(args[2])}")
            elif node.op == "polyline":
                points = tuple(args[0])  # type: ignore[arg-type]
                closed = bool(args[1]) if len(args) > 1 else False
                coordinates = " ".join(
                    str(float(value)) for point in points for value in point
                )
                lines.append(f"polyline {int(closed)} {len(points)} {coordinates}")
            elif node.op == "circle_profile":
                radius = float(args[0])
                center = args[1] if len(args) > 1 else (0, 0, 0)
                normal = args[2] if len(args) > 2 else (0, 0, 1)
                lines.append(
                    "circle_profile "
                    + " ".join(str(float(value)) for value in (radius, *center, *normal))
                )
            elif node.op == "arc":
                points = tuple(args[0])  # type: ignore[arg-type]
                coordinates = " ".join(
                    str(float(value)) for point in points for value in point
                )
                lines.append(f"arc {coordinates}")
            elif node.op == "interpolate":
                points = tuple(args[0])  # type: ignore[arg-type]
                periodic = bool(args[1]) if len(args) > 1 else False
                tolerance = float(args[2]) if len(args) > 2 else 1e-6
                coordinates = " ".join(
                    str(float(value)) for point in points for value in point
                )
                lines.append(
                    f"interpolate {int(periodic)} {tolerance} "
                    f"{len(points)} {coordinates}"
                )
            elif node.op == "helix":
                center = args[3] if len(args) > 3 else (0, 0, 0)
                direction = args[4] if len(args) > 4 else (0, 0, 1)
                values = (args[0], args[1], args[2], *center, *direction)
                lines.append(
                    "helix " + " ".join(str(float(value)) for value in values)
                )
            elif node.op in {"import_brep", "import_stl"}:
                lines.append(f"{node.op} {args[0]}")
            elif node.op == "bspline":
                points = tuple(args[0])
                degree = int(args[1])
                knots = tuple(float(value) for value in args[2])
                multiplicities = tuple(int(value) for value in args[3])
                weights = args[4] if len(args) > 4 else None
                periodic = bool(args[5]) if len(args) > 5 else False
                values = " ".join(str(float(value)) for point in points for value in point)
                values += " " + " ".join(str(value) for value in knots)
                values += " " + " ".join(str(value) for value in multiplicities)
                if weights is not None:
                    values += " " + " ".join(str(float(value)) for value in weights)
                lines.append(f"bspline {len(points)} {degree} {len(knots)} {len(multiplicities)} {int(weights is not None)} {int(periodic)} {values}")
            elif node.op == "face":
                lines.append(f"face ${int(args[0])}")
            elif node.op == "bezier_surface":
                rows, columns, points = _surface_grid(args[0])  # type: ignore[arg-type]
                weights = args[1] if len(args) > 1 else None
                values = " ".join(str(value) for value in points)
                if weights is not None:
                    flattened_weights = [
                        float(value) for row in weights for value in row  # type: ignore[union-attr]
                    ]
                    values += " " + " ".join(str(value) for value in flattened_weights)
                lines.append(
                    f"bezier_surface {rows} {columns} {int(weights is not None)} {values}"
                )
            elif node.op == "fit_surface":
                rows, columns, points = _surface_grid(args[0])  # type: ignore[arg-type]
                tolerance = float(args[1]) if len(args) > 1 else 1e-3
                degree_min = int(args[2]) if len(args) > 2 else 3
                degree_max = int(args[3]) if len(args) > 3 else 8
                values = " ".join(str(value) for value in points)
                lines.append(
                    f"fit_surface {rows} {columns} {tolerance} "
                    f"{degree_min} {degree_max} {values}"
                )
            elif node.op == "extrude":
                lines.append(
                    f"extrude ${int(args[0])} {float(args[1])} "
                    f"{float(args[2])} {float(args[3])}"
                )
            elif node.op == "revolve":
                lines.append(
                    f"revolve ${int(args[0])} "
                    + " ".join(str(float(value)) for value in args[1:])
                )
            elif node.op in {"fillet", "chamfer"}:
                selected = args[2] if len(args) > 2 else None
                indices, count = _subshape_indices(selected)  # type: ignore[arg-type]
                suffix = "" if indices is None else " " + " ".join(
                    str(int(value)) for value in indices
                )
                lines.append(
                    f"{node.op} ${int(args[0])} {float(args[1])} {count}{suffix}"
                )
            elif node.op == "shell":
                selected = args[2] if len(args) > 2 else None
                tolerance = float(args[3]) if len(args) > 3 else 1e-3
                indices, count = _subshape_indices(selected)  # type: ignore[arg-type]
                suffix = "" if indices is None else " " + " ".join(
                    str(int(value)) for value in indices
                )
                lines.append(
                    f"shell ${int(args[0])} {float(args[1])} "
                    f"{tolerance} {count}{suffix}"
                )
            elif node.op == "loft":
                profiles = tuple(args[0])  # type: ignore[arg-type]
                solid = bool(args[1]) if len(args) > 1 else True
                ruled = bool(args[2]) if len(args) > 2 else False
                references = " ".join(f"${int(index)}" for index in profiles)
                lines.append(
                    f"loft {int(solid)} {int(ruled)} {len(profiles)} {references}"
                )
            elif node.op == "sweep":
                solid = bool(args[2]) if len(args) > 2 else True
                frenet = bool(args[3]) if len(args) > 3 else False
                lines.append(
                    f"sweep ${int(args[0])} ${int(args[1])} "
                    f"{int(solid)} {int(frenet)}"
                )
            elif node.op == "twisted_sweep":
                origin = args[3] if len(args) > 3 else (0, 0, 0)
                axis = args[4] if len(args) > 4 else (0, 0, 1)
                radius = float(args[5]) if len(args) > 5 else 1.0
                lines.append(
                    f"twisted_sweep ${int(args[0])} {float(args[1])} {float(args[2])} "
                    + " ".join(str(float(value)) for value in (*origin, *axis, radius))
                )
            elif node.op in {"ruled_surface", "shell_to_solid"}:
                if node.op == "shell_to_solid":
                    lines.append(f"shell_to_solid ${int(args[0])}")
                else:
                    lines.append(f"ruled_surface ${int(args[0])} ${int(args[1])}")
            elif node.op in {"filling_surface", "sew"}:
                values = tuple(args[0])
                tolerance = float(args[1]) if len(args) > 1 else 1e-6
                refs = " ".join(f"${int(value)}" for value in values)
                lines.append(f"{node.op} {tolerance} {len(values)} {refs}")
            elif node.op == "gordon_surface":
                profiles = tuple(args[0])
                guides = tuple(args[1])
                tolerance = float(args[2]) if len(args) > 2 else 1e-6
                refs = " ".join(f"${int(value)}" for value in (*profiles, *guides))
                lines.append(f"gordon_surface {tolerance} {len(profiles)} {len(guides)} {refs}")
            elif node.op in {"cut", "union", "intersect"}:
                lines.append(f"{node.op} ${int(args[0])} ${int(args[1])}")
            elif node.op == "translate":
                lines.append(f"translate ${int(args[0])} {float(args[1])} {float(args[2])} {float(args[3])}")
            elif node.op == "rotate":
                lines.append(
                    f"rotate ${int(args[0])} {float(args[1])} {float(args[2])} {float(args[3])} "
                    f"{float(args[4])} {float(args[5])} {float(args[6])} {float(args[7])}"
                )
            elif node.op == "mirror":
                lines.append(
                    f"mirror ${int(args[0])} "
                    + " ".join(str(float(value)) for value in args[1:])
                )
            elif node.op == "scale":
                lines.append(
                    f"scale ${int(args[0])} "
                    + " ".join(str(float(value)) for value in args[1:])
                )
            elif node.op == "distance":
                lines.append(f"distance ${int(args[0])} ${int(args[1])}")
            elif node.op in {"volume", "area", "length", "center", "kind", "bbox"}:
                lines.append(f"{node.op} ${int(args[0])}")
            else:
                raise ValueError(f"unsupported native graph operation: {node.op}")
        return "\n".join(lines)

    def execute(self, session: NativeSession | None = None) -> list[str]:
        owned = session is None
        session = session or NativeSession()
        try:
            return session.execute(self._compile())
        finally:
            if owned:
                session.close()


def __getattr__(name: str) -> Any:
    """Expose the migrated GraphSession API beside the native Graph builder."""
    from .legacy import module

    return getattr(module("graph"), name)


def __dir__() -> list[str]:
    from .legacy import module

    return sorted(set(globals()) | set(dir(module("graph"))))
