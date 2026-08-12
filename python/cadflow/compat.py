"""Lazy compatibility facade for applications migrating from the old API."""

from __future__ import annotations

from typing import Any

from .legacy import api, module


def __getattr__(name: str) -> Any:
    return getattr(api(), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(api())))


def submodule(name: str) -> Any:
    """Return a legacy submodule, for example ``submodule('translator')``."""
    return module(name)
