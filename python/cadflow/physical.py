"""Physical connection semantics and reduced-order simulation interfaces.

This module deliberately sits beside the kinematic ``Assembly.constraints``
graph.  A kinematic constraint describes allowed motion; a physical connection
describes how an interface carries load, how it was made, and where it acts.
Keeping the two graphs separate lets existing assembly models remain valid.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Mapping, Optional, Sequence

from cadflow._engine.assembly.product import (
    Assembly,
    ConnectorRef,
    GeometryRef,
)


Vec3 = tuple[float, float, float]
_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")


class PhysicalConnectionKind(str, Enum):
    """Built-in manufacturing and interface connection categories."""

    MORTISE_TENON = "mortise_tenon"
    DOVETAIL = "dovetail"
    FINGER_JOINT = "finger_joint"
    DOWEL = "dowel"
    PIN = "pin"
    KEY = "key"
    SPLINE = "spline"
    BOLT = "bolt"
    SCREW = "screw"
    RIVET = "rivet"
    CLAMP = "clamp"
    WELD = "weld"
    SOLDER = "solder"
    ADHESIVE = "adhesive"
    POTTING = "potting"
    PRESS_FIT = "press_fit"
    SNAP_FIT = "snap_fit"
    BEARING = "bearing"
    CONTACT = "contact"
    CUSTOM = "custom"


class ConnectionResponseMode(str, Enum):
    """Reduced-order force law evaluated by the native batch kernel."""

    BONDED = "bonded"
    FRICTIONAL_CONTACT = "frictional_contact"
    FASTENER = "fastener"
    INTERFERENCE = "interference"
    COMPLIANT = "compliant"


class ConnectionRegionRole(str, Enum):
    """Physical purpose of a selected interface region."""

    CONTACT = "contact"
    BEARING = "bearing"
    ADHESIVE = "adhesive"
    WELD = "weld"
    FASTENER = "fastener"
    RETENTION = "retention"
    INSERTION = "insertion"
    CUSTOM = "custom"


def _identifier(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    if not _ID_PATTERN.fullmatch(result):
        raise ValueError(
            f"{field_name} must start with a letter and contain only letters, "
            "digits, underscore, dash, dot, or colon"
        )
    return result


def _finite(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{field_name} must be numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _non_negative(value: Any, *, field_name: str) -> float:
    result = _finite(value, field_name=field_name)
    if result < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _optional_positive(value: Any, *, field_name: str) -> Optional[float]:
    if value is None:
        return None
    result = _finite(value, field_name=field_name)
    if result <= 0.0:
        raise ValueError(f"{field_name} must be positive when provided")
    return result


def _vec3(value: Sequence[float], *, field_name: str) -> Vec3:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{field_name} must contain exactly three values")
    return tuple(
        _finite(component, field_name=f"{field_name}[{index}]")
        for index, component in enumerate(value)
    )  # type: ignore[return-value]


def _unit_vector(value: Sequence[float], *, field_name: str) -> Vec3:
    vector = _vec3(value, field_name=field_name)
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-12:
        raise ValueError(f"{field_name} must be a non-zero vector")
    return tuple(component / length for component in vector)  # type: ignore[return-value]


def _enum_value(value: Any, enum_type: type[Enum], *, field_name: str) -> str:
    raw = value.value if isinstance(value, enum_type) else value
    try:
        return str(enum_type(str(raw)).value)
    except ValueError as error:
        choices = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {choices}") from error


def _json_mapping(value: Optional[Mapping[str, Any]], *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    try:
        encoded = json.dumps(dict(value), allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain finite JSON values") from error
    return dict(json.loads(encoded))


def _name(value: Optional[str], *, field_name: str = "name") -> Optional[str]:
    if value is None:
        return None
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field_name} must not be empty when provided")
    return result


@dataclass(frozen=True)
class ConnectionBehavior:
    """Parameters for one reduced-order connection law.

    Length and force units come from the owning :class:`PhysicalConnectionLayer`.
    Translational stiffness therefore uses force/length, damping uses
    force*time/length, and rotational values use the corresponding moment units
    per radian.  Relative rotations supplied to the evaluator are radians.
    """

    response_mode: ConnectionResponseMode | str
    normal_stiffness: float = 0.0
    tangential_stiffness: float = 0.0
    rotational_stiffness: float = 0.0
    normal_damping: float = 0.0
    tangential_damping: float = 0.0
    rotational_damping: float = 0.0
    friction_coefficient: float = 0.0
    preload: float = 0.0
    clearance: float = 0.0
    interference: float = 0.0
    tensile_limit: Optional[float] = None
    shear_limit: Optional[float] = None
    torque_limit: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "response_mode",
            _enum_value(
                self.response_mode,
                ConnectionResponseMode,
                field_name="response_mode",
            ),
        )
        for field_name in (
            "normal_stiffness",
            "tangential_stiffness",
            "rotational_stiffness",
            "normal_damping",
            "tangential_damping",
            "rotational_damping",
            "friction_coefficient",
            "preload",
            "clearance",
            "interference",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative(getattr(self, field_name), field_name=field_name),
            )
        if self.clearance > 0.0 and self.interference > 0.0:
            raise ValueError("clearance and interference cannot both be positive")
        for field_name in ("tensile_limit", "shear_limit", "torque_limit"):
            object.__setattr__(
                self,
                field_name,
                _optional_positive(getattr(self, field_name), field_name=field_name),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_mode": self.response_mode,
            "normal_stiffness": self.normal_stiffness,
            "tangential_stiffness": self.tangential_stiffness,
            "rotational_stiffness": self.rotational_stiffness,
            "normal_damping": self.normal_damping,
            "tangential_damping": self.tangential_damping,
            "rotational_damping": self.rotational_damping,
            "friction_coefficient": self.friction_coefficient,
            "preload": self.preload,
            "clearance": self.clearance,
            "interference": self.interference,
            "tensile_limit": self.tensile_limit,
            "shear_limit": self.shear_limit,
            "torque_limit": self.torque_limit,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConnectionBehavior":
        if not isinstance(data, Mapping):
            raise TypeError("connection behavior must be an object")
        return cls(**dict(data))


@dataclass(frozen=True)
class ConnectionRegion:
    """Component-local BREP region participating in a physical connection."""

    region_id: str
    component_id: str
    geometry_ref: GeometryRef
    role: ConnectionRegionRole | str = ConnectionRegionRole.CONTACT
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _identifier(self.region_id, field_name="region_id"))
        object.__setattr__(
            self,
            "component_id",
            _identifier(self.component_id, field_name="component_id"),
        )
        if not isinstance(self.geometry_ref, GeometryRef):
            raise TypeError("geometry_ref must be a GeometryRef")
        object.__setattr__(
            self,
            "role",
            _enum_value(self.role, ConnectionRegionRole, field_name="role"),
        )
        object.__setattr__(
            self,
            "metadata",
            _json_mapping(self.metadata, field_name="metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "component_id": self.component_id,
            "geometry_ref": self.geometry_ref.to_dict(),
            "role": self.role,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConnectionRegion":
        if not isinstance(data, Mapping):
            raise TypeError("connection region must be an object")
        return cls(
            region_id=data["region_id"],
            component_id=data["component_id"],
            geometry_ref=_geometry_ref_from_dict(data["geometry_ref"]),
            role=data.get("role", ConnectionRegionRole.CONTACT.value),
            metadata=data.get("metadata", {}),
        )


_DEFAULT_RESPONSE_MODES = {
    PhysicalConnectionKind.BOLT.value: ConnectionResponseMode.FASTENER.value,
    PhysicalConnectionKind.SCREW.value: ConnectionResponseMode.FASTENER.value,
    PhysicalConnectionKind.RIVET.value: ConnectionResponseMode.FASTENER.value,
    PhysicalConnectionKind.CLAMP.value: ConnectionResponseMode.FASTENER.value,
    PhysicalConnectionKind.PRESS_FIT.value: ConnectionResponseMode.INTERFERENCE.value,
    PhysicalConnectionKind.CONTACT.value: ConnectionResponseMode.FRICTIONAL_CONTACT.value,
    PhysicalConnectionKind.BEARING.value: ConnectionResponseMode.FRICTIONAL_CONTACT.value,
    PhysicalConnectionKind.SNAP_FIT.value: ConnectionResponseMode.COMPLIANT.value,
}


@dataclass(frozen=True)
class PhysicalConnection:
    """Physical connection between two assembly component connector frames."""

    connection_id: str
    connection_kind: PhysicalConnectionKind | str
    connector_a: ConnectorRef
    connector_b: ConnectorRef
    behavior: ConnectionBehavior
    regions: tuple[ConnectionRegion, ...] = ()
    insertion_direction: Optional[Vec3] = None
    auxiliary_component_ids: tuple[str, ...] = ()
    kinematic_constraint_id: Optional[str] = None
    name: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_id",
            _identifier(self.connection_id, field_name="connection_id"),
        )
        object.__setattr__(
            self,
            "connection_kind",
            _enum_value(
                self.connection_kind,
                PhysicalConnectionKind,
                field_name="connection_kind",
            ),
        )
        if not isinstance(self.connector_a, ConnectorRef):
            raise TypeError("connector_a must be a ConnectorRef")
        if not isinstance(self.connector_b, ConnectorRef):
            raise TypeError("connector_b must be a ConnectorRef")
        if self.connector_a.component_id == self.connector_b.component_id:
            raise ValueError("a physical connection must join two different components")
        if not isinstance(self.behavior, ConnectionBehavior):
            raise TypeError("behavior must be a ConnectionBehavior")
        regions = tuple(self.regions or ())
        if any(not isinstance(region, ConnectionRegion) for region in regions):
            raise TypeError("regions must contain ConnectionRegion values")
        region_ids = [region.region_id for region in regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("region_id values must be unique within a connection")
        object.__setattr__(self, "regions", regions)
        if self.insertion_direction is not None:
            object.__setattr__(
                self,
                "insertion_direction",
                _unit_vector(self.insertion_direction, field_name="insertion_direction"),
            )
        auxiliary = tuple(
            _identifier(value, field_name="auxiliary_component_id")
            for value in (self.auxiliary_component_ids or ())
        )
        if len(auxiliary) != len(set(auxiliary)):
            raise ValueError("auxiliary_component_ids must be unique")
        if self.connector_a.component_id in auxiliary or self.connector_b.component_id in auxiliary:
            raise ValueError("auxiliary components must differ from the two primary components")
        object.__setattr__(self, "auxiliary_component_ids", auxiliary)
        if self.kinematic_constraint_id is not None:
            object.__setattr__(
                self,
                "kinematic_constraint_id",
                _identifier(
                    self.kinematic_constraint_id,
                    field_name="kinematic_constraint_id",
                ),
            )
        object.__setattr__(self, "name", _name(self.name))
        object.__setattr__(
            self,
            "metadata",
            _json_mapping(self.metadata, field_name="metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "connection_kind": self.connection_kind,
            "connector_a": self.connector_a.to_dict(),
            "connector_b": self.connector_b.to_dict(),
            "behavior": self.behavior.to_dict(),
            "regions": [region.to_dict() for region in self.regions],
            "insertion_direction": (
                list(self.insertion_direction)
                if self.insertion_direction is not None
                else None
            ),
            "auxiliary_component_ids": list(self.auxiliary_component_ids),
            "kinematic_constraint_id": self.kinematic_constraint_id,
            "name": self.name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicalConnection":
        if not isinstance(data, Mapping):
            raise TypeError("physical connection must be an object")
        return cls(
            connection_id=data["connection_id"],
            connection_kind=data["connection_kind"],
            connector_a=_connector_ref_from_dict(data["connector_a"]),
            connector_b=_connector_ref_from_dict(data["connector_b"]),
            behavior=ConnectionBehavior.from_dict(data["behavior"]),
            regions=tuple(
                ConnectionRegion.from_dict(region)
                for region in data.get("regions", ())
            ),
            insertion_direction=data.get("insertion_direction"),
            auxiliary_component_ids=tuple(data.get("auxiliary_component_ids", ())),
            kinematic_constraint_id=data.get("kinematic_constraint_id"),
            name=data.get("name"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class PhysicalConnectionLayer:
    """Immutable physical connection graph associated with one assembly."""

    SCHEMA_VERSION: ClassVar[str] = "1.0"

    assembly_id: str
    connections: tuple[PhysicalConnection, ...] = ()
    length_unit: str = "mm"
    force_unit: str = "N"
    time_unit: str = "s"
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "assembly_id", _identifier(self.assembly_id, field_name="assembly_id"))
        connections = tuple(self.connections or ())
        if any(not isinstance(item, PhysicalConnection) for item in connections):
            raise TypeError("connections must contain PhysicalConnection values")
        ids = [item.connection_id for item in connections]
        if len(ids) != len(set(ids)):
            raise ValueError("connection_id values must be unique within a layer")
        object.__setattr__(self, "connections", connections)
        for field_name in ("length_unit", "force_unit", "time_unit"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "metadata",
            _json_mapping(self.metadata, field_name="metadata"),
        )

    def connection_ids(self) -> tuple[str, ...]:
        return tuple(item.connection_id for item in self.connections)

    def get_connection(self, connection_id: str) -> PhysicalConnection:
        target = _identifier(connection_id, field_name="connection_id")
        for connection in self.connections:
            if connection.connection_id == target:
                return connection
        raise KeyError(f"physical connection layer has no connection_id '{target}'")

    def connections_for_component(self, component_id: str) -> tuple[PhysicalConnection, ...]:
        target = _identifier(component_id, field_name="component_id")
        return tuple(
            connection
            for connection in self.connections
            if target
            in {
                connection.connector_a.component_id,
                connection.connector_b.component_id,
                *connection.auxiliary_component_ids,
            }
        )

    def connections_between(
        self, component_a: str, component_b: str
    ) -> tuple[PhysicalConnection, ...]:
        pair = {
            _identifier(component_a, field_name="component_a"),
            _identifier(component_b, field_name="component_b"),
        }
        if len(pair) != 2:
            raise ValueError("component_a and component_b must differ")
        return tuple(
            connection
            for connection in self.connections
            if {
                connection.connector_a.component_id,
                connection.connector_b.component_id,
            }
            == pair
        )

    def with_connection(self, connection: PhysicalConnection) -> "PhysicalConnectionLayer":
        if not isinstance(connection, PhysicalConnection):
            raise TypeError("connection must be a PhysicalConnection")
        if connection.connection_id in self.connection_ids():
            raise ValueError(f"duplicate connection_id in layer: {connection.connection_id}")
        return PhysicalConnectionLayer(
            self.assembly_id,
            (*self.connections, connection),
            length_unit=self.length_unit,
            force_unit=self.force_unit,
            time_unit=self.time_unit,
            metadata=self.metadata,
        )

    def without_connection(self, connection_id: str) -> "PhysicalConnectionLayer":
        target = _identifier(connection_id, field_name="connection_id")
        self.get_connection(target)
        return PhysicalConnectionLayer(
            self.assembly_id,
            tuple(item for item in self.connections if item.connection_id != target),
            length_unit=self.length_unit,
            force_unit=self.force_unit,
            time_unit=self.time_unit,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "assembly_id": self.assembly_id,
            "units": {
                "length": self.length_unit,
                "force": self.force_unit,
                "time": self.time_unit,
                "rotation": "rad",
            },
            "connections": [item.to_dict() for item in self.connections],
            "metadata": dict(self.metadata),
        }

    def to_json(self, *, indent: Optional[int] = None) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicalConnectionLayer":
        if not isinstance(data, Mapping):
            raise TypeError("physical connection layer must be an object")
        version = data.get("schema_version")
        if version != cls.SCHEMA_VERSION:
            raise ValueError(
                f"unsupported physical connection schema_version {version!r}; "
                f"expected {cls.SCHEMA_VERSION!r}"
            )
        units = data.get("units")
        if not isinstance(units, Mapping):
            raise TypeError("physical connection units must be an object")
        if units.get("rotation") != "rad":
            raise ValueError("physical connection rotation unit must be 'rad'")
        return cls(
            assembly_id=data["assembly_id"],
            connections=tuple(
                PhysicalConnection.from_dict(item)
                for item in data.get("connections", ())
            ),
            length_unit=units["length"],
            force_unit=units["force"],
            time_unit=units["time"],
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "PhysicalConnectionLayer":
        try:
            data = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid physical connection JSON") from error
        return cls.from_dict(data)


@dataclass(frozen=True)
class PhysicalConnectionValidationIssue:
    severity: str
    code: str
    connection_id: Optional[str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "connection_id": self.connection_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class PhysicalConnectionValidationReport:
    valid: bool
    issues: tuple[PhysicalConnectionValidationIssue, ...]

    @property
    def errors(self) -> tuple[PhysicalConnectionValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[PhysicalConnectionValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ValueError("; ".join(issue.message for issue in self.errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PhysicalConnectionState:
    """Relative B-to-A connector state expressed in connector A's local frame."""

    connection_id: str
    relative_translation: Vec3 = (0.0, 0.0, 0.0)
    relative_rotation: Vec3 = (0.0, 0.0, 0.0)
    relative_linear_velocity: Vec3 = (0.0, 0.0, 0.0)
    relative_angular_velocity: Vec3 = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_id",
            _identifier(self.connection_id, field_name="connection_id"),
        )
        for field_name in (
            "relative_translation",
            "relative_rotation",
            "relative_linear_velocity",
            "relative_angular_velocity",
        ):
            object.__setattr__(
                self,
                field_name,
                _vec3(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True)
class PhysicalConnectionResponse:
    """Wrench on component B, expressed in connector A's local frame."""

    connection_id: str
    force: Vec3
    torque: Vec3
    normal_force: float
    shear_force: float
    tensile_utilization: float
    shear_utilization: float
    torque_utilization: float
    active: bool
    failed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "force": list(self.force),
            "torque": list(self.torque),
            "normal_force": self.normal_force,
            "shear_force": self.shear_force,
            "tensile_utilization": self.tensile_utilization,
            "shear_utilization": self.shear_utilization,
            "torque_utilization": self.torque_utilization,
            "active": self.active,
            "failed": self.failed,
        }


