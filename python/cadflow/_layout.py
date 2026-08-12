"""Authoritative mapping between compatibility names and engine domains."""

from __future__ import annotations

from pathlib import Path


_EXACT_MODULES = {
    "_mesh": "geometry._mesh",
    "_vendor_warning_filters": "foundation._vendor_warning_filters",
    "autotag": "semantics.autotag",
    "core": "geometry.core",
    "errors": "foundation.errors",
    "evolve": "workflow.evolve",
    "expr": "foundation.expr",
    "frame": "foundation.frame",
    "graph": "workflow.graph",
    "math": "foundation.math",
    "operations": "geometry.operations",
    "product": "assembly.product",
    "ql": "workflow.ql",
    "serializer": "workflow.serializer",
    "sketch": "geometry.sketch",
    "source_mapping": "foundation.source_mapping",
    "surface": "geometry.surface",
    "tagging": "semantics.tagging",
    "tolerance": "semantics.tolerance",
    "topology": "semantics.topology",
    "tracking": "semantics.tracking",
    "units": "foundation.units",
}

_PACKAGE_MODULES = {
    "auto_tools": "tools",
    "inspect": "geometry.inspection",
    "kernel": "geometry.kernel",
    "scene": "exchange.scene",
    "sketch_solver": "constraints",
    "std": "library",
    "translator": "exchange.translators",
    "verifier": "verification",
}


def engine_module_name(compatibility_name: str = "") -> str:
    """Resolve an old public module path to its domain-owned implementation."""
    name = compatibility_name.strip(".")
    if not name:
        return "cadflow._engine"
    exact = _EXACT_MODULES.get(name)
    if exact is not None:
        return f"cadflow._engine.{exact}"
    for public_prefix, engine_prefix in _PACKAGE_MODULES.items():
        if name == public_prefix:
            return f"cadflow._engine.{engine_prefix}"
        prefix = public_prefix + "."
        if name.startswith(prefix):
            suffix = name.removeprefix(prefix)
            return f"cadflow._engine.{engine_prefix}.{suffix}"
    raise KeyError(f"unknown compatibility module: {compatibility_name}")


def logical_source_path(
    logical_name: str, engine_root: Path | None = None
) -> Path:
    """Map a former package-relative source name to the new physical path."""
    root = engine_root or Path(__file__).resolve().parent / "_engine"
    logical = logical_name.replace("\\", "/").removeprefix("./")
    suffix = Path(logical).suffix
    module_name = logical[: -len(suffix)] if suffix else logical
    dotted = module_name.replace("/", ".")
    target = engine_module_name(dotted).removeprefix("cadflow._engine.")
    path = root.joinpath(*target.split("."))
    return path.with_suffix(suffix) if suffix else path


def logical_name_for_source(path: Path, engine_root: Path | None = None) -> str:
    """Return the compatibility-relative name used by generated API docs."""
    root = (engine_root or Path(__file__).resolve().parent / "_engine").resolve()
    relative = path.resolve().relative_to(root).as_posix()
    for name, target in _EXACT_MODULES.items():
        target_path = target.replace(".", "/") + ".py"
        if relative == target_path:
            return name + ".py"
    for public_prefix, engine_prefix in _PACKAGE_MODULES.items():
        physical = engine_prefix.replace(".", "/")
        if relative == physical + "/__init__.py":
            return public_prefix + "/__init__.py"
        prefix = physical + "/"
        if relative.startswith(prefix):
            return public_prefix + "/" + relative.removeprefix(prefix)
    if relative == "__init__.py":
        return "__init__.py"
    raise KeyError(f"source is outside the compatibility layout: {path}")


COMPATIBILITY_ROOT_MODULES = tuple(sorted((*_EXACT_MODULES, *_PACKAGE_MODULES)))
