# Native Layer

The native backend has one-way dependencies:

```text
c_api -> runtime -> kernel -> core
  |          |         ^
  +--------> io -------+

c_api -> flexible
c_api -> analysis -> core
```

## Boundaries

- `include/cadflow_core.h` is the only stable, installed ABI header.
- `src/core` owns sessions, shape records, handles, and exception translation.
- `src/kernel/construction` creates primitives, profiles, and curves.
- `src/kernel/advanced` owns exact B-splines, twisted/ruled/filling/Gordon
  surfaces, sewing, shell-to-solid conversion, native BREP/STL import, and
  multi-handle topology/curvature queries.
- `src/kernel/features` creates solids from profiles and paths.
- `src/kernel/surfaces` creates Bezier and fitted-grid surfaces.
- `src/kernel/blend` builds G0/G1/G2 quintic Hermite blends between face
  boundaries; `src/kernel/smooth_fillet` uses it to replace circular rounds,
  with n-sided G2 corner patches where rounds meet at a vertex.
- `src/kernel/differential.h` holds the shared exact surface differential
  geometry used by the kernel builders and by `src/analysis`.
- `src/kernel/edge_features` owns indexed fillet, chamfer, and shell operations.
- `src/kernel/operations` owns booleans and transforms.
- `src/kernel/queries` owns measurements and topology inspection.
- `src/io` owns CAD exchange and tessellation formats.
- `src/runtime` parses and executes batch graphs.
- `src/flexible` owns stateless static surface sampling and thin-shell mesh
  construction. It has no dependency on the session-owned BREP kernel.
- `src/analysis` owns read-only surface-quality measurement: boundary
  continuity, exact curvature sampling, curvature-annotated tessellation, and
  surface-definition diagnostics. It never creates session shapes.
- `src/c_api.cpp` validates ABI arguments, locks a session, and delegates.

## Rules

1. `core` must not include a higher-level native module.
2. OCCT algorithms belong in `kernel` or `io`, never in `c_api.cpp`.
3. Python-visible objects remain opaque `ShapeId` values owned by one session.
4. A new operation needs a C ABI declaration, native implementation, ctypes
   binding, direct test, graph test when batchable, and fallback behavior.
5. Internal headers are private build inputs and are not installed in wheels.
6. Stateless array APIs must keep design semantics in Python and expose only
   geometry-intensive kernels through the C ABI.
