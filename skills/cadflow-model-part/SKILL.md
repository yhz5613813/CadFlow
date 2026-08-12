---
name: cadflow-model-part
description: Build, inspect, validate, and export a mechanical CAD part with CadFlow's public Python API. Use for dimensioned solids, sketches, profiles, holes, pockets, bosses, lofts, sweeps, blends, chamfers, transforms, and single-part STEP/STL deliverables. Do not use for static cloth or flexible-shell meshes; use cadflow-flexible-model instead.
---

# CadFlow Part Modeling

Build one reproducible mechanical part at a time. Use `import cadflow as cad`
and the public Python frontend. Read `references/public-api.md` when a
signature or operation boundary matters.

## Select the modeling boundary

- Use `cad.Model()` and `cad.Shape` for the current session-oriented frontend
  when writing ordinary part scripts.
- Use `GraphSession`, `@cad.model`, `cad.capture_result()`, and the
  `make_*_r*` APIs when the result must be replayed through model JSON.
- Do not mix shapes created by different sessions.
- Do not import `cadflow._engine`, OCP/CadQuery classes, native handles, or
  private shared-library symbols in a part script.

## Required workflow

1. Extract units, dimensions, tolerances, datums, feature order, placement,
   and requested output files. State assumptions when the specification is
   incomplete.
2. Choose and document the coordinate frame. Keep all dimensions in one unit;
   convert at the input boundary rather than mixing units in operations.
3. Build named intermediate values in feature order: base, additive features,
   subtractive tools, transforms, then finishing operations.
4. Use sketches for dimensioned planar profiles. Promote a solved sketch to a
   wire/face before extrusion, revolution, or a profile cut.
5. After the base, every boolean, and each fillet/chamfer/shell, query a
   diagnostic. Check overlap and tool extent for through cuts.
6. Validate the final shape: validity, solid count, volume, area, bounding-box
   extents, and the topology needed by the request. Compare against stated
   tolerances, not visual intuition.
7. Export only after validation. Create the output directory, write requested
   STEP/STL/PNG/JSON files, and verify existence and non-zero size.
8. Leave the generation script and report exact assumptions, commands,
   measurements, and output paths.

## Modeling rules

- Treat operations as functional: retain useful source values instead of
  overwriting every feature.
- Keep a requested single part as one `Solid`; never hide a failed boolean by
  returning an arbitrary component of a compound.
- Query faces/edges before indexed fillet, chamfer, or shell selections.
  Topology indices can change after any topology-changing operation.
- Apply repeated holes or pockets sequentially unless fused tools are known to
  overlap and the fused tool has been validated.
- Use positive, finite dimensions and reject impossible radii before invoking
  a kernel operation.
- Keep graph recording and export parameters faithful. Do not claim replay
  equivalence when only a preview was checked.

## Minimal current-frontend pattern

```python
from pathlib import Path
import cadflow as cad

out = Path("outputs/bracket")
with cad.Model() as model:
    base = model.box(width=20.0, depth=30.0, height=10.0)
    tool = model.cylinder(radius=3.0, height=14.0)
    tool = model.translate(tool, x=10.0, y=15.0, z=-2.0)
    final_part = model.cut(base, tool)

    print(final_part.describe())
    print(final_part.validate().to_dict())
    print(final_part.bbox, final_part.volume, final_part.topology)

    out.mkdir(parents=True, exist_ok=True)
    final_part.export_step(str(out / "bracket.step"))
    final_part.export_stl(str(out / "bracket.stl"), binary=True)
```

For replayable workflows, see `references/public-api.md` for the
`GraphSession`/`@cad.model` pattern.

## Failure handling

- A native-library error is an environment/build issue until geometry checks
  prove otherwise. Report the exact command and error; do not bypass it with
  private imports.
- For a failed boolean, inspect body/tool bounds, overlap, orientation, and
  validity before changing dimensions.
- For a failed feature, reduce the selection and radius only as a documented
  diagnostic experiment; do not silently weaken the requested geometry.
- If the specification is underdetermined, state the chosen assumption and
  expose it as a parameter in the script.
