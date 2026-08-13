"""Translator backends for exporting CadFlow model JSON to external CAD systems."""

from importlib import import_module
from importlib.util import find_spec

__all__: list[str] = []

for _backend_name in ("fusion360_translator", "solidworks_translator"):
    _qualified_name = f"{__name__}.{_backend_name}"
    if find_spec(_qualified_name) is None:
        continue
    globals()[_backend_name] = import_module(_qualified_name)
    __all__.append(_backend_name)

del _backend_name, _qualified_name
