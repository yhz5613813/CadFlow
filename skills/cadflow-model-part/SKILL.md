---
name: cadflow-model-part
description: Build, inspect, validate, and export a single mechanical CAD part with CadFlow's public Python frontend. Use when a task asks an agent to create or modify a part from dimensions, sketches, primitives, holes, bosses, blends, chamfers, or other solid features, or to produce STEP/STL output from CadFlow.
---

# CadFlow Part Modeling

Use this skill for one-part CAD jobs. Treat CadFlow's Python frontend as the
only modeling boundary: import cadflow as cad, create one cad.Model, and
compose new Shape values through the model methods. Read
references/public-api.md before selecting an operation or relying on a
signature.

## Required Workflow

1. **Extract the specification.** List units, dimensions, tolerances, required
   features, datum/reference axes, placement, and requested output formats. If
   units are not stated, ask or state the assumption; CadFlow does not attach
   units to numeric arguments.
2. **Choose a coordinate system.** Record what (0, 0, 0) means and which axis
   is the primary extrusion/revolution axis. Keep all feature placements in
   that frame.
3. **Decompose the part.** Build in feature order: base solid, additive
   features, subtractive tools (holes/pockets), then transforms and optional
   finishing features. Keep each intermediate result in a named variable so a
   failed step can be inspected or replaced.
4. **Use one session.** Put the complete pipeline in with cad.Model() as
   model:. Every input Shape to a modeling operation must come from that same
   Model; do not mix shapes from separate sessions.
5. **Ground each risky step.** After the base, each boolean, and each finishing
   feature, query at least kind, volume, or bbox. For a cut, make the tool
   overlap the body and extend beyond the material when a through feature is
   intended.
6. **Validate the final shape.** Check volume, area, bbox, and topology.
   Compare dimensions to the specification with a stated numeric tolerance.
   Use mesh() when a tessellation sanity check is useful.
7. **Export explicitly.** Create the output directory, then call
   final_shape.export_step(path) and/or final_shape.export_stl(path,
   binary=True). Confirm that each requested file exists and is non-empty.
8. **Report reproducibly.** Leave the generation script or test in the
   project, report the coordinate assumptions, feature sequence, validation
   values, and exact output paths. Do not claim a geometric property that was
   not queried or calculated.

## Public Boundary

- Allowed: cadflow.Model, cadflow.Shape, cadflow.Graph, and documented public
  modules such as cadflow.modeling, cadflow.query, cadflow.scene,
  cadflow.stdlib, and cadflow.translators when the task needs them.
- Forbidden: imports from cadflow._engine, direct OCP/OpenCascade imports,
  ctypes access to the core library, private shape handles, or copying native
  implementation details into the part script.
- Prefer the Model/Shape API for direct part creation. Use Graph only when a
  batch/replayable native operation program is explicitly needed; its operation
  names and argument order are documented in the reference.
- For dimensioned profiles, use `model.workplane(...).sketch(...)`. A
  `SketchDocument` preserves named entity references, solves through the
  bundled `py-slvs` backend, and returns diagnostics/DOF before promotion.
- Use `model.capabilities()`, `model.preflight(...)`, `model.apply(...)`,
  `shape.describe()`, and `shape.validate()` as the Agent feedback loop. Treat
  a blocked report as an instruction to inspect or repair inputs, not as a
  reason to guess new geometry.
- Do not silently fall back to a different geometry implementation when the
  native library is unavailable. Report the environment error and follow the
  repository build instructions instead.

## Modeling Rules

- Use millimetres (or another explicitly stated unit) consistently within one
  script. Convert input dimensions once at the boundary.
- Use positive dimensions and radii. Reject or report impossible geometry
  before invoking a boolean (for example, a fillet radius larger than the
  local edge clearance).
- Name variables by feature intent, such as base, mounting_hole_tool,
  base_with_holes, and final_part, rather than overwriting every step.
- Treat operations as functional: model.cut(a, b) and transforms return a new
  shape; retain the source when it is useful for comparison.
- Fillet/chamfer/shell selections are zero-based indices. Query topology first,
  select deliberately, and expect indices to change after a topology-changing
  operation.
- For repeated subtractive features, sequentially cut the individual tools by
  default. Fuse tools with model.union only when they overlap and that fused
  result is verified; disjoint tools are not assumed to form one solid. Make
  every repeated placement explicit.
- Keep the result a single solid when the request describes one part. Check
  final_part.topology["solids"] == 1; do not silently return a compound or
  select one piece from a failed boolean.

## Minimal Template

~~~python
from pathlib import Path
import cadflow as cad


OUT = Path("outputs")

with cad.Model() as model:
    base = model.box(width=20.0, depth=30.0, height=10.0)

    hole_tool = model.cylinder(radius=3.0, height=10.0)
    hole_tool = model.translate(hole_tool, x=10.0, y=15.0, z=0.0)
    final_part = model.cut(base, hole_tool)

    print("final", final_part.kind)
    print("volume", final_part.volume)
    print("bbox", final_part.bbox)
    print("topology", final_part.topology)

    OUT.mkdir(parents=True, exist_ok=True)
    final_part.export_step(str(OUT / "part.step"))
    final_part.export_stl(str(OUT / "part.stl"), binary=True)
~~~

The template is intentionally small. For profiles, revolves, lofts, sweeps,
indexed features, graph execution, import, and troubleshooting, load
references/public-api.md and use only the signatures shown there.

## Failure Handling

- NativeError usually means a missing native library, invalid geometry, or a
  kernel boolean/feature failure. Preserve the error text in the report.
- For a failed boolean, check body/tool overlap, orientation, tool extent, and
  operation order. Inspect the operands before changing dimensions.
- For an invalid export, check that the shape is non-null, the output directory
  is writable, and the path has the requested extension. Re-query the final
  shape after the last operation.
- If the specification is underdetermined, stop at the ambiguity and state the
  assumption instead of inventing hidden geometry.
