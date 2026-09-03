"""Backend protocol and type-aware dispatcher."""

from __future__ import annotations

from typing import Any, Protocol

from .legacy import api as legacy_api
from .native import NativeSession, ShapeHandle


class Backend(Protocol):
    def supports(self, operation: str) -> bool: ...
    def call(self, operation: str, *args: Any, **kwargs: Any) -> Any: ...


class NativeBackend:
    """Dispatches handle-based operations to one explicit native session."""

    operations = frozenset({
        "box", "cylinder", "sphere", "cone", "polyline", "circle_profile",
        "arc", "interpolate",
        "helix",
        "import_step", "face", "bezier_surface", "fit_surface", "extrude",
        "revolve", "fillet", "chamfer", "shell", "loft", "sweep", "cut", "union",
        "intersect",
        "translate", "rotate", "mirror", "scale", "volume", "area", "bbox",
        "topology", "kind", "length", "distance", "center_of_mass", "mesh", "export_step",
        "export_stl", "export_dxf",
    })

    def __init__(self, session: NativeSession | None = None) -> None:
        self.session = session or NativeSession()
        self._owns_session = session is None

    def supports(self, operation: str) -> bool:
        return operation in self.operations

    def call(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        if not self.supports(operation):
            raise NotImplementedError(operation)
        return getattr(self.session, operation)(*args, **kwargs)

    def close(self) -> None:
        if self._owns_session:
            self.session.close()


class CompatibilityBackend:
    """Complete OCC implementation used for operations not migrated yet."""

    def supports(self, operation: str) -> bool:
        return hasattr(legacy_api(), operation)

    def call(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        try:
            target = getattr(legacy_api(), operation)
        except AttributeError as error:
            raise NotImplementedError(operation) from error
        return target(*args, **kwargs)


class Router:
    """Routes native handles to C++ and keeps the complete fallback surface."""

    def __init__(self, native: NativeBackend | None = None, fallback: Backend | None = None) -> None:
        self.native = native or NativeBackend()
        self.fallback = fallback or CompatibilityBackend()

    def call(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        native_request = operation in {
            "box", "cylinder", "sphere", "cone", "polyline", "circle_profile",
            "arc", "interpolate",
            "helix",
            "import_step",
            "bezier_surface", "fit_surface",
        } or _contains_native_handle((args, kwargs))
        if native_request and self.native.supports(operation):
            return self.native.call(operation, *args, **kwargs)
        return self.fallback.call(operation, *args, **kwargs)

    def close(self) -> None:
        self.native.close()


def capabilities() -> dict[str, object]:
    old = legacy_api()
    with NativeSession() as session:
        version = session.version
    return {
        "native": sorted(NativeBackend.operations),
        "compatibility": sorted(old.__all__),
        "native_version": version,
    }


def _contains_native_handle(value: Any) -> bool:
    if isinstance(value, ShapeHandle):
        return True
    if isinstance(value, dict):
        return any(_contains_native_handle(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_native_handle(item) for item in value)
    return False
