# System-Level Performance Bottlenecks

Status: recorded for future work; no optimization is implemented by this
document.

This document tracks performance costs caused by shared CadFlow architecture
and execution paths. It intentionally excludes one-off example complexity,
model-specific operation counts, and historical file timestamp gaps that could
not be reproduced.

Measurements were collected on 2026-08-13 with the editable CadFlow checkout,
`/data/yihongzhu/SimpleCADAPI-venv`, OCCT 7.9.3, and headless VTK using OSMesa.
Times are baselines rather than cross-machine performance guarantees.

## P1: Eager Default Tessellation

### Problem

Compatibility `Shape` creation eagerly builds and attaches a default triangle
mesh, including for intermediate shapes and solids that are never rendered or
exported as a mesh. This couples exact BREP construction to a potentially
expensive derived representation.

### Impact

The cost affects any workflow that creates many shapes. It increases build
latency and peak memory, and generated meshes can become obsolete after later
geometry operations.

### Evidence

The 4,962-solid willow benchmark took 132.425 s to build. Profiling attributed
127.822 s cumulative time to `build_solid_trimesh`, including 90.687 s in face
tessellation. The full build-and-render process reached 3.43 GiB peak resident
memory.

### Suggested Direction

Store exact geometry as the authoritative result and materialize a mesh only
when a mesh consumer requests it. Keep preview quality explicit and make mesh
cache invalidation follow shape identity or revision.

### Future Acceptance Criteria

- Constructing an exact shape does not tessellate unless explicitly requested.
- Non-rendered intermediate shapes allocate no triangle buffers.
- Existing public rendering and mesh-export behavior remains compatible.
- The willow build baseline drops substantially without shifting the same work
  into an unconditional later phase.

## P1: Repeated Tessellation Across Consumers

### Problem

Validation, rendering, STL export, and other mesh consumers can independently
copy or tessellate the same BREP. There is no shared tessellation result keyed
by geometry identity and meshing parameters.

### Impact

Repeated OCCT meshing and conversion scale with geometry complexity and with
the number of downstream consumers. A workflow that validates, previews, and
exports can pay essentially the same preparation cost multiple times.

### Evidence

Willow direct rendering spent 45.315 s of 51.329 s in 16 `_mesh_polydata`
calls, while the actual VTK `Render` call took 1.374 s. In the STEP four-view
benchmarks, BREP copy, tessellation, and VTK mesh construction cost 0.676 s for
the mounting bracket and 1.187 s for Sun Wukong before rasterization.

### Suggested Direction

Introduce one tessellation service and cache keyed by immutable shape identity,
linear/angular deflection, relative mode, and required attributes. Let
validation, preview, and export consume the same compatible buffers.

### Future Acceptance Criteria

- Repeating a mesh request with identical inputs does not call OCCT meshing or
  rebuild buffers.
- Validation followed by rendering and STL export reuses compatible geometry.
- Cache invalidation is deterministic after geometry changes.
- Cache memory is bounded and observable.

## P1: Sequential Eager Boolean Execution

### Problem

Repeated unions are executed eagerly in input order. The shared modeling path
does not expose a multi-shape batch operation, construct a balanced reduction
tree, or defer work so adjacent booleans can be planned together.

### Impact

This penalizes assemblies and generated parts composed from many primitives.
Intermediate BREPs can grow progressively more complex, making later boolean
steps increasingly expensive.

### Evidence

The Sun Wukong build profile took 22.715 s. Its 45 union operations consumed
15.604 s. A further 4.803 s was spent in 52 volume queries, so booleans plus
intermediate measurement accounted for about 90% of the measured build.

### Suggested Direction

Add native batch boolean support, select a stable balanced execution strategy,
and allow the graph executor to delay booleans until their result is consumed.
Preserve exact failure reporting and deterministic result semantics.

### Future Acceptance Criteria

- A multi-shape union crosses the Python/native boundary once.
- The executor avoids a linear chain of increasingly complex intermediate
  results when a balanced plan is valid.
- Boolean validity and topology regression suites remain unchanged.
- The Sun Wukong boolean phase is materially faster than the current 15.604 s
  baseline under the same benchmark conditions.

## P1: Per-Group Geometry Duplication

### Problem

Rendering geometry grouped by color or label can copy and mesh the same source
geometry separately for each group. Presentation metadata therefore controls
how many times geometry preparation runs.

### Impact

Scenes with many semantic groups pay repeated BREP copy, tessellation, Python
conversion, and VTK allocation costs. Runtime can grow with group count even
when the underlying geometry is unchanged.

### Evidence

The willow renderer made 16 `_mesh_polydata` calls and spent 45.315 s in that
preparation path. The produced scene had millions of mesh elements, so copying
per group also contributes to its multi-gigabyte peak memory use.

### Suggested Direction

Tessellate each source shape once, retain stable face/solid ownership indices,
and derive render groups as indexed views or cell attributes over shared
buffers.

### Future Acceptance Criteria

