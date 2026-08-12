# Native Layer

The native backend has one-way dependencies:

```text
c_api -> runtime -> kernel -> core
  |          |         ^
  +--------> io -------+
```

## Boundaries

- `include/cadflow_core.h` is the only stable, installed ABI header.
- `src/core` owns sessions, shape records, handles, and exception translation.
- `src/kernel/construction` creates primitives, profiles, and curves.
- `src/kernel/features` creates solids from profiles and paths.
- `src/kernel/surfaces` creates Bezier and fitted-grid surfaces.
- `src/kernel/edge_features` owns indexed fillet, chamfer, and shell operations.
- `src/kernel/operations` owns booleans and transforms.
- `src/kernel/queries` owns measurements and topology inspection.
- `src/io` owns CAD exchange and tessellation formats.
- `src/runtime` parses and executes batch graphs.
- `src/c_api.cpp` validates ABI arguments, locks a session, and delegates.

## Rules

1. `core` must not include a higher-level native module.
2. OCCT algorithms belong in `kernel` or `io`, never in `c_api.cpp`.
3. Python-visible objects remain opaque `ShapeId` values owned by one session.
4. A new operation needs a C ABI declaration, native implementation, ctypes
   binding, direct test, graph test when batchable, and fallback behavior.
5. Internal headers are private build inputs and are not installed in wheels.
