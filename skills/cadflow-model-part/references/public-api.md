# CadFlow Public API Reference

This reference covers the Python-first, session-oriented interface used by the
cadflow-model-part skill. All dimensions are plain floating-point values in a
user-chosen consistent unit. The examples use millimetres.

## Imports and Session Lifetime

~~~python
import cadflow as cad

with cad.Model() as model:
    part = model.box(width=20.0, depth=30.0, height=10.0)
~~~

Model owns the native session. A Shape is valid only while its model is alive
and cannot be passed to another model. Model methods return new shapes; they do
not mutate the source shape.

## Primitive and Profile Construction

~~~python
box = model.box(width, depth, height)
cylinder = model.cylinder(radius, height)
sphere = model.sphere(radius)
cone = model.cone(radius1, radius2, height)

wire = model.polyline(points, closed=False)
circle = model.circle_profile(
    radius,
    center=(x, y, z),
    normal=(nx, ny, nz),
)
face = model.face(wire)
~~~

points is a sequence of 3-coordinate points. Use closed=True for a planar
closed wire intended for face. A circle profile is a wire; turn it into a face
before extrude when a solid is required.

Additional public curve/surface constructors are available when needed:

~~~python
arc = model.arc((start, middle, end))
spline = model.interpolate(points, periodic=False, tolerance=1e-6)
helix = model.helix(
    pitch, height, radius, center=(0, 0, 0), direction=(0, 0, 1)
)
surface = model.bezier_surface(point_grid, weights=weight_grid)
fitted = model.fit_surface(
    point_grid, tolerance=1e-3, degree_min=3, degree_max=8
)
~~~

## Feature Creation

~~~python
prism = model.extrude(profile_face, x=0.0, y=0.0, z=10.0)
turned = model.revolve(
    profile_face,
    degrees=360.0,
    axis=(0, 0, 1),
    origin=(0, 0, 0),
)
lofted = model.loft((lower_profile, upper_profile), solid=True, ruled=False)
swept = model.sweep(profile, path, solid=True, frenet=False)
rounded = model.fillet(shape, radius=1.0, edges=(0, 1))
beveled = model.chamfer(shape, distance=0.5, edges=(0, 1))
hollow = model.shell(shape, thickness=1.0, faces=(0,), tolerance=1e-3)
~~~

## Workplanes and Constrained Sketches

Workplanes and sketches are Python orchestration objects. The sketch solver
uses the bundled `py-slvs` backend; native geometry is created only when a
profile is lowered into the explicit `Model` session.

~~~python
with model.workplane(origin=(10, 0, 5), normal=(0, 1, 0)) as plane:
    sketch = plane.sketch("mounting_profile")
    sketch = (sketch.add_point("a", 0, 0)
                    .add_point("b", 20, 0)
                    .add_point("c", 20, 10)
                    .add_point("d", 0, 10))
    sketch = (sketch.add_line("ab", "a", "b")
                    .add_line("bc", "b", "c")
                    .add_line("cd", "c", "d")
                    .add_line("da", "d", "a"))
    sketch = sketch.constrain_fix("a")
    result = sketch.inspect(strict=False)
    face = sketch.to_native_face(model, strict=False)
~~

`SketchDocument` also exposes `add_circle`, `add_arc`, `add_bspline`, named
references, and the established constraint methods (`constrain_horizontal`,
`constrain_tangent`, `constrain_distance`, `constrain_radius`, and so on).
`result.to_dict()` includes solver backend, status, degrees of freedom,
residual, solved values, and diagnostics.

## Agent Feedback

~~~python
model.capabilities()
shape.describe()                  # JSON-safe geometry summary
shape.validate().to_dict()        # validity and warnings
model.preflight("fillet", shape, radius=1, edges=(0, 1))
outcome = model.apply("cut", body, tool)
if not outcome.report.ok:
    print(outcome.report.to_dict())
~~~

`preflight()` checks session ownership, selection bounds, and common invalid
parameters. `apply()` executes a named model operation and returns an
`OperationResult` containing the value and a machine-readable
`OperationReport`; it does not hide native errors or silently switch kernels.

extrude takes a vector, not a scalar height. revolve uses degrees and a 3D
axis/origin. Fillet, chamfer, and shell selections are optional zero-based
indices; omit the selection only when the kernel should process all applicable
subshapes.

## Booleans and Transforms

~~~python
cut_part = model.cut(body, tool)
joined = model.union(left, right)
overlap = model.intersect(left, right)

placed = model.translate(shape, x=dx, y=dy, z=dz)
turned = model.rotate(
    shape, degrees=90.0, axis=(0, 0, 1), origin=(0, 0, 0)
)
mirrored = model.mirror(shape, normal=(1, 0, 0), origin=(0, 0, 0))
scaled = model.scale(shape, factor=2.0, center=(0, 0, 0))
~~~

For a through hole, place the cutter so it intersects the body and extends
through its full thickness. For repeated holes or pockets, sequential cuts are
the default. union is binary; fuse tools only when they overlap and verify the
fused result before using it as a cutter.

## Inspection and Validation

~~~python
assert abs(shape.volume - expected_volume) <= volume_tolerance
print(shape.kind)
print(shape.volume)
print(shape.area)
print(shape.length)
print(shape.center_of_mass)
print(shape.bbox)       # (xmin, ymin, zmin, xmax, ymax, zmax)
print(shape.topology)   # vertices, edges, faces, solids counts
mesh_data = shape.mesh(deflection=0.1)
~~~

volume, area, length, center_of_mass, bbox, and topology are properties on
Shape. mesh() returns a JSON-like dictionary with vertices and triangles.
Compare the bounding-box extents (xmax - xmin, etc.) with the specified
envelope, not just its origin.

## Exchange

~~~python
shape.export_step("outputs/part.step")
shape.export_stl("outputs/part.stl", binary=True)
~~~

The parent directory must exist or be created by the script. After exporting,
check both file existence and non-zero size. Use model.import_step(path) when
the task is to start from an existing STEP part, then apply supported public
operations in the same model.

## Optional Batch Graph

cadflow.Graph is a lower-level native batch builder. It is useful for a compact,
deterministic operation program, but direct Model code is easier to audit for
ordinary parts.

~~~python
graph = cad.Graph()
base_id = graph.add("box", 20.0, 30.0, 10.0)
tool_id = graph.add("cylinder", 3.0, 10.0)
tool_id = graph.add("translate", tool_id, 10.0, 15.0, 0.0)
part_id = graph.add("cut", base_id, tool_id)
graph.add("volume", part_id)
graph.add("bbox", part_id)
results = graph.execute()
~~~

Graph references are zero-based node IDs. Supported operation names mirror the
Model surface: box, cylinder, sphere, cone, polyline, circle_profile, face,
extrude, revolve, loft, sweep, fillet, chamfer, shell, cut, union, intersect,
translate, rotate, mirror, scale, and inspection operations. Use the source API
when an operation has optional arguments; do not invent graph syntax.

## Environment and Errors

Run scripts from the repository environment with the package importable (for a
source checkout, PYTHONPATH=python is commonly sufficient). cadflow.Model()
loads the packaged or repository native library. A cadflow.NativeError saying
that the library was not found is an environment/build issue; do not import
private implementation modules to work around it. Check the repository README,
native build outputs, and CADFLOW_CORE_LIBRARY only when the environment owner
has configured it.
