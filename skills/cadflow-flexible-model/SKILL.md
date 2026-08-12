---
name: cadflow-flexible-model
description: Build static flexible-material geometry in CadFlow for cloth, leather, sheet goods, membranes, draped panels, and garments. Use when the deliverable is a static multi-face surface or thin shell with dense mesh output, wrinkles, sections, OBJ/STL/JSON, or rendered PNG views. Do not add gravity, collision, time integration, velocity, XPBD, or motion simulation.
---

# CadFlow Static Flexible Modeling

Model the shape that a flexible product is intended to have at one fixed
configuration. This skill is for geometry generation, not physical simulation.
Use `import cadflow as cad` for the package and import the flexible domain from
`cadflow.flexible`.

## Choose the representation

- Use `FlexiblePanel` for an arbitrary rectangular control-point surface.
- Use `RingSection` plus `sectioned_panel` for sleeves, trouser legs, tubes,
  torsos, rolled sheets, or other section-driven garment parts.
- Use `FlexibleModel` to concatenate independent panels while preserving panel
  names and index ranges.
- Use positive `FlexibleMaterial.thickness` for a closed thin shell; use zero
  thickness only for an intentionally open surface.
- Use a CadFlow `Model`/`Solid` only when the request is a rigid BREP part.
  Do not force a cloth panel into a rigid-solid workflow.

## Required workflow

1. Extract the design intent: panel boundaries, section centers and axes,
   dimensions, material thickness, wrinkle/fold locations, sampling density,
   output formats, and the fixed pose to model.
2. State units and coordinate assumptions. Normalize section axes and keep the
   same unit across all panels.
3. Build one panel at a time. Name panels by semantic role (`torso`, `left_leg`,
   `right_sleeve`) rather than by numeric order.
4. Use static wrinkle parameters (`wrinkle_amplitude`, `wrinkle_count`, and
   `wrinkle_phase`) as geometry inputs. Never introduce a time loop or solver.
5. Choose sampling density from curvature and inspection needs. Increase
   `sample_rows`/`sample_columns` where folds are tight; do not hide self-
   intersections or bad parameterization by oversampling.
6. Build the combined `FlexibleMesh`, then validate vertex/triangle indices,
   finite coordinates, unit normals, non-degenerate triangles, panel ranges,
   deterministic output, and watertightness when thickness is positive.
7. Export OBJ, binary STL, and metadata JSON. Render orthographic front/side/top
   plus a perspective geometry view when the user asks to see the result.
8. Report the exact mesh counts, bounds, area, panel names, thickness, output
   paths, and all assumptions.

## C++/Python boundary

Keep the boundary stateless and narrow:

- C++ (`native/src/flexible/shell_mesh.*`) performs dense grid sampling,
  periodic seams, smooth normals, thickness offsets, boundary walls, and
  triangle indexing.
- Python (`python/cadflow/flexible.py`) owns material/design semantics,
  section construction, panel composition, validation, measurement, and file
  export.
- Do not add C++ callbacks into Python, time state, scene state, collision
  state, gravity, velocity, or an XPBD/deformable simulation API.

## Minimal section-driven pattern

```python
from cadflow.flexible import (
    FlexibleMaterial, FlexibleModel, RingSection, sectioned_panel,
)

fabric = FlexibleMaterial(name="cotton", thickness=1.2)
torso = sectioned_panel(
    "torso",
    [
        RingSection((0, 0, 0), (1, 0, 0), (0, 1, 0), 220, 130),
        RingSection((0, 0, 500), (1, 0, 0), (0, 1, 0), 250, 145,
                    wrinkle_amplitude=0.02, wrinkle_count=7),
    ],
    control_columns=24,
    sample_rows=48,
    sample_columns=72,
    material=fabric,
)

model = FlexibleModel("static-garment")
model.add_panel(torso)
mesh = model.build()
assert mesh.is_watertight
mesh.write_obj("out/garment.obj")
mesh.write_stl("out/garment.stl")
mesh.write_json("out/garment.json")
```

For a complete four-view renderer, use
`examples/cadflow_static_flexible_garment.py` as the project-local template.

## Failure handling

- Reject non-finite or negative material thickness and invalid control grids.
- Reject non-orthogonal or zero section axes before building a panel.
- Treat non-watertight positive-thickness output as a modeling failure, not as a
  cosmetic warning.
- If folds self-intersect, adjust section geometry or wrinkle amplitude; do not
  claim physical cloth behavior from a static procedural perturbation.
- If a requested feature requires motion, hand the request back as outside
  this skill's scope rather than adding a simulator.
