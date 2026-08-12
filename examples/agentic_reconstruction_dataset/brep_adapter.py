"""Narrow OpenCascade adapters for operations CadFlow does not expose yet."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cadflow as cad
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from cadflow.inspect import brep


def heal_same_domain_rsolid(
    *,
    solid: cad.Solid,
    linear_tolerance_mm: float,
    output_step: str | Path,
) -> tuple[cad.Solid, dict[str, Any]]:
    """Unify nearly coplanar faces and export the healed solid.

    CadFlow's public ``union_rsolid(clean=True)`` enables same-domain cleanup,
    but currently does not expose the cleanup algorithm's linear tolerance.
    Reconstruction JSON can contain float32 sketch coordinates next to exact
    feature dimensions, so nominally coplanar faces may differ by less than a
    micrometre and retain splitter edges. This adapter is intentionally small
    and keeps that kernel-specific policy outside the Fusion parser.
    """

    tolerance = float(linear_tolerance_mm)
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("linear_tolerance_mm must be finite and greater than zero")

    before = _topology_summary(solid)
    unifier = ShapeUpgrade_UnifySameDomain(solid.wrapped, True, True, True)
    unifier.SetLinearTolerance(tolerance)
    unifier.Build()
    healed_in_memory = cad.Solid(unifier.Shape())
    in_memory_valid = bool(BRepCheck_Analyzer(healed_in_memory.wrapped).IsValid())

    destination = Path(output_step).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    cad.export_step(shapes=healed_in_memory, filename=str(destination))
    healed = cad.Solid(
        brep.load_step_rshape(
            destination,
            require_single_root=True,
            require_valid=True,
        )
    )
    after = _topology_summary(healed)
    return healed, {
        "output_step": str(destination),
        "linear_tolerance_mm": tolerance,
        "before": before,
        "after": after,
        "in_memory_shape_valid_before_step_roundtrip": in_memory_valid,
        "step_roundtrip_required": not in_memory_valid,
        "volume_delta_mm3": after["volume_mm3"] - before["volume_mm3"],
        "backend_calls": [
            "OCP.ShapeUpgrade_UnifySameDomain",
            "ShapeUpgrade_UnifySameDomain.SetLinearTolerance",
            "BRepCheck_Analyzer",
            "cadflow.export_step",
            "cadflow.inspect.brep.load_step_rshape",
        ],
        "graph_boundary": (
            "This deterministic post-process is replayed as an agent tool call; "
            "it is not represented by the current CadFlow model graph schema."
        ),
    }


def _topology_summary(solid: cad.Solid) -> dict[str, Any]:
    return {
        "valid": bool(BRepCheck_Analyzer(solid.wrapped).IsValid()),
        "volume_mm3": solid.get_volume(),
        "face_count": len(solid.get_faces()),
        "edge_count": len(solid.get_edges()),
        "vertex_count": len(
            {
                vertex.topo_id
                for edge in solid.get_edges()
                for vertex in edge.get_vertices()
            }
        ),
    }