@dataclass(frozen=True)
class PhysicalConnectionResponseBatch:
    backend: str
    responses: tuple[PhysicalConnectionResponse, ...]
    length_unit: str
    force_unit: str
    time_unit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "units": {
                "length": self.length_unit,
                "force": self.force_unit,
                "time": self.time_unit,
                "rotation": "rad",
            },
            "responses": [response.to_dict() for response in self.responses],
        }


def make_connection_behavior_rconnectionbehavior(
    *,
    response_mode: ConnectionResponseMode | str,
    normal_stiffness: float = 0.0,
    tangential_stiffness: float = 0.0,
    rotational_stiffness: float = 0.0,
    normal_damping: float = 0.0,
    tangential_damping: float = 0.0,
    rotational_damping: float = 0.0,
    friction_coefficient: float = 0.0,
    preload: float = 0.0,
    clearance: float = 0.0,
    interference: float = 0.0,
    tensile_limit: Optional[float] = None,
    shear_limit: Optional[float] = None,
    torque_limit: Optional[float] = None,
) -> ConnectionBehavior:
    return ConnectionBehavior(
        response_mode=response_mode,
        normal_stiffness=normal_stiffness,
        tangential_stiffness=tangential_stiffness,
        rotational_stiffness=rotational_stiffness,
        normal_damping=normal_damping,
        tangential_damping=tangential_damping,
        rotational_damping=rotational_damping,
        friction_coefficient=friction_coefficient,
        preload=preload,
        clearance=clearance,
        interference=interference,
        tensile_limit=tensile_limit,
        shear_limit=shear_limit,
        torque_limit=torque_limit,
    )


