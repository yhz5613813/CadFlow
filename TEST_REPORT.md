# Verification Report

Verification was performed with Python 3.10, GCC 9.4, CMake 3.16, and the
OCCT 7.9.3 libraries supplied by `cadquery-ocp`.

## Full Regression

```text
python -m pytest -q --disable-warnings --tb=short
1024 passed, 66 skipped in 581.55s
```

All 1090 collected tests were included. No rendering, translator, collision,
or compatibility test files were excluded. The 66 results are declared skips
for optional external backends or future contracts; there were no failures.

The suite covers the complete bundled API, graph/session replay, tags and
topology lineage, sketches, product assemblies, constraints, standard parts,
Scene contracts and archives, BREP inspection and headless rendering,
translators, collision fallback, tooling, examples, and the native frontend.

## Native Builds

The layered C++ source was compiled in both configurations with warnings
enabled (`-Wall -Wextra -Wpedantic`):

```text
OCCT backend:       build succeeded
analytic fallback: build succeeded
OCCT native tests:  16 passed, 1 skipped
fallback smoke:     passed
```

Direct native tests cover primitives, polygon/circle/arc/spline/helix curves,
Bezier and fitted-grid surfaces, faces, extrusion, revolution, loft, sweep,
indexed fillet/chamfer/shell features, booleans, transforms, properties,
topology, mesh, STEP import/export, STL export without pre-meshing, graph
batching, invalid selections, fallback errors, and session ownership. The
public header and shared library expose the same 44 `cadflow_*` symbols.

The analytic fallback was validated against its declared capability boundary,
not against exact OCCT behavior. Its smoke run covers the analytic version
marker, primitive construction and properties, graph execution, session
isolation, structured errors, and explicit rejections for fillet, chamfer,
shell, STEP, and STL operations. Exact topology, tessellation, exchange, edge
features, and exact boolean equivalence are not claimed for this build.

## Distribution

A platform wheel and source distribution were rebuilt from the layered tree.
The wheel contains `libcadflow_core`, the public C header, all Python modules,
and all Scene contracts. Its native library uses this portable runtime path:

```text
$ORIGIN/../cadquery_ocp.libs
```

The wheel was installed into a clean target directory with no source checkout
on its import path. Compatibility geometry, native geometry, public submodule
aliases, Scene resources, entry-point metadata, and the absence of the retired
private layout were verified from that installation. The source distribution
contains the layered C++ tree and the domain-owned Python engine and was
independently rebuilt into a wheel.

## Naming Audit

Case-insensitive scans of source contents and path names show no occurrence of
the prohibited former project name. The same scan was applied to the wheel and
source distribution; neither archive contains the removed `_runtime` layout.

## Scope

Passing tests prove complete behavior is bundled and preserved. They do not
claim that every geometry path is already implemented in the native session.
The measured C++ coverage and remaining kernel work are listed in
`MIGRATION_MATRIX.md`.
