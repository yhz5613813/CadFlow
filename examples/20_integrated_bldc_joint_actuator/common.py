"""Shared construction, tagging, connector, and grounding helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable

import cadflow as cad
from cadflow import ql


@cad.requires_session
def apply_tags(*, shape: cad.Solid, tags: Iterable[str]) -> cad.Solid:
    """Apply semantic tags through the public functional API."""

    tagged = shape
    for tag in tags:
        tagged = cad.apply_tag(shape=tagged, tag=tag)
    return tagged


@cad.requires_session
def make_annulus_rsolid(
    *,
    outer_radius: float,
    inner_radius: float,
    bottom_z: float,
    height: float,
    tag_prefix: str,
    tags: Iterable[str],
) -> cad.Solid:
    """Create a strict single-solid annular cylinder."""

    outer = cad.make_cylinder_rsolid(
        radius=outer_radius,
        height=height,
        bottom_face_center=(0.0, 0.0, bottom_z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{tag_prefix}.outer",
        result_tag=f"feature.{tag_prefix}.outer",
    )
    bore = cad.make_cylinder_rsolid(
        radius=inner_radius,
        height=height + 2.0,
        bottom_face_center=(0.0, 0.0, bottom_z - 1.0),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=f"{tag_prefix}.bore",
        result_tag=f"tool.{tag_prefix}.bore",
    )
    annulus = cad.cut_rsolid(outer, bore, skip_non_intersecting=False)
    return apply_tags(shape=annulus, tags=tags)


@cad.requires_session
def make_axis_part_rpart(
    *,
    part_id: str,
    body: cad.Solid,
    name: str,
    material: cad.Material,
    connectors: Iterable[tuple[str, tuple[float, float, float], str]],
) -> cad.Part:
    """Create a single-body part with stable placement-based axis datums."""

    part = cad.make_part_rpart(part_id=part_id, body=body, name=name)
    part = cad.assign_material_rpart(part=part, material=material)
    connector_count = 0
    for connector_id, origin, connector_name in connectors:
        connector = cad.make_placement_connector_rconnector(
            connector_id=connector_id,
            placement=cad.make_placement_rplacement(origin=origin),
            name=connector_name,
        )
        part = cad.add_connector_rpart(part=part, connector=connector)
        connector_count += 1
    ground_solid(label=part_id, solid=body)
    print(f"part_{part_id}: connectors={connector_count} material={material.material_id}")
    return part


@cad.requires_session
def make_z_rotation_rplacement(
    *,
    origin: tuple[float, float, float],
    angle_degrees: float,
) -> cad.Placement:
    """Return a right-handed placement rotated about Z."""

    angle = math.radians(angle_degrees)
    return cad.make_placement_rplacement(
        origin=origin,
        x_axis=(math.cos(angle), math.sin(angle), 0.0),
        y_axis=(-math.sin(angle), math.cos(angle), 0.0),
    )


def radial_centers(*, count: int, radius: float, angle_offset: float = 0.0):
    """Yield index, angle in degrees, and XY center on a bolt/pole circle."""

    for index in range(count):
        angle_degrees = angle_offset + 360.0 * index / count
        angle = math.radians(angle_degrees)
        yield index, angle_degrees, (radius * math.cos(angle), radius * math.sin(angle))


@cad.requires_session
def make_axial_hole_cutters_rsolids(
    *,
    count: int,
    pcd: float,
    hole_radius: float,
    bottom_z: float,
    height: float,
    tag_prefix: str,
    angle_offset: float = 0.0,
) -> list[cad.Solid]:
    """Create equally spaced axial hole cutters."""

    cutters = []
    for index, _angle, center in radial_centers(
        count=count,
        radius=pcd / 2.0,
        angle_offset=angle_offset,
    ):
        cutters.append(
            cad.make_cylinder_rsolid(
                radius=hole_radius,
                height=height,
                bottom_face_center=(center[0], center[1], bottom_z),
                axis=(0.0, 0.0, 1.0),
                tag_prefix=f"{tag_prefix}.hole{index + 1}",
                result_tag=f"tool.{tag_prefix}.hole{index + 1}",
            )
        )
    return cutters


def ground_solid(*, label: str, solid: cad.Solid) -> None:
    """Print a concise QL-backed solid summary."""

    faces = ql.select(items=solid.get_faces()).all()
    local_roles = [
        tag
        for tag in cad.list_tags(shape=solid, scope="local")
        if tag.startswith("role.")
    ]
    print(
        f"{label}: faces={len(faces)} local_roles={len(local_roles)} "
        f"volume={solid.get_volume():.3f} tags={','.join(cad.list_tags(shape=solid))}"
    )


def ground_compound(*, label: str, compound: cad.Compound) -> None:
    """Print a concise QL-backed assembly projection summary."""

    solids = ql.select(items=compound.get_solids()).all()
    faces = sum(len(ql.select(items=solid.get_faces()).all()) for solid in solids)
    volume = sum(solid.get_volume() for solid in solids)
    print(f"{label}: solids={len(solids)} faces={faces} volume={volume:.3f}")


@cad.requires_session
def connector_ref(*, component_id: str, connector_id: str) -> cad.ConnectorRef:
    """Create a component-scoped connector reference."""

    return cad.make_connector_ref_rconnectorref(
        component_id=component_id,
        connector_id=connector_id,
    )


def ground_constraint_report(*, label: str, assembly: cad.Assembly) -> None:
    """Print solved state and only non-zero residual facts."""

    report = cad.inspect_assembly_constraints_rconstraintreport(assembly=assembly)
    worst_translation = max((item.translation_error for item in report.residuals), default=0.0)
    worst_angle = max((item.angular_error_degrees for item in report.residuals), default=0.0)
    print(
        f"{label}_constraints: solved={report.solved} components={len(assembly.component_ids())} "
        f"constraints={len(assembly.constraint_ids())} unsolved={len(report.unsolved_component_ids)} "
        f"max_translation={worst_translation:.6g} max_angle={worst_angle:.6g}"
    )
