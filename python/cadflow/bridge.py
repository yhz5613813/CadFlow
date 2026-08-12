"""One generic bridge used by the compatibility domain modules."""

from __future__ import annotations

from typing import Any, MutableMapping

from .legacy import module


def attr(domain: str, name: str) -> Any:
    return getattr(module(domain), name)


def names(domain: str) -> list[str]:
    return sorted(set(dir(module(domain))))


def install(domain: str, namespace: MutableMapping[str, Any]) -> None:
    namespace["__getattr__"] = lambda name: attr(domain, name)
    namespace["__dir__"] = lambda: sorted(set(namespace) | set(names(domain)))
