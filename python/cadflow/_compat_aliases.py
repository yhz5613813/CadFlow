"""Install import aliases for the migrated high-level API surface.

The aliases keep module-qualified imports working while the public package is
organized around frontend domains and a native backend. Every target remains
inside the installed CadFlow distribution.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from types import ModuleType
from typing import MutableMapping

from ._layout import engine_module_name


_MODULES = (
    "_mesh",
    "autotag",
    "auto_tools",
    "core",
    "errors",
    "evolve",
    "expr",
    "inspect",
    "kernel",
    "math",
    "operations",
    "product",
    "ql",
    "scene",
    "serializer",
    "sketch_solver",
    "source_mapping",
    "std",
    "tagging",
    "tolerance",
    "topology",
    "tracking",
    "translator",
    "units",
    "verifier",
)

_INTERNAL_TOP_LEVEL_MODULES = {
    "autotag",
    "graph",
    "serializer",
    "tracking",
}


def install(namespace: MutableMapping[str, object]) -> None:
    for name in _MODULES:
        target_name = engine_module_name(name)
        target = importlib.import_module(target_name)
        sys.modules.setdefault(f"cadflow.{name}", target)
        if name not in _INTERNAL_TOP_LEVEL_MODULES:
            namespace.setdefault(name, target)
        if not hasattr(target, "__path__"):
            continue
        prefix = target_name + "."
        for info in pkgutil.walk_packages(target.__path__, prefix):
            try:
                child = importlib.import_module(info.name)
            except ImportError:
                # Optional backend modules remain lazy and can be imported when
                # their dependencies are installed.
                continue
            suffix = info.name.removeprefix(prefix)
            alias = f"cadflow.{name}.{suffix}"
            sys.modules.setdefault(alias, child)
