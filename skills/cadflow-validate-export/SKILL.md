---
name: cadflow-validate-export
description: Validate CadFlow geometry and mesh results, replay model JSON, check topology and files, and produce trustworthy STEP/STL/OBJ/JSON/PNG deliverables. Use after any CAD or static flexible-material generation when the output must be tested, rendered, exported, or reported with measured evidence.
---

# CadFlow Validation and Export

Use this skill as the final quality gate. It does not create geometry by itself;
it verifies the result produced by a modeling skill and refuses unsupported or
unmeasured claims.

## Required validation sequence

1. Identify the artifact type: rigid `Shape`, replayable `ModelResult`, or
   static `FlexibleMesh`. Record source script, environment, units, and output
   directory.
2. Validate geometry before export. For solids check validity, one-solid
   topology, volume, area, bbox extents, and expected feature dimensions. For
   flexible meshes check finite arrays, index bounds, unit normals, triangle
   area, panel ranges, deterministic rebuild, and watertightness when thick.
3. If graph/model JSON exists, import and replay it independently. Compare
   result count and measured geometry; do not trust only a successful parser.
4. Export requested files. Verify each file exists, is non-empty, has the
   expected header/format, and can be parsed or reopened when a parser exists.
5. Render requested views. Check PNG signature, dimensions, non-zero content,
   and that all requested views are present.
6. Write a concise report with pass/fail status, measured values, tolerances,
   file sizes, and residual risks.

## Public boundaries

- Use `import cadflow as cad`.
- Use public `cadflow.flexible` for flexible meshes and public modeling,
  serialization, and inspection APIs for rigid geometry.
- Do not repair a bad result by editing private native code during validation.
- Do not call a static mesh watertight merely because it renders; inspect edge
  multiplicities and triangle orientation.

## Rigid-shape gate

```python
assert final_shape.validate().to_dict()["ok"]
assert final_shape.topology["solids"] == 1
assert final_shape.volume > 0.0
lower = final_shape.bbox[:3]
upper = final_shape.bbox[3:]
assert all(u > l for l, u in zip(lower, upper))
```

Query expected dimensions and tolerances explicitly. A valid shape with the
wrong dimensions is a failed deliverable.

## Flexible-mesh gate

```python
import numpy as np

assert np.all(np.isfinite(mesh.vertices))
assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0, atol=1e-5)
assert int(mesh.triangles.max()) < mesh.vertex_count
points = mesh.vertices[mesh.triangles]
areas = 0.5 * np.linalg.norm(
    np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1
)
assert float(areas.min()) > 1e-9
if any(panel.material.thickness > 0 for panel in mesh.panels):
    assert mesh.is_watertight
```

## Export gate

For rigid shapes use `export_step` and `export_stl`. For flexible meshes use
`write_obj`, `write_stl`, and `write_json`. Ensure the parent directory exists.
Check STL triangle count and expected binary length when applicable:

```python
import struct
with open(stl_path, "rb") as handle:
    handle.seek(80)
    count = struct.unpack("<I", handle.read(4))[0]
assert stl_path.stat().st_size == 84 + 50 * count
```

For PNG, verify the eight-byte PNG signature, width/height from the IHDR, and
that the file is not an empty placeholder.

## Reporting

Report exact paths and measurements. Separate:

- measured facts (counts, bounds, area, file sizes);
- assumptions (units, coordinate frame, inferred dimensions);
- validation status;
- unresolved risks (e.g. no physical cloth simulation, approximate folds, or
  unsupported external CAD features).
