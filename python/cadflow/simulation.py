"""Solver-neutral surface contact semantics and native BREP evidence.

The objects in this module describe distributed face interactions for finite-
element and other continuum preprocessors. They are deliberately separate from
``PhysicalConnection``, whose stiffness values define a concentrated 6-DOF law.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, ClassVar, Mapping, Optional, Sequence

from ._engine.assembly.product import Assembly, GeometryRef, Part


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value.strip()):
        raise ValueError(
            f"{field_name} must start with a letter and contain only letters, "
            "digits, underscore, dash, dot, or colon"
        )
    return value.strip()


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _positive(value: Any, field_name: str) -> float:
    result = _finite(value, field_name)
    if result <= 0.0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _optional_non_negative(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    result = _finite(value, field_name)
    if result < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _metadata(value: Mapping[str, Any] | None, field_name: str = "metadata") -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be a string-keyed mapping")
    return json.loads(json.dumps(dict(value), allow_nan=False, sort_keys=True))


def _enum(value: Any, enum_type: type[Enum], field_name: str) -> str:
    raw = value.value if isinstance(value, enum_type) else value
    try:
        return str(enum_type(str(raw)).value)
    except ValueError as error:
        raise ValueError(
            f"{field_name} must be one of: " + ", ".join(item.value for item in enum_type)
        ) from error


class SurfaceRole(str, Enum):
    CONTACT = "contact"
    ADHESIVE = "adhesive"
    COHESIVE = "cohesive"
    BEARING = "bearing"
    LOAD = "load"
    SUPPORT = "support"
    THERMAL = "thermal"
    CUSTOM = "custom"


class NormalContactModel(str, Enum):
    HARD = "hard"
    PENALTY = "penalty"
    TABULAR = "tabular"
    COHESIVE = "cohesive"


class FrictionModel(str, Enum):
    FRICTIONLESS = "frictionless"
    COULOMB = "coulomb"


class SlidingFormulation(str, Enum):
    SMALL = "small"
    FINITE = "finite"


@dataclass(frozen=True)
class MechanicalMaterial:
    """Isotropic structural material in the owning model's explicit units."""

    material_id: str
    youngs_modulus: float
    poisson_ratio: float
    density: float | None = None
    yield_stress: float | None = None
    thermal_expansion: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_id", _identifier(self.material_id, "material_id"))
        object.__setattr__(self, "youngs_modulus", _positive(self.youngs_modulus, "youngs_modulus"))
        ratio = _finite(self.poisson_ratio, "poisson_ratio")
        if not (-1.0 < ratio < 0.5):
            raise ValueError("poisson_ratio must be between -1 and 0.5")
        object.__setattr__(self, "poisson_ratio", ratio)
        for name in ("density", "yield_stress", "thermal_expansion"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _positive(value, name))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "youngs_modulus": self.youngs_modulus,
            "poisson_ratio": self.poisson_ratio,
            "density": self.density,
            "yield_stress": self.yield_stress,
            "thermal_expansion": self.thermal_expansion,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MechanicalMaterial":
        return cls(**dict(value))


@dataclass(frozen=True)
class SurfaceProperty:
    """Intrinsic properties of one manufactured surface, not a surface pair."""

    property_id: str
    roughness_average: float | None = None
    coating_material_id: str | None = None
    coating_thickness: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "property_id", _identifier(self.property_id, "property_id"))
        object.__setattr__(self, "roughness_average", _optional_non_negative(self.roughness_average, "roughness_average"))
        object.__setattr__(self, "coating_thickness", _optional_non_negative(self.coating_thickness, "coating_thickness"))
        if self.coating_material_id is not None:
            object.__setattr__(self, "coating_material_id", _identifier(self.coating_material_id, "coating_material_id"))
        if self.coating_thickness is not None and self.coating_material_id is None:
            raise ValueError("coating_thickness requires coating_material_id")
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "roughness_average": self.roughness_average,
            "coating_material_id": self.coating_material_id,
            "coating_thickness": self.coating_thickness,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurfaceProperty":
        return cls(**dict(value))


