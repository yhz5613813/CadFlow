# Native Migration Matrix

This file records the executable boundary rather than treating a green
compatibility suite as proof that every geometry path is native.

## Measured Surface

- Preserved compatibility API: 329 exports, including 213 public functions
- Complete current package API: 358 exports
- Error reporting uses `CadFlowError`; the prohibited former error-class name is
  intentionally not retained as an import alias.
- Functions owned by the modeling operation layer: 164
- Native dispatcher operations: 36
- Full collected regression suite: 1090 tests

## Native C++

The C++ `Session` owns every shape created through `cadflow.Model` or
`cadflow.Graph`. Python only carries `(session_token, shape_id)` handles.

- primitives: box, cylinder, sphere, cone
- profiles and curves: polyline, circle, three-point arc, interpolated B-spline,
  helix, planar face
- surfaces: weighted/unweighted Bezier and fitted point-grid B-spline faces
- features: extrude, revolve, loft, sweep, indexed fillet, chamfer, shell
- booleans: cut, union, intersect
- transforms: translate, rotate, mirror, scale
- queries: kind, volume, area, unique-edge length, center of mass, distance,
  bounding box, topology counts
- exchange: tessellated mesh, STEP import/export, STL export
- execution: multi-operation graph in one C ABI call

## Python By Design

These layers are orchestration and structured-data work, so moving them to C++
would add ABI complexity without removing a geometry bottleneck.

- expression graphs and units
- Model JSON, Scene archives, and schema validation
- product assemblies, connectors, and constraint reports
- semantic tags, source mapping, and lineage records
- translators, documentation tools, and standard-part parameterization

## Remaining Kernel Work

These paths still invoke OCCT through the private Python engine and remain
candidates for the native session:

- hole filling
- helical and twisted sweeps
- explicit control-point and rational B-spline curve builders
- Gordon, ruled, and filling surfaces
- sewing, free-boundary repair, and shell-to-solid conversion
- detailed subshape extraction, local normals, and curvature queries
- native BREP import and STL import

Each migrated path must retain the complete regression suite and add direct
native equivalence, ownership, invalid-input, graph, fallback-build, and wheel
installation coverage.