def make_connection_region_rconnectionregion(
    *,
    region_id: str,
    component_id: str,
    geometry_ref: GeometryRef,
    role: ConnectionRegionRole | str = ConnectionRegionRole.CONTACT,
    metadata: Optional[Mapping[str, Any]] = None,
) -> ConnectionRegion:
    return ConnectionRegion(
        region_id=region_id,
        component_id=component_id,
        geometry_ref=geometry_ref,
        role=role,
        metadata=dict(metadata or {}),
    )


def make_physical_connection_rphysicalconnection(
    *,
    connection_id: str,
    connection_kind: PhysicalConnectionKind | str,
    connector_a: ConnectorRef,
    connector_b: ConnectorRef,
    behavior: Optional[ConnectionBehavior] = None,
    regions: Sequence[ConnectionRegion] = (),
    insertion_direction: Optional[Sequence[float]] = None,
    auxiliary_component_ids: Sequence[str] = (),
    kinematic_constraint_id: Optional[str] = None,
    name: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> PhysicalConnection:
    resolved_kind = _enum_value(
        connection_kind,
        PhysicalConnectionKind,
        field_name="connection_kind",
    )
    resolved_behavior = behavior or ConnectionBehavior(
        _DEFAULT_RESPONSE_MODES.get(
            resolved_kind,
            ConnectionResponseMode.BONDED.value,
        )
    )
    return PhysicalConnection(
        connection_id=connection_id,
        connection_kind=resolved_kind,
        connector_a=connector_a,
        connector_b=connector_b,
        behavior=resolved_behavior,
        regions=tuple(regions),
        insertion_direction=(
            tuple(insertion_direction) if insertion_direction is not None else None
        ),
        auxiliary_component_ids=tuple(auxiliary_component_ids),
        kinematic_constraint_id=kinematic_constraint_id,
        name=name,
        metadata=dict(metadata or {}),
    )


def make_physical_connection_layer_rphysicalconnectionlayer(
    assembly: Assembly | str,
    *,
    length_unit: str = "mm",
    force_unit: str = "N",
    time_unit: str = "s",
    metadata: Optional[Mapping[str, Any]] = None,
) -> PhysicalConnectionLayer:
    if isinstance(assembly, Assembly):
        assembly_id = assembly.assembly_id
    else:
        assembly_id = assembly
    return PhysicalConnectionLayer(
        assembly_id=assembly_id,
        length_unit=length_unit,
        force_unit=force_unit,
        time_unit=time_unit,
        metadata=dict(metadata or {}),
    )


def add_physical_connection_rphysicalconnectionlayer(
    layer: PhysicalConnectionLayer,
    connection: PhysicalConnection,
) -> PhysicalConnectionLayer:
    if not isinstance(layer, PhysicalConnectionLayer):
        raise TypeError("layer must be a PhysicalConnectionLayer")
    return layer.with_connection(connection)


def remove_physical_connection_rphysicalconnectionlayer(
    layer: PhysicalConnectionLayer,
    connection_id: str,
) -> PhysicalConnectionLayer:
    if not isinstance(layer, PhysicalConnectionLayer):
        raise TypeError("layer must be a PhysicalConnectionLayer")
    return layer.without_connection(connection_id)


def validate_physical_connection_layer_rphysicalconnectionvalidationreport(
    layer: PhysicalConnectionLayer,
    assembly: Assembly,
) -> PhysicalConnectionValidationReport:
    if not isinstance(layer, PhysicalConnectionLayer):
        raise TypeError("layer must be a PhysicalConnectionLayer")
    if not isinstance(assembly, Assembly):
        raise TypeError("assembly must be an Assembly")
    issues: list[PhysicalConnectionValidationIssue] = []

    def add(severity: str, code: str, connection_id: Optional[str], message: str) -> None:
        issues.append(PhysicalConnectionValidationIssue(severity, code, connection_id, message))

    if layer.assembly_id != assembly.assembly_id:
        add(
            "error",
            "assembly_id_mismatch",
            None,
            f"layer assembly_id '{layer.assembly_id}' does not match assembly '{assembly.assembly_id}'",
        )

    component_ids = set(assembly.component_ids())
    for connection in layer.connections:
        connection_id = connection.connection_id
        for side_name, connector_ref in (
            ("connector_a", connection.connector_a),
            ("connector_b", connection.connector_b),
        ):
            if connector_ref.component_id not in component_ids:
                add(
                    "error",
                    "component_missing",
                    connection_id,
                    f"{side_name} references missing component '{connector_ref.component_id}'",
                )
                continue
            component = assembly.get_component(connector_ref.component_id)
            connector_ids = set(component.item.connector_ids())
            if connector_ref.connector_id not in connector_ids:
                add(
                    "error",
                    "connector_missing",
                    connection_id,
                    f"{side_name} references missing connector '{connector_ref.connector_id}' "
                    f"on component '{connector_ref.component_id}'",
                )

        allowed_region_components = {
            connection.connector_a.component_id,
            connection.connector_b.component_id,
            *connection.auxiliary_component_ids,
        }
        for auxiliary_id in connection.auxiliary_component_ids:
            if auxiliary_id not in component_ids:
                add(
                    "error",
                    "auxiliary_component_missing",
                    connection_id,
                    f"auxiliary component '{auxiliary_id}' does not exist in the assembly",
                )
        for region in connection.regions:
            if region.component_id not in component_ids:
                add(
                    "error",
                    "region_component_missing",
                    connection_id,
                    f"region '{region.region_id}' references missing component '{region.component_id}'",
                )
            elif region.component_id not in allowed_region_components:
                add(
                    "error",
                    "region_component_unrelated",
                    connection_id,
                    f"region '{region.region_id}' is not owned by a participant component",
                )

        if connection.kinematic_constraint_id is not None:
            try:
                constraint = assembly.get_constraint(connection.kinematic_constraint_id)
            except KeyError:
                add(
                    "error",
                    "kinematic_constraint_missing",
                    connection_id,
                    f"kinematic constraint '{connection.kinematic_constraint_id}' does not exist",
                )
            else:
                physical_pair = {
                    connection.connector_a.component_id,
                    connection.connector_b.component_id,
                }
                constraint_pair = {
                    constraint.connector_a.component_id,
                    constraint.connector_b.component_id,
                }
                if physical_pair != constraint_pair:
                    add(
                        "error",
                        "kinematic_constraint_pair_mismatch",
                        connection_id,
                        "kinematic constraint connects a different component pair",
                    )

        behavior = connection.behavior
        if (
            behavior.normal_stiffness == 0.0
            and behavior.tangential_stiffness == 0.0
            and behavior.rotational_stiffness == 0.0
        ):
            add(
                "warning",
                "response_not_parameterized",
                connection_id,
                "connection has no non-zero stiffness and will produce no elastic response",
            )
        if connection.connection_kind == PhysicalConnectionKind.PRESS_FIT.value:
            if behavior.response_mode != ConnectionResponseMode.INTERFERENCE.value:
                add(
                    "warning",
                    "press_fit_mode",
                    connection_id,
                    "press-fit connection normally uses the interference response mode",
                )
            if behavior.interference <= 0.0:
                add(
                    "warning",
                    "press_fit_interference_missing",
                    connection_id,
                    "press-fit connection has no positive interference",
                )
        if behavior.response_mode in {
            ConnectionResponseMode.FRICTIONAL_CONTACT.value,
            ConnectionResponseMode.INTERFERENCE.value,
        } and behavior.normal_stiffness <= 0.0:
            add(
                "warning",
                "contact_stiffness_missing",
                connection_id,
                "contact response requires positive normal_stiffness to carry contact load",
            )
        if connection.connection_kind in {
            PhysicalConnectionKind.MORTISE_TENON.value,
            PhysicalConnectionKind.DOVETAIL.value,
            PhysicalConnectionKind.PRESS_FIT.value,
            PhysicalConnectionKind.SNAP_FIT.value,
        } and connection.insertion_direction is None:
            add(
                "warning",
                "insertion_direction_missing",
                connection_id,
                "connection kind normally requires an insertion direction for assembly planning",
            )

    return PhysicalConnectionValidationReport(
        valid=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
    )


def evaluate_physical_connections_rphysicalconnectionresponsebatch(
    layer: PhysicalConnectionLayer,
    states: Sequence[PhysicalConnectionState],
) -> PhysicalConnectionResponseBatch:
    """Evaluate a batch of reduced-order connection states in native C++.

    Each state is expressed in connector A's local frame.  The resulting wrench
    acts on component B in that same frame; component A receives the opposite
    wrench.  This is a connection constitutive model, not a time integrator or
    finite-element solver.
    """

    if not isinstance(layer, PhysicalConnectionLayer):
        raise TypeError("layer must be a PhysicalConnectionLayer")
    state_values = tuple(states)
    if any(not isinstance(state, PhysicalConnectionState) for state in state_values):
        raise TypeError("states must contain PhysicalConnectionState values")
    state_ids = [state.connection_id for state in state_values]
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("states must contain at most one entry per connection_id")
    connections = tuple(layer.get_connection(state.connection_id) for state in state_values)
    if not state_values:
        return PhysicalConnectionResponseBatch(
            backend="native_cpp",
            responses=(),
            length_unit=layer.length_unit,
            force_unit=layer.force_unit,
            time_unit=layer.time_unit,
        )

    from cadflow._physical_native import evaluate_connection_responses

    native_results = evaluate_connection_responses(connections, state_values)
    responses = tuple(
        PhysicalConnectionResponse(
            connection_id=state.connection_id,
            force=result.force,
            torque=result.torque,
            normal_force=result.normal_force,
            shear_force=result.shear_force,
            tensile_utilization=result.tensile_utilization,
            shear_utilization=result.shear_utilization,
            torque_utilization=result.torque_utilization,
            active=result.active,
            failed=result.failed,
        )
        for state, result in zip(state_values, native_results)
    )
    return PhysicalConnectionResponseBatch(
        backend="native_cpp",
        responses=responses,
        length_unit=layer.length_unit,
        force_unit=layer.force_unit,
        time_unit=layer.time_unit,
    )


def export_physical_connection_layer_json_rpath(
    layer: PhysicalConnectionLayer,
    path: str | Path,
    *,
    indent: Optional[int] = 2,
) -> Path:
    if not isinstance(layer, PhysicalConnectionLayer):
        raise TypeError("layer must be a PhysicalConnectionLayer")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(layer.to_json(indent=indent) + "\n", encoding="utf-8")
    return output


def import_physical_connection_layer_json_rphysicalconnectionlayer(
    path: str | Path,
) -> PhysicalConnectionLayer:
    return PhysicalConnectionLayer.from_json(Path(path).read_text(encoding="utf-8"))


def _connector_ref_from_dict(data: Any) -> ConnectorRef:
    if not isinstance(data, Mapping):
        raise TypeError("connector reference must be an object")
    return ConnectorRef(data["component_id"], data["connector_id"])


def _geometry_ref_from_dict(data: Any) -> GeometryRef:
    if not isinstance(data, Mapping):
        raise TypeError("geometry reference must be an object")
    return GeometryRef(
        kind=data["kind"],
        source_node_id=data.get("source_node_id"),
        geo_selector=dict(data["geo_selector"]),
        flip=bool(data.get("flip", False)),
    )


__all__ = [
    "ConnectionBehavior",
    "ConnectionRegion",
    "ConnectionRegionRole",
    "ConnectionResponseMode",
    "PhysicalConnection",
    "PhysicalConnectionKind",
    "PhysicalConnectionLayer",
    "PhysicalConnectionResponse",
    "PhysicalConnectionResponseBatch",
    "PhysicalConnectionState",
    "PhysicalConnectionValidationIssue",
    "PhysicalConnectionValidationReport",
    "add_physical_connection_rphysicalconnectionlayer",
    "evaluate_physical_connections_rphysicalconnectionresponsebatch",
    "export_physical_connection_layer_json_rpath",
    "import_physical_connection_layer_json_rphysicalconnectionlayer",
    "make_connection_behavior_rconnectionbehavior",
    "make_connection_region_rconnectionregion",
    "make_physical_connection_layer_rphysicalconnectionlayer",
    "make_physical_connection_rphysicalconnection",
    "remove_physical_connection_rphysicalconnectionlayer",
    "validate_physical_connection_layer_rphysicalconnectionvalidationreport",
]
