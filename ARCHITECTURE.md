# CadFlow Architecture

CadFlow is split into three boundaries:

```text
Python frontend       native C ABI              OCCT
Model / Graph  ->  Session + ShapeHandle  ->  TopoDS_Shape
compat domains    batch executor              booleans / mesh / GProp
```

## Frontend

`cadflow.Model` owns an explicit session and exposes handle-based primitives.
`cadflow.Graph` compiles a typed operation list into one native call. The
frontend contains no OCC imports. `cadflow.backend.Router` chooses native
operations for native handles and routes every other operation to the complete
compatibility implementation.

The domain modules (`modeling`, `graph_api`, `serialization`, `inspection`,
`scene`, `assembly`, `sketch`, `stdlib`, `query`, `topology`, and `translators`)
are intentionally small public facades over the bundled `cadflow._engine`
implementation. This keeps the public layout stable while Python kernel paths
are replaced domain by domain with native operations.

## Native ownership

The C++ `Session` owns all shapes. Python receives only a pair of integers:
the session token and shape ID. A handle cannot be used with another session,
and closing a session invalidates all of its handles. Expensive OCC calls run
inside C++, so topology and geometry data do not cross the Python boundary one
object at a time.

The native source tree follows the dependency direction below:

```text
c_api.cpp -> runtime / io / kernel -> core
```

`core` owns no modeling algorithms. `kernel` owns geometry construction and
inspection. `io` owns serialization formats. `runtime` parses batch programs
and calls the kernel. Only `c_api.cpp` includes the public ABI boundary, so
internal OCCT types and module headers are not installed as public API.

The native vertical slice implements:

- box, cylinder, sphere, and cone construction
- polygon and circle profiles plus planar faces
- extrusion, revolution, loft, and sweep
- exact OCCT cut, fuse, and intersection
- translate, rotate, mirror, and uniform scale
- volume, area, and bounding-box queries
- topology counts
- tessellation into JSON vertex/index buffers
- optional STEP export
- compact batch graph execution

## Compatibility contract

`cadflow.compat` lazily exposes the complete compatibility API, including Model JSON,
strict replay, topology tracking, tags, selectors, sketches, assemblies,
Scene archives, BREP inspection, translators, and standard parts. The
implementation is installed inside the `cadflow` distribution and never reads
another source checkout.

The bundled engine is both the complete feature layer and the behavioral test
oracle. Geometry-heavy paths move into the native session while metadata,
serialization, assemblies, constraints, and translators stay in Python. See
`MIGRATION_MATRIX.md` for the measured boundary and remaining kernel work.
