"""ctypes bridge for the stateless native physical-connection batch kernel."""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from .native import NativeError, _load_library

if TYPE_CHECKING:
    from .physical import PhysicalConnection, PhysicalConnectionState


class _ConnectionParameters(C.Structure):
    _fields_ = [
        ("response_mode", C.c_int),
        ("axis", C.c_double * 3),
        ("normal_stiffness", C.c_double),
        ("tangential_stiffness", C.c_double),
        ("rotational_stiffness", C.c_double),
        ("normal_damping", C.c_double),
        ("tangential_damping", C.c_double),
        ("rotational_damping", C.c_double),
        ("friction_coefficient", C.c_double),
        ("preload", C.c_double),
        ("clearance", C.c_double),
        ("interference", C.c_double),
        ("tensile_limit", C.c_double),
        ("shear_limit", C.c_double),
        ("torque_limit", C.c_double),
    ]


class _ConnectionState(C.Structure):
    _fields_ = [
        ("relative_translation", C.c_double * 3),
        ("relative_rotation", C.c_double * 3),
        ("relative_linear_velocity", C.c_double * 3),
        ("relative_angular_velocity", C.c_double * 3),
    ]


class _ConnectionResponse(C.Structure):
    _fields_ = [
        ("force", C.c_double * 3),
        ("torque", C.c_double * 3),
        ("normal_force", C.c_double),
        ("shear_force", C.c_double),
        ("tensile_utilization", C.c_double),
        ("shear_utilization", C.c_double),
        ("torque_utilization", C.c_double),
        ("active", C.c_int),
        ("failed", C.c_int),
    ]


_MODE_CODES = {
    "bonded": 0,
    "frictional_contact": 1,
    "fastener": 2,
    "interference": 3,
    "compliant": 4,
}


@dataclass(frozen=True)
class NativeConnectionResponse:
    force: tuple[float, float, float]
    torque: tuple[float, float, float]
    normal_force: float
    shear_force: float
    tensile_utilization: float
    shear_utilization: float
    torque_utilization: float
    active: bool
    failed: bool


def _configure(lib: C.CDLL) -> None:
    try:
        function = lib.cadflow_evaluate_physical_connections
    except AttributeError as error:
        raise NativeError(
            "cadflow native library does not provide the physical connection kernel; "
            "rebuild and reinstall CadFlow"
        ) from error
    function.argtypes = [
        C.POINTER(_ConnectionParameters),
        C.POINTER(_ConnectionState),
        C.c_size_t,
        C.POINTER(_ConnectionResponse),
    ]
    function.restype = C.c_int
    lib.cadflow_last_error.restype = C.c_char_p


def _parameters(connection: "PhysicalConnection") -> _ConnectionParameters:
    behavior = connection.behavior
    result = _ConnectionParameters()
    result.response_mode = _MODE_CODES[str(behavior.response_mode)]
    axis = connection.insertion_direction or (0.0, 0.0, 1.0)
    result.axis[:] = axis
    result.normal_stiffness = behavior.normal_stiffness
    result.tangential_stiffness = behavior.tangential_stiffness
    result.rotational_stiffness = behavior.rotational_stiffness
    result.normal_damping = behavior.normal_damping
    result.tangential_damping = behavior.tangential_damping
    result.rotational_damping = behavior.rotational_damping
    result.friction_coefficient = behavior.friction_coefficient
    result.preload = behavior.preload
    result.clearance = behavior.clearance
    result.interference = behavior.interference
    result.tensile_limit = behavior.tensile_limit or 0.0
    result.shear_limit = behavior.shear_limit or 0.0
    result.torque_limit = behavior.torque_limit or 0.0
    return result


def _state(state: "PhysicalConnectionState") -> _ConnectionState:
    result = _ConnectionState()
    result.relative_translation[:] = state.relative_translation
    result.relative_rotation[:] = state.relative_rotation
    result.relative_linear_velocity[:] = state.relative_linear_velocity
    result.relative_angular_velocity[:] = state.relative_angular_velocity
    return result


def _error(lib: C.CDLL) -> str:
    value = lib.cadflow_last_error()
    return value.decode("utf-8", "replace") if value else "native physical connection evaluation failed"


def evaluate_connection_responses(
    connections: Sequence["PhysicalConnection"],
    states: Sequence["PhysicalConnectionState"],
) -> tuple[NativeConnectionResponse, ...]:
    if len(connections) != len(states):
        raise ValueError("connections and states must have the same length")
    if not connections:
        return ()
    lib = _load_library()
    _configure(lib)
    count = len(connections)
    parameters = (_ConnectionParameters * count)(
        *(_parameters(connection) for connection in connections)
    )
    state_values = (_ConnectionState * count)(*(_state(state) for state in states))
    response_values = (_ConnectionResponse * count)()
    ok = lib.cadflow_evaluate_physical_connections(
        parameters,
        state_values,
        count,
        response_values,
    )
    if not ok:
        raise NativeError(_error(lib))
    return tuple(
        NativeConnectionResponse(
            force=tuple(float(value) for value in response.force),
            torque=tuple(float(value) for value in response.torque),
            normal_force=float(response.normal_force),
            shear_force=float(response.shear_force),
            tensile_utilization=float(response.tensile_utilization),
            shear_utilization=float(response.shear_utilization),
            torque_utilization=float(response.torque_utilization),
            active=bool(response.active),
            failed=bool(response.failed),
        )
        for response in response_values
    )


__all__ = ["NativeConnectionResponse", "evaluate_connection_responses"]
