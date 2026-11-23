# Class-A Surface Construction

CadFlow builds the transition surfaces of styled parts in the native core and
verifies them with the [surface analysis](surface-analysis.md) tools. Every
operation below states the continuity it produces, and the tests measure it.

## Why a dedicated implementation

OCCT 7.9.3's constrained plate filling (`BRepOffsetAPI_MakeFilling`) cannot
deliver curvature-continuous transitions:

- `BRepFill_Filling` passes the `GeomAbs_Shape` value of a constraint straight
  into `BRepFill_CurveConstraint`, which accepts orders 0 to 2. `GeomAbs_G2` is
  enum value 3, so every G2 request throws "The continuity is not G0 G1 or G2"
  (and `GeomAbs_C1`, value 2, silently means G2).
- Measured on a bridge between two curved patches whose exact G2 bridge is
  known, plate filling asked for G1 delivered only G0 (2.8 degree normal
  error), and asked for G2 through the C1 workaround left a 0.032 gap and an
  8.8 degree crease, with visible ripples across the plate.

`Model.blend_surface` on the same input measures G2 with a 2e-8 gap, 1.5e-6
degree normal error, and a 1e-7 relative curvature error.

## Blend between two faces

```python
blend = model.blend_surface(face_a, edge_a, face_b, edge_b, continuity="G2")
blend.continuity_with(face_a)["edges"][0]["level"]   # "G2"
```

`edge_a` must be a boundary edge of `face_a` (use `model.edges(face_a)`), and
likewise for side B. `continuity` is `"G0"`, `"G1"`, `"G2"`, or a pair for
per-side control. The edges are coupled by arc length; `reverse_b=None` picks
the coupling with the shorter rulings.

Each cross section is a quintic Bezier curve. Its first three poles come from
side A and the last three from side B: position, the tangent-plane direction
perpendicular to the edge that leaves the face, and the face's normal
curvature in that direction. With handle length `d`:

```text
P1 = P0 + d T
P2 = P0 + 2 d T + (5/4) k d^2 N      (G2 only)
```

which gives the section the support's tangent and exactly its normal curvature
`k` (`C''(0) . N = 25 k d^2 = k |C'(0)|^2`). Along the edges the pole rows are
interpolated, and the number of sections doubles until the boundary deviates
less than `tolerance` (default `1e-6`) from both edges.

`tension` fixes the handle factor (`d = tension * chord / 5`; 1.0 spaces the
poles evenly on a straight bridge). By default the factor minimizing the
scale-free curvature-variation energy `L^3 * integral (dk/ds)^2 ds` over the
whole blend is chosen. That is the minimum-variation criterion of class-A
surfacing: the curvature rises from each support to one central peak. The
optimal factor depends on the corner angle (about 1.02 at 30 degrees, 1.21 at
90 degrees, 1.8 at 150 degrees), so no fixed default fits every corner. One
factor serves the whole blend; choosing it per section lets it wander where
the energy is flat and ripples the surface.

## Curvature-continuous fillet

```python
edge = 3   # same index order as Model.fillet and Model.edges
smooth = model.smooth_fillet(part, 3.0, [edge])      # continuity="G2"
```

A circular fillet is only G1: curvature jumps from the neighbour's value to
`1/R` at each trim line, which shows as a break in reflections. On a box edge
the continuity report shows `curvature_a = 0, curvature_b = 1/R, ratio = 1`.

`smooth_fillet` runs OCCT's circular fillet only to place the trim lines at the
given `setback` and to fix the topology, then rebuilds every new face:

- **Rounds.** OCCT's round surface is swept by rolling-ball sections, and its
  two trim lines are iso-parameter lines. The replacement blend keeps OCCT's
  spine parameter, so each blend section joins the same two contact points as
  OCCT's section at that parameter, and is a quintic G2 section between them.
- **Chains of tangent rounds** (e.g. a straight edge running into an arc)
  share their junction sections exactly and one automatic tension.
- **Corners** where three or more rounds meet replace OCCT's spherical or
  plate corner with an n-sided patch: Kato's transfinite interpolation of the
  rounds' second-order ribbons, faired by a bubble-function correction that
  minimizes the third-order variation energy without touching the boundary.
  It is split into n degree-5 B-spline quads. The quads' boundary pole rows
  are solved jointly for the G1 condition and the linearized G2 condition
  `n . F_cc = II(F_c, F_c)`; the interior poles are fitted to the patch with
  a control-net fairness term. Each pass leaves the tangential parts of the
  cross derivatives free near the polygon vertices, where neighbouring sides
  constrain the same poles.
- **Miters** where two rounds meet at an angle (two filleted edges of a
  three-edge corner) are rebuilt as the intersection curve of the two blends,
  as in OCCT's own miter.
- **End faces** that the rounds run into are planar faces re-bounded by the
  blend's end section.

The result is sewn into one validated solid with the circular fillet's
topology. Measured results (`Shape.continuity()`):

| Case | Circular fillet | `smooth_fillet` |
|---|---|---|
| Box edge, 3 mm | G1, curvature 0 vs 0.333 | G2, curvature 0 vs 0, single central peak 0.477 |
| Cylinder rim (closed loop) | G1 | G2 on both trim lines |
| Plane meets B-spline side | G1, curvature 0.500 vs 0.141 | G2, 0.141 vs 0.141 (ratio 5e-13) |
| Box corner, three rounds | 9 G1 | 15 G2 (rounds, corner seams, corner to rounds) |
| All 12 box edges | 48 G1 | 96 G2 |
| Triangular / pentagonal / hexagonal prism, all edges | G1 | all G2 (60, 108, 120 degree wall angles) |
| Stadium rim (line-arc chain) | G1 | G2 trim lines; junctions G1, as is the rim itself |

On the corner patches the worst measured relative curvature mismatch is
about 3% (G2 threshold 5%) with sub-0.002 degree normal error. Corner
patches are the expensive part: a hexagonal prism with every edge rounded
(12 corners) takes about 1 s on many cores, against 30 ms for OCCT's circular
fillet. Because the transition leaves each face with that face's own
curvature, it keeps slightly more material than the arc (box edge: 5942 mm3
round, 5962 mm3 smooth, 6000 mm3 sharp).

Current limits, each reported with a clear error:

- corners where a round ends on a boundary that is not one of its cross
  sections, typical of tapered parts (lofted frustums);
- corner patches that touch unrounded faces (unequal setbacks);
- closed rounds (cylinder rims) that meet other rounds;
- end faces must be planar and contain the blend's end sections, i.e. the
  filleted edge meets them perpendicularly;
- the setback must be one OCCT's circular fillet accepts.

On strongly skewed corners (the 53 degree corner of a wedge) the patch is G2
but `surface_quality` may flag control-net undulation on the corner quads;
the zebra stripes remain continuous.

## Boundary filling

`model.filling_surface(edges)` accepts edges or one-edge wires in any order and
direction. They are chained head to tail within `tolerance`, shared corners
are snapped together, and:

- three or four edges produce a Coons patch that interpolates every boundary
  curve exactly;
- five or more edges produce a plate surface through the boundary, rejected if
  it deviates more than `tolerance`.

Earlier releases fitted nine mixed boundary samples, so a four-edge boundary
could return a zero-area face 10 units away from one of its edges.

## Sewing

`model.sew` accepts any face or shell, including imported faces, faces from
`model.faces`, Gordon surfaces, and blends. It previously rejected faces by
the constructor that created them.
