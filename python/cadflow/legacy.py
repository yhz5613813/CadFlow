"""Access to CadFlow's complete compatibility API."""

from __future__ import annotations

import importlib
from types import ModuleType

from ._layout import engine_module_name


def api() -> ModuleType:
    """Return the complete compatibility API bundled with CadFlow."""
    return importlib.import_module(engine_module_name())


def module(name: str) -> ModuleType:
    """Return a compatibility submodule by its public module path."""
    return importlib.import_module(engine_module_name(name))