@dataclass(frozen=True)
class SurfaceRegion:
    """A named set of replayable component-local BREP faces."""

    surface_id: str
    component_id: str
    geometry_refs: tuple[GeometryRef, ...]
    role: SurfaceRole | str = SurfaceRole.CONTACT
    property_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "surface_id", _identifier(self.surface_id, "surface_id"))
        object.__setattr__(self, "component_id", _identifier(self.component_id, "component_id"))
        refs = tuple(self.geometry_refs or ())
        if not refs or any(not isinstance(ref, GeometryRef) or ref.kind != "face" for ref in refs):
            raise ValueError("geometry_refs must contain at least one face GeometryRef")
        serialized = [json.dumps(ref.to_dict(), sort_keys=True) for ref in refs]
        if len(serialized) != len(set(serialized)):
            raise ValueError("geometry_refs must be unique within a SurfaceRegion")
        object.__setattr__(self, "geometry_refs", refs)
        object.__setattr__(self, "role", _enum(self.role, SurfaceRole, "role"))
        if self.property_id is not None:
            object.__setattr__(self, "property_id", _identifier(self.property_id, "property_id"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "component_id": self.component_id,
            "geometry_refs": [ref.to_dict() for ref in self.geometry_refs],
            "role": self.role,
            "property_id": self.property_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurfaceRegion":
        data = dict(value)
        data["geometry_refs"] = tuple(_geometry_ref(item) for item in data["geometry_refs"])
        return cls(**data)


@dataclass(frozen=True)
class SurfaceContactLaw:
    """Distributed traction/separation law; penalty units are force/length^3."""

    law_id: str
    normal_model: NormalContactModel | str = NormalContactModel.HARD
    allow_separation: bool = True
    normal_penalty_stiffness: float | None = None
    pressure_overclosure: tuple[tuple[float, float], ...] = ()
    friction_model: FrictionModel | str = FrictionModel.FRICTIONLESS
    friction_coefficient: float = 0.0
    tangential_penalty_stiffness: float | None = None
    normal_damping_per_area: float = 0.0
    cohesive_tensile_strength: float | None = None
    cohesive_shear_strength: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "law_id", _identifier(self.law_id, "law_id"))
        object.__setattr__(self, "normal_model", _enum(self.normal_model, NormalContactModel, "normal_model"))
        object.__setattr__(self, "friction_model", _enum(self.friction_model, FrictionModel, "friction_model"))
        object.__setattr__(self, "allow_separation", bool(self.allow_separation))
        object.__setattr__(self, "normal_penalty_stiffness", _optional_non_negative(self.normal_penalty_stiffness, "normal_penalty_stiffness"))
        object.__setattr__(self, "tangential_penalty_stiffness", _optional_non_negative(self.tangential_penalty_stiffness, "tangential_penalty_stiffness"))
        object.__setattr__(self, "normal_damping_per_area", _finite(self.normal_damping_per_area, "normal_damping_per_area"))
        if self.normal_damping_per_area < 0.0:
            raise ValueError("normal_damping_per_area must be non-negative")
        coefficient = _finite(self.friction_coefficient, "friction_coefficient")
        if coefficient < 0.0:
            raise ValueError("friction_coefficient must be non-negative")
        object.__setattr__(self, "friction_coefficient", coefficient)
        for name in ("cohesive_tensile_strength", "cohesive_shear_strength"):
            object.__setattr__(self, name, _optional_non_negative(getattr(self, name), name))

        curve = tuple((_finite(item[0], "overclosure"), _finite(item[1], "pressure")) for item in self.pressure_overclosure)
        if any(overclosure < 0.0 or pressure < 0.0 for overclosure, pressure in curve):
            raise ValueError("pressure_overclosure values must be non-negative")
        if any(curve[index][0] <= curve[index - 1][0] for index in range(1, len(curve))):
            raise ValueError("pressure_overclosure closure values must increase strictly")
        object.__setattr__(self, "pressure_overclosure", curve)
        if self.normal_model == NormalContactModel.PENALTY.value and not self.normal_penalty_stiffness:
            raise ValueError("penalty normal contact requires normal_penalty_stiffness")
        if self.normal_model == NormalContactModel.TABULAR.value and len(curve) < 2:
            raise ValueError("tabular normal contact requires at least two pressure_overclosure points")
        if self.normal_model != NormalContactModel.TABULAR.value and curve:
            raise ValueError("pressure_overclosure is only valid for tabular normal contact")
        if self.friction_model == FrictionModel.FRICTIONLESS.value and coefficient != 0.0:
            raise ValueError("frictionless contact requires friction_coefficient=0")
        if self.friction_model == FrictionModel.COULOMB.value and coefficient <= 0.0:
            raise ValueError("Coulomb contact requires a positive friction_coefficient")
        if self.normal_model == NormalContactModel.COHESIVE.value and not (
            self.cohesive_tensile_strength and self.cohesive_shear_strength
        ):
            raise ValueError("cohesive contact requires tensile and shear strengths")
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "law_id": self.law_id,
            "normal_model": self.normal_model,
            "allow_separation": self.allow_separation,
            "normal_penalty_stiffness": self.normal_penalty_stiffness,
            "pressure_overclosure": [list(item) for item in self.pressure_overclosure],
            "friction_model": self.friction_model,
            "friction_coefficient": self.friction_coefficient,
            "tangential_penalty_stiffness": self.tangential_penalty_stiffness,
            "normal_damping_per_area": self.normal_damping_per_area,
            "cohesive_tensile_strength": self.cohesive_tensile_strength,
            "cohesive_shear_strength": self.cohesive_shear_strength,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurfaceContactLaw":
        data = dict(value)
        data["pressure_overclosure"] = tuple(tuple(item) for item in data.get("pressure_overclosure", ()))
        return cls(**data)


@dataclass(frozen=True)
class SurfaceContactPair:
    pair_id: str
    surface_a_id: str
    surface_b_id: str
    law_id: str
    initial_clearance: float = 0.0
    interference: float = 0.0
    search_tolerance: float = 0.0
    minimum_opposed_normal_cosine: float = 0.5
    sliding: SlidingFormulation | str = SlidingFormulation.FINITE
    activation_step: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        for name in ("pair_id", "surface_a_id", "surface_b_id", "law_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.surface_a_id == self.surface_b_id:
            raise ValueError("surface_a_id and surface_b_id must differ")
        for name in ("initial_clearance", "interference", "search_tolerance"):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)
        if self.initial_clearance > 0.0 and self.interference > 0.0:
            raise ValueError("initial_clearance and interference cannot both be positive")
        cosine = _finite(self.minimum_opposed_normal_cosine, "minimum_opposed_normal_cosine")
        if not 0.0 <= cosine <= 1.0:
            raise ValueError("minimum_opposed_normal_cosine must be in [0, 1]")
        object.__setattr__(self, "minimum_opposed_normal_cosine", cosine)
        object.__setattr__(self, "sliding", _enum(self.sliding, SlidingFormulation, "sliding"))
        if self.activation_step is not None:
            object.__setattr__(self, "activation_step", _identifier(self.activation_step, "activation_step"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "surface_a_id": self.surface_a_id,
            "surface_b_id": self.surface_b_id,
            "law_id": self.law_id,
            "initial_clearance": self.initial_clearance,
            "interference": self.interference,
            "search_tolerance": self.search_tolerance,
            "minimum_opposed_normal_cosine": self.minimum_opposed_normal_cosine,
            "sliding": self.sliding,
            "activation_step": self.activation_step,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurfaceContactPair":
        return cls(**dict(value))


@dataclass(frozen=True)
class ContactSimulationModel:
    SCHEMA_VERSION: ClassVar[str] = "1.0"

    assembly_id: str
    surfaces: tuple[SurfaceRegion, ...] = ()
    contact_laws: tuple[SurfaceContactLaw, ...] = ()
    contact_pairs: tuple[SurfaceContactPair, ...] = ()
    surface_properties: tuple[SurfaceProperty, ...] = ()
    materials: tuple[MechanicalMaterial, ...] = ()
    component_materials: dict[str, str] = field(default_factory=dict)
    length_unit: str = "mm"
    force_unit: str = "N"
    time_unit: str = "s"
    temperature_unit: str = "K"
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "assembly_id", _identifier(self.assembly_id, "assembly_id"))
        collections = (
            ("surfaces", SurfaceRegion, "surface_id"),
            ("contact_laws", SurfaceContactLaw, "law_id"),
            ("contact_pairs", SurfaceContactPair, "pair_id"),
            ("surface_properties", SurfaceProperty, "property_id"),
            ("materials", MechanicalMaterial, "material_id"),
        )
        for field_name, item_type, id_name in collections:
            values = tuple(getattr(self, field_name) or ())
            if any(not isinstance(value, item_type) for value in values):
                raise TypeError(f"{field_name} contains an invalid value")
            ids = [getattr(value, id_name) for value in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field_name} ids must be unique")
            object.__setattr__(self, field_name, values)
        assignments = {
            _identifier(component, "component_id"): _identifier(material, "material_id")
            for component, material in dict(self.component_materials).items()
        }
        object.__setattr__(self, "component_materials", assignments)
        for name in ("length_unit", "force_unit", "time_unit", "temperature_unit"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def with_surface(self, value: SurfaceRegion) -> "ContactSimulationModel":
        return replace(self, surfaces=(*self.surfaces, value))

    def with_contact_law(self, value: SurfaceContactLaw) -> "ContactSimulationModel":
        return replace(self, contact_laws=(*self.contact_laws, value))

    def with_contact_pair(self, value: SurfaceContactPair) -> "ContactSimulationModel":
        return replace(self, contact_pairs=(*self.contact_pairs, value))

    def with_surface_property(self, value: SurfaceProperty) -> "ContactSimulationModel":
        return replace(self, surface_properties=(*self.surface_properties, value))

    def with_material(self, value: MechanicalMaterial) -> "ContactSimulationModel":
        return replace(self, materials=(*self.materials, value))

    def assign_material(self, component_id: str, material_id: str) -> "ContactSimulationModel":
        assignments = dict(self.component_materials)
        assignments[_identifier(component_id, "component_id")] = _identifier(material_id, "material_id")
        return replace(self, component_materials=assignments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "cadflow-contact-simulation",
            "schema_version": self.SCHEMA_VERSION,
            "assembly_id": self.assembly_id,
            "units": {
                "length": self.length_unit,
                "force": self.force_unit,
                "time": self.time_unit,
                "temperature": self.temperature_unit,
                "pressure": f"{self.force_unit}/{self.length_unit}^2",
                "contact_penalty": f"{self.force_unit}/{self.length_unit}^3",
                "contact_damping_per_area": f"{self.force_unit}*{self.time_unit}/{self.length_unit}^3",
                "density": f"{self.force_unit}*{self.time_unit}^2/{self.length_unit}^4",
                "thermal_expansion": f"1/{self.temperature_unit}",
            },
            "surfaces": [item.to_dict() for item in self.surfaces],
            "surface_properties": [item.to_dict() for item in self.surface_properties],
            "contact_laws": [item.to_dict() for item in self.contact_laws],
            "contact_pairs": [item.to_dict() for item in self.contact_pairs],
            "materials": [item.to_dict() for item in self.materials],
            "component_materials": dict(sorted(self.component_materials.items())),
            "metadata": dict(self.metadata),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContactSimulationModel":
        if value.get("schema") != "cadflow-contact-simulation" or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported contact simulation schema")
        units = value.get("units")
        if not isinstance(units, Mapping):
            raise ValueError("contact simulation units are missing")
        return cls(
            assembly_id=value["assembly_id"],
            surfaces=tuple(SurfaceRegion.from_dict(item) for item in value.get("surfaces", ())),
            contact_laws=tuple(SurfaceContactLaw.from_dict(item) for item in value.get("contact_laws", ())),
            contact_pairs=tuple(SurfaceContactPair.from_dict(item) for item in value.get("contact_pairs", ())),
            surface_properties=tuple(SurfaceProperty.from_dict(item) for item in value.get("surface_properties", ())),
            materials=tuple(MechanicalMaterial.from_dict(item) for item in value.get("materials", ())),
            component_materials=dict(value.get("component_materials", {})),
            length_unit=units["length"],
            force_unit=units["force"],
            time_unit=units["time"],
            temperature_unit=units["temperature"],
            metadata=value.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, value: str) -> "ContactSimulationModel":
        data = json.loads(value)
        if not isinstance(data, Mapping):
            raise ValueError("contact simulation JSON root must be an object")
        return cls.from_dict(data)


@dataclass(frozen=True)
class ContactSimulationIssue:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class ContactSimulationValidationReport:
    valid: bool
    issues: tuple[ContactSimulationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ContactSimulationIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "error")

    @property
    def warnings(self) -> tuple[ContactSimulationIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "warning")

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ValueError("; ".join(f"{item.path}: {item.message}" for item in self.errors))

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [item.to_dict() for item in self.issues]}


@dataclass(frozen=True)
class ContactSimulationAnalysis:
    backend: str
    validation: ContactSimulationValidationReport
    resolved_surfaces: tuple[dict[str, Any], ...]
    pair_metrics: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "validation": self.validation.to_dict(),
            "resolved_surfaces": list(self.resolved_surfaces),
            "pair_metrics": list(self.pair_metrics),
        }


def _geometry_ref(value: Mapping[str, Any]) -> GeometryRef:
    return GeometryRef(
        kind=value["kind"], source_node_id=value.get("source_node_id"),
        geo_selector=dict(value["geo_selector"]), flip=bool(value.get("flip", False)),
    )


def geometry_ref_from_face(face: Any, *, flip: bool = False) -> GeometryRef:
    """Create a replayable geometric face reference from a public Face."""
    from ._engine.geometry.core import Face
    if not isinstance(face, Face):
        raise TypeError("face must be a CadFlow compatibility Face")
    from ._engine.geometry.operations import (
        _ensure_geo_selection_node_ids,
        _make_geo_selector,
        _selection_source_for_shape,
    )
    source = _selection_source_for_shape(face) or face
    node_ids = _ensure_geo_selection_node_ids(source, [face])
    return GeometryRef(
        kind="face",
        source_node_id=node_ids[0] if node_ids else None,
        geo_selector=_make_geo_selector(face, source_shape=source),
        flip=flip,
    )


def make_surface_region_rsurfaceregion(
    *, surface_id: str, component_id: str,
    faces: Sequence[Any] = (), geometry_refs: Sequence[GeometryRef] = (),
    role: SurfaceRole | str = SurfaceRole.CONTACT,
    property_id: str | None = None,
    flip: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> SurfaceRegion:
    refs = tuple(geometry_refs) + tuple(geometry_ref_from_face(face, flip=flip) for face in faces)
    return SurfaceRegion(surface_id, component_id, refs, role, property_id, _metadata(metadata))


def make_contact_simulation_model_rcontactsimulationmodel(
    assembly: Assembly | str, **kwargs: Any
) -> ContactSimulationModel:
    assembly_id = assembly.assembly_id if isinstance(assembly, Assembly) else assembly
    return ContactSimulationModel(assembly_id=assembly_id, **kwargs)


def _resolved_face(assembly: Assembly, region: SurfaceRegion, ref: GeometryRef) -> tuple[Any, Any, int]:
    component = assembly.get_component(region.component_id)
    if not isinstance(component.item, Part):
        raise ValueError("surface regions currently require a direct Part component")
    from ._engine.workflow.serializer import (
        _candidate_shapes_for_geo_selection,
        _geo_selector_score,
    )
    candidates = _candidate_shapes_for_geo_selection(component.item.body, "face")
    ranked = sorted(
        ((_geo_selector_score(face, ref.geo_selector, candidate_index=index), index, face) for index, face in enumerate(candidates)),
        key=lambda item: (item[0], item[1]),
    )
    if not ranked or ranked[0][0] > 1e-4:
        raise ValueError("geometry reference no longer matches a stable component face")
    if len(ranked) > 1 and ranked[1][0] <= 1e-4:
        raise ValueError("geometry reference ambiguously matches multiple component faces")
    return ranked[0][2], component.placement, int(ranked[0][1])


def validate_contact_simulation_model_rcontactsimulationvalidationreport(
    model: ContactSimulationModel, assembly: Assembly
) -> ContactSimulationValidationReport:
    if not isinstance(model, ContactSimulationModel):
        raise TypeError("model must be a ContactSimulationModel")
    if not isinstance(assembly, Assembly):
        raise TypeError("assembly must be an Assembly")
    issues: list[ContactSimulationIssue] = []
    def add(severity: str, code: str, path: str, message: str) -> None:
        issues.append(ContactSimulationIssue(severity, code, path, message))
    if model.assembly_id != assembly.assembly_id:
        add("error", "assembly_id_mismatch", "assembly_id", "model and assembly ids differ")
    component_ids = set(assembly.component_ids())
    properties = {item.property_id for item in model.surface_properties}
    materials = {item.material_id for item in model.materials}
    surfaces = {item.surface_id: item for item in model.surfaces}
    laws = {item.law_id for item in model.contact_laws}
    for region in model.surfaces:
        path = f"surfaces.{region.surface_id}"
        if region.component_id not in component_ids:
            add("error", "component_missing", path, f"component {region.component_id!r} does not exist")
            continue
        if region.property_id is not None and region.property_id not in properties:
            add("error", "surface_property_missing", path, f"surface property {region.property_id!r} does not exist")
        for index, ref in enumerate(region.geometry_refs):
            try:
                _resolved_face(assembly, region, ref)
            except Exception as error:
                add("error", "face_reference_unresolved", f"{path}.geometry_refs[{index}]", str(error))
    for pair in model.contact_pairs:
        path = f"contact_pairs.{pair.pair_id}"
        if pair.surface_a_id not in surfaces:
            add("error", "surface_missing", path, f"surface {pair.surface_a_id!r} does not exist")
        if pair.surface_b_id not in surfaces:
            add("error", "surface_missing", path, f"surface {pair.surface_b_id!r} does not exist")
        if pair.law_id not in laws:
            add("error", "contact_law_missing", path, f"contact law {pair.law_id!r} does not exist")
        if pair.search_tolerance == 0.0:
            add("warning", "search_tolerance_zero", path, "only exactly touching faces are initial contact candidates")
    for component_id, material_id in model.component_materials.items():
        if component_id not in component_ids:
            add("error", "material_component_missing", f"component_materials.{component_id}", "component does not exist")
        if material_id not in materials:
            add("error", "material_missing", f"component_materials.{component_id}", f"material {material_id!r} does not exist")
    for component_id in sorted({region.component_id for region in model.surfaces} - set(model.component_materials)):
        add("warning", "component_material_unassigned", f"component_materials.{component_id}", "contact component has no mechanical material assignment")
    return ContactSimulationValidationReport(not any(item.severity == "error" for item in issues), tuple(issues))


def _flip_face_metrics(value: dict[str, object], flip: bool) -> dict[str, object]:
    result = dict(value)
    if not flip:
        return result
    result["normal"] = tuple(-float(item) for item in result["normal"])  # type: ignore[arg-type]
    k_min = float(result["principal_curvature_min"])
    k_max = float(result["principal_curvature_max"])
    result["mean_curvature"] = -float(result["mean_curvature"])
    result["principal_curvature_min"] = -k_max
    result["principal_curvature_max"] = -k_min
    return result


def analyze_contact_simulation_model_rcontactsimulationanalysis(
    model: ContactSimulationModel, assembly: Assembly
) -> ContactSimulationAnalysis:
    validation = validate_contact_simulation_model_rcontactsimulationvalidationreport(model, assembly)
    validation.raise_for_errors()
    from ._surface_native import brep_bytes, measure_brep_face, measure_brep_pair, placement_transform
    resolved: dict[str, list[tuple[Any, Any, GeometryRef]]] = {}
    surface_payloads: list[dict[str, Any]] = []
    for region in model.surfaces:
        values: list[tuple[Any, Any, GeometryRef]] = []
        faces_payload: list[dict[str, Any]] = []
        for index, ref in enumerate(region.geometry_refs):
            face, placement, component_face_index = _resolved_face(assembly, region, ref)
            values.append((face, placement, ref))
            data = brep_bytes(face)
            faces_payload.append({
                "face_index": index,
                "component_face_index": component_face_index,
                "geometry_ref": ref.to_dict(),
                "brep_sha256": hashlib.sha256(data).hexdigest(),
                "local_brep_byte_length": len(data),
                "component_transform": list(placement_transform(placement)),
                "metrics": _flip_face_metrics(measure_brep_face(face, placement), ref.flip),
            })
        resolved[region.surface_id] = values
        surface_payloads.append({
            "surface_id": region.surface_id,
            "component_id": region.component_id,
            "role": region.role,
            "property_id": region.property_id,
            "faces": faces_payload,
        })

    pair_payloads: list[dict[str, Any]] = []
    for pair in model.contact_pairs:
        combinations: list[dict[str, Any]] = []
        candidate_count = 0
        for index_a, (face_a, placement_a, ref_a) in enumerate(resolved[pair.surface_a_id]):
            for index_b, (face_b, placement_b, ref_b) in enumerate(resolved[pair.surface_b_id]):
                metrics = measure_brep_pair(face_a, placement_a, face_b, placement_b)
                face_a_metrics = _flip_face_metrics(metrics["face_a"], ref_a.flip)  # type: ignore[arg-type]
                face_b_metrics = _flip_face_metrics(metrics["face_b"], ref_b.flip)  # type: ignore[arg-type]
                normal_a = face_a_metrics["normal"]
                normal_b = face_b_metrics["normal"]
                normal_dot = sum(float(normal_a[i]) * float(normal_b[i]) for i in range(3))  # type: ignore[index]
                closest_a = metrics["closest_a"]
                closest_b = metrics["closest_b"]
                signed_gap = sum(
                    (float(closest_b[i]) - float(closest_a[i])) * float(normal_a[i])  # type: ignore[index]
                    for i in range(3)
                )
                minimum_distance = float(metrics["minimum_distance"])
                solver_initial_gap = (
                    signed_gap + pair.initial_clearance - pair.interference
                )
                initial_overclosure = max(0.0, -solver_initial_gap)
                candidate = (
                    (
                        minimum_distance <= pair.search_tolerance + 1e-12
                        or initial_overclosure > 0.0
                    )
                    and -normal_dot >= pair.minimum_opposed_normal_cosine
                )
                candidate_count += int(candidate)
                combinations.append({
                    "face_a_index": index_a,
                    "face_b_index": index_b,
                    "minimum_distance": minimum_distance,
                    "normal_dot": normal_dot,
                    "signed_normal_gap": signed_gap,
                    "solver_initial_normal_gap": solver_initial_gap,
                    "initial_overclosure": initial_overclosure,
                    "tangential_offset": float(metrics["tangential_offset"]),
                    "closest_a": list(closest_a),
                    "closest_b": list(closest_b),
                    "initial_contact_candidate": candidate,
                })
        pair_payloads.append({
            "pair_id": pair.pair_id,
            "surface_a_id": pair.surface_a_id,
            "surface_b_id": pair.surface_b_id,
            "law_id": pair.law_id,
            "candidate_count": candidate_count,
            "face_pairs": combinations,
        })
    return ContactSimulationAnalysis("native_cpp_occt", validation, tuple(surface_payloads), tuple(pair_payloads))


def export_contact_simulation_json_rpath(
    model: ContactSimulationModel, path: str | Path, *, indent: int | None = 2
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(model.to_json(indent=indent) + "\n", encoding="utf-8")
    return output


def import_contact_simulation_json_rcontactsimulationmodel(path: str | Path) -> ContactSimulationModel:
    return ContactSimulationModel.from_json(Path(path).read_text(encoding="utf-8"))


def export_contact_simulation_package_rpath(
    model: ContactSimulationModel, assembly: Assembly, output_dir: str | Path
) -> Path:
    """Write a neutral manifest plus component-local BREP files for every face."""
    analysis = analyze_contact_simulation_model_rcontactsimulationanalysis(model, assembly)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    surface_dir = root / "surfaces"
    surface_dir.mkdir(parents=True, exist_ok=True)
    component_dir = root / "components"
    component_dir.mkdir(parents=True, exist_ok=True)
    from ._surface_native import brep_bytes, placement_transform
    component_payloads: list[dict[str, Any]] = []
    referenced_components = sorted({region.component_id for region in model.surfaces})
    for component_index, component_id in enumerate(referenced_components):
        component = assembly.get_component(component_id)
        if not isinstance(component.item, Part):
            raise ValueError("surface regions currently require a direct Part component")
        data = brep_bytes(component.item.body)
        relative = Path("components") / f"component-{component_index:06d}.brep"
        (root / relative).write_bytes(data)
        component_payloads.append({
            "component_id": component_id,
            "part_id": component.item.part_id,
            "material_id": model.component_materials.get(component_id),
            "brep_uri": relative.as_posix(),
            "brep_sha256": hashlib.sha256(data).hexdigest(),
            "brep_byte_length": len(data),
            "component_transform": list(placement_transform(component.placement)),
        })
    resolved_payloads = [dict(item) for item in analysis.resolved_surfaces]
    regions = {region.surface_id: region for region in model.surfaces}
    file_index = 0
    for surface_payload in resolved_payloads:
        surface_id = str(surface_payload["surface_id"])
        region = regions[surface_id]
        face_payloads = surface_payload["faces"]
        for index, (ref, face_payload) in enumerate(zip(region.geometry_refs, face_payloads)):
            face, _placement, _component_face_index = _resolved_face(assembly, region, ref)
            relative = Path("surfaces") / f"surface-{file_index:06d}.brep"
            file_index += 1
            data = brep_bytes(face)
            (root / relative).write_bytes(data)
            face_payload["brep_uri"] = relative.as_posix()
            face_payload["brep_sha256"] = hashlib.sha256(data).hexdigest()
            face_payload["face_index"] = index
    manifest = {
        "schema": "cadflow-contact-simulation-package",
        "schema_version": "1.0",
        "model": model.to_dict(),
        "analysis": {
            "backend": analysis.backend,
            "validation": analysis.validation.to_dict(),
            "components": component_payloads,
            "resolved_surfaces": resolved_payloads,
            "pair_metrics": list(analysis.pair_metrics),
        },
    }
    path = root / "simulation.json"
    path.write_text(json.dumps(manifest, allow_nan=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "ContactSimulationAnalysis", "ContactSimulationIssue", "ContactSimulationModel",
    "ContactSimulationValidationReport", "FrictionModel", "MechanicalMaterial",
    "NormalContactModel", "SlidingFormulation", "SurfaceContactLaw",
    "SurfaceContactPair", "SurfaceProperty", "SurfaceRegion", "SurfaceRole",
    "analyze_contact_simulation_model_rcontactsimulationanalysis",
    "export_contact_simulation_json_rpath", "export_contact_simulation_package_rpath",
    "geometry_ref_from_face", "import_contact_simulation_json_rcontactsimulationmodel",
    "make_contact_simulation_model_rcontactsimulationmodel", "make_surface_region_rsurfaceregion",
    "validate_contact_simulation_model_rcontactsimulationvalidationreport",
]