- Adding a color or label does not remesh unchanged geometry.
- Mesh preparation scales primarily with unique geometry, not presentation
  group count.
- Rendered colors, labels, selection IDs, and visibility remain correct.

## P1: Element-Wise Python Mesh Conversion

### Problem

OCCT triangulation is converted through Python one vertex and one triangle at a
time before reaching NumPy or VTK-compatible storage.

### Impact

Interpreter calls, temporary Python objects, and repeated bounds/type checks
become a shared bottleneck for large meshes. The cost affects previews,
inspection output, and mesh export regardless of the model that produced the
BREP.

### Evidence

In the willow render, geometry preparation consumed 45.315 s while actual VTK
rasterization consumed 1.374 s. The profiled STEP mesh reached approximately
4.84 million points and 8.51 million triangles, amplifying per-element Python
overhead.

### Suggested Direction

Expose contiguous native vertex, normal, ownership, and index buffers through
the public frontend boundary using bulk buffer interchange. Construct NumPy and
VTK arrays from those buffers without Python element loops.

### Future Acceptance Criteria

- Mesh transfer performs a bounded number of Python/native calls independent
  of vertex and triangle count.
- Large-mesh conversion time and temporary-object allocation are substantially
  lower than the current baseline.
- Buffer ownership and lifetime are explicit and covered by tests.

## P2: Fragmented Derived-Property Computation

### Problem

Volume, area, bounding box, topology counts, and validity are derived repeatedly
through separate call paths. CadFlow has no unified shape-property cache or
single inspection pass shared across these queries.

### Impact

Generated models often query properties after each operation for validation,
selection, reporting, or control flow. Repeating OCCT traversals adds latency
even when geometry has not changed.

### Evidence

Sun Wukong issued 52 volume queries that consumed 4.803 s, more than one fifth
of its 22.715 s profiled build. These queries targeted geometry already held by
the session.

### Suggested Direction

Cache derived properties by immutable shape identity and offer a native bulk
inspection call that computes requested fields with shared traversals. Do not
compute fields that no consumer requested.

### Future Acceptance Criteria

- Repeated identical property queries perform no repeated OCCT calculation.
- A bulk query can return volume, area, bounding box, topology, and validity in
  one native boundary crossing.
- New shape results cannot observe stale properties from their inputs.
- Sun Wukong's repeated-property phase is materially faster than the 4.803 s
  baseline.

## P2: STEP Round-Trip in Internal Preview Paths

### Problem

Some internal preview workflows serialize exact geometry to STEP and read it
back before rendering, even though the geometry already exists in process.
STEP is an interchange format, not an efficient internal transport.

### Impact

The round-trip adds serialization, filesystem I/O, parsing, reconstruction, and
possible metadata/precision differences. It also obscures whether time belongs
to model generation or visualization.

### Evidence

The measured willow STEP export alone took 7.140 s. Current direct rendering
works from the in-memory result and completes without requiring that export.
Historical timestamp gaps are deliberately excluded because they do not provide
reliable phase timing.

### Suggested Direction

Pass in-memory shape handles or shared tessellation buffers directly to the
preview layer. Keep STEP conversion only when the user explicitly requests a
STEP artifact or an interoperability test requires it.

### Future Acceptance Criteria

- Internal previews of in-memory models perform no STEP filesystem I/O.
- Explicit STEP export and STEP-import preview remain supported.
- Direct and exported/reloaded previews have documented parity checks.

## P3: CPU-Only Headless Rasterization

### Problem

The current headless VTK environment selects `vtkOSOpenGLRenderWindow` and
OSMesa software rendering instead of a hardware EGL/OpenGL path.

### Impact

Raster-heavy views and repeated image capture use CPU resources and cannot take
advantage of an available GPU. This is a deployment-level limitation rather
than the primary geometry-generation bottleneck.

### Evidence

VTK render and PNG output took 1.582 s for the mounting-bracket four-view and
1.883 s for the Sun Wukong four-view. For willow, actual VTK `Render` took
1.374 s, far below the 45.315 s geometry-preparation cost. The flexible-mesh
Matplotlib render took 4.316 s, but it is a separate renderer and should not be
used to estimate VTK acceleration.

### Suggested Direction

Provide an optional EGL-enabled VTK runtime for compatible machines while
retaining OSMesa as a deterministic fallback. Report the active backend in
benchmark and diagnostic output.

### Future Acceptance Criteria

- Runtime diagnostics distinguish hardware EGL from OSMesa fallback.
- Headless output passes the existing image-content checks on both backends.
- GPU acceleration is evaluated separately from tessellation and buffer
  conversion so improvements are not misattributed.

## Measurement Rules for Future Work

Each optimization should be measured with phase timers and function profiles,
using the same input artifact, mesh settings, renderer, image size, and process
lifecycle as its baseline. Report wall time and peak resident memory. Historical
file modification intervals may be supporting context but must not be treated
as phase measurements.

Optimization work remains intentionally deferred until it is separately
scheduled and assigned.
