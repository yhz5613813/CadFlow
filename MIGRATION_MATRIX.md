# Native Migration Matrix

This file records the executable boundary rather than treating a green
compatibility suite as proof that every geometry path is native.

## Measured Surface

- Preserved compatibility API: 329 exports, including 213 public functions
- Complete current package API: 414 exports
- Error reporting uses `CadFlowError`; the prohibited former error-class name is
  intentionally not retained as an import alias.
- Functions owned by the modeling operation layer: 164
- Native dispatcher operations: 36
- Full collected regression suite: 1010 tests plus 313 parametrized subtests

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
- advanced kernel: exact rational/non-rational B-spline edges, twisted sweep,
  ruled/filling/Gordon surface construction, sewing, shell-to-solid conversion,
  BREP/STL import, subshape extraction, free-boundary extraction, face normal
  and curvature queries, transformed face metrics, and exact face-pair closest
  points/gap evidence for contact preprocessing
- execution: multi-operation graph in one C ABI call

## Python By Design

These layers are orchestration and structured-data work, so moving them to C++
would add ABI complexity without removing a geometry bottleneck.

- expression graphs and units
- Model JSON, Scene archives, and schema validation
- product assemblies, connectors, and constraint reports
- solver-neutral surface regions, material/contact-law declarations,
  cross-reference validation, JSON, and simulation-package manifests
- semantic tags, source mapping, and lineage records
- translators, documentation tools, and standard-part parameterization

## Remaining Kernel Work

These paths still invoke OCCT through the private Python engine and remain
candidates for the native session:

- hole filling with the full legacy N-side constraint parameter set
- exact Gordon curve-network interpolation matching the optional `ocp_gordon`
  implementation byte-for-byte (native uses a deterministic OCCT surface fit)

The migrated paths have direct C ABI, Python facade, graph, ownership, invalid
input, OCCT equivalence, and fallback-build coverage. The two items above remain
explicitly tracked because their legacy APIs expose richer constraints than the
small public native facade currently promises.
