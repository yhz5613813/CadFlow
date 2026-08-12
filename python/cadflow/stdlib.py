"""Standard-part domain facade."""

from __future__ import annotations

from typing import Any

from .bridge import attr, names


def __getattr__(name: str) -> Any:
    # Standard parts are split into several legacy modules; resolve lazily.
    for domain in ("std.gear", "std.bearing", "std.fastener", "std.chain"):
        try:
            return attr(domain, name)
        except AttributeError:
            continue
    raise AttributeError(name)


def __dir__() -> list[str]:
    result = set(globals())
    for domain in ("std.gear", "std.bearing", "std.fastener", "std.chain"):
        result.update(names(domain))
    return sorted(result)
