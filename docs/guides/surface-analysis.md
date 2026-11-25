# Surface Analysis

CadFlow measures the quality of BREP surfaces in the native C++ core and returns
JSON-safe reports plus inspection images. The checks mirror the surface-quality
workflow of class-A CAD systems: boundary continuity, curvature, reflection
lines, and surface-definition defects.

All measurements are exact evaluations of the OCCT surfaces, not of a mesh.
Lengths use model units and curvatures use inverse model units. Curvature is
signed against the oriented face normal (`n . S_uu`), the same convention as
`Shape.surface_metrics()`: a convex solid reads negative.

## Boundary continuity

```python
import cadflow as cad

with cad.Model() as model:
    part = model.fillet(model.box(10, 20, 30), 3.0, [0])
    report = part.continuity()
    report["summary"]          # {"G2": 0, "G1": 2, "G0": 13, "gap": 0, ...}
    for edge in report["edges"]:
        edge["edge_index"], edge["faces"], edge["level"]
```

Every manifold edge shared by two faces is sampled (`samples`, default 16).
At each sample the core compares the two faces and classifies the edge:

| Level | Condition (all previous conditions also hold) | Default tolerance |
|---|---|---|
| `gap` | positions differ by more than `position_tolerance` | `1e-3` |
| `G0` | positions match, normals differ by more than `angle_tolerance_degrees` | `0.5` |
| `G1` | tangent planes match, relative cross-boundary normal curvature differs by more than `curvature_ratio_tolerance` | `0.05` |
| `G2` | curvature matches across the boundary | |

The G2 measure is `|k_a - k_b| / max(|k_a|, |k_b|)`, where `k` is the normal
curvature of each face in the direction perpendicular to the edge. With G1
already satisfied this is the complete curvature-continuity condition. A
circular fillet against a plane is the textbook G1-but-not-G2 case: the report
shows `curvature_a = 0`, `curvature_b = -1/R`, and a ratio of 1.

`edge_index` and `faces` use the same deterministic order as `Model.fillet`
and `Model.faces`, so an agent can act on the reported edges directly. Each
edge also reports the worst sample locations, `orientation_flipped` when the
two faces traverse the edge in the same direction (inconsistent shell
orientation), and counts of skipped `seam`, `free`, `degenerated`, and
`non_manifold` edges.

### Unsewn faces

`face_a.continuity_with(face_b)` checks two separate faces before they are
sewn. Boundary edges are matched geometrically, side-B parameters come from
projection, samples outside the overlapping part of the boundaries are
ignored, and normals are compared as unoriented lines (`orientation_flipped`
records when the second face had to be reversed). The reported gap is the
distance to the other face's boundary curve.

## Curvature

`face.curvature_samples(u_count, v_count)` evaluates a row-major grid (v
varies fastest) over the trimmed UV bounds. Each sample carries the point,
oriented normal, principal curvatures and directions, mean and Gaussian
curvature, `inside` (classified against the trimming boundary), and `singular`
(undefined normal, for example at a sphere pole; curvature fields are NaN).

## Surface quality

```python
report = shape.surface_quality(samples=24, check_self_intersection=False)
for face in report["faces"]:
    face["definition"]      # degrees, poles, knots, internal continuity, control-net reversals
    face["curvature"]       # principal and Gaussian ranges, minimum radius, inflections
    face["issues"]          # severity, code, message, hint
report["issues"]            # warnings and errors from every face, prefixed with the face index
```

| Code | Severity | Meaning |
|---|---|---|
| `surface.invalid_topology` | error | BRepCheck rejects the face |
| `shape.self_intersection` | error | sub-shapes interfere (only with `check_self_intersection=True`) |
| `surface.internal_crease` | warning | an interior knot inside the face has full multiplicity: C0 inside one face |
| `surface.control_net_undulation` | warning | second differences of a control-net row reverse three or more times |
| `surface.curvature_oscillation` | warning | normal curvature changes sign three or more times along an isoparametric line |
| `surface.tight_curvature` | warning | minimum radius below 0.1% of the face size |
| `surface.large_tolerance` | warning | a face, edge, or vertex tolerance exceeds `1e-3` |
| `surface.internal_c1` | info | an interior knot limits the face to C1 |
| `surface.singular_points` | info | some samples have an undefined normal |

Only knots strictly inside the face's trimmed UV range are considered. The
self-intersection check uses OCCT's argument analyzer, which detects
interference between sub-shapes; it does not detect a single face folding
through itself.

## Visual inspection

```python
from cadflow import surface_analysis as sa

mesh = shape.curvature_mesh(deflection=0.01)   # exact curvature per vertex
mesh.summary()                                  # ranges and tightest-radius location
sa.render_png(mesh, "zebra.png", mode="zebra", view_direction=(-0.3, -0.25, -1))
sa.render_png(mesh, "mean.png", mode="mean")     # or gaussian, k_min, k_max, max_abs
sa.render_png(mesh, "iso.png", mode="isophote")
open("mean.glb", "wb").write(sa.to_glb(mesh, sa.curvature_colors(mesh.field("mean"))))
```

`render_png` is an orthographic z-buffer rasterizer that interpolates the
exact surface normal per pixel, so zebra and isophote band edges follow the
geometry rather than the triangle layout. BREP face boundaries are outlined.
Read zebra stripes across a boundary as follows: they break at G0, stay
connected but kink at G1, and continue smoothly at G2.

Curvature colour maps are diverging (blue negative, white zero, red positive,
grey singular). The symmetric range is a percentile of the non-zero
magnitudes so flat faces do not collapse the scale; `render_png` returns the
range it used.
