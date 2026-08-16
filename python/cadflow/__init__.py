"""CadFlow: a compact Python frontend over a session-oriented C++ core."""

from .frontend import Model, Shape, legacy_api, native_model
from .graph import Graph, Node
from .backend import CompatibilityBackend, NativeBackend, Router, capabilities
from . import (
    assembly,
    compat,
    expressions,
    graph_api,
    inspection,
    modeling,
    physical,
    query,
    scene,
    serialization,
    sketch,
    stdlib,
    surfaces,
    tolerances,
    topology,
    translators,
)
from .legacy import api as legacy_api_module
from .native import NativeError, NativeSession, ShapeHandle
from . import flexible
from .feedback import Diagnostic, OperationReport, OperationResult
from .frame import CoordinateFrame, Workplane, current_frame, use_frame
from .physical import *
from .physical import __all__ as _physical_all
from .preview import PreviewMeshBuffer, parse_preview_mesh_buffer, preview_mesh_buffer_to_glb
from .sketch_api import SketchDocument
from ._compat_aliases import install as _install_compat_aliases

_install_compat_aliases(globals())

# Importing the native graph implementation registers it on the package. Keep
# the module private while exposing its stable Graph and Node types above.
globals().pop("graph", None)


def __getattr__(name: str):
    """Keep every old top-level operation available during migration."""
    return getattr(legacy_api_module(), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(legacy_api_module())))

__all__ = [
    "Graph",
    "CompatibilityBackend",
    "Model",
    "NativeError",
    "NativeBackend",
    "NativeSession",
    "Node",
    "Shape",
    "ShapeHandle",
    "CoordinateFrame",
    "Diagnostic",
    "OperationReport",
    "OperationResult",
    "SketchDocument",
    "Workplane",
    "PreviewMeshBuffer",
    "parse_preview_mesh_buffer",
    "preview_mesh_buffer_to_glb",
    "Router",
    "assembly",
    "flexible",
    "compat",
    "capabilities",
    "expressions",
    "graph_api",
    "inspection",
    "legacy_api",
    "legacy_api_module",
    "modeling",
    "native_model",
    "physical",
    "query",
    "scene",
    "serialization",
    "sketch",
    "stdlib",
    "surfaces",
    "tolerances",
    "topology",
    "translators",
    "current_frame",
    "use_frame",
    "verifier",
]

# Keep ``from cadflow import *`` complete for the migrated API as well as the
# new frontend. The engine is bundled, so this does not pull in another tree.
__all__ = sorted(set(__all__) | set(_physical_all) | set(legacy_api_module().__all__))

__version__ = "0.1.0"
