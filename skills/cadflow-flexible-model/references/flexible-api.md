# Static Flexible API Reference

## Data types

```python
from cadflow.flexible import (
    FlexibleMaterial, FlexiblePanel, FlexibleModel,
    FlexibleMesh, RingSection, sectioned_panel,
)
```

`FlexibleMaterial` fields:

- `name: str`
- `thickness: float >= 0`
- `color: tuple[float, float, float]` in `[0, 1]`
- `roughness: float` in `[0, 1]`

`FlexiblePanel` requires a finite `(rows, columns, 3)` control grid with at
least `2 x 2` points. `sample_rows` and `sample_columns` must not be smaller
than the control-grid dimensions. Set `periodic_columns=True` for a closed
column seam; periodic panels need at least three control columns.

`RingSection` takes `center`, two non-zero orthogonal axes, `radius_u`,
`radius_v`, and optional static wrinkle parameters. `sectioned_panel` stacks at
least two sections into a periodic panel.

## Mesh facts and checks

`FlexiblePanel.build()` returns a `FlexiblePanelMesh`; `FlexibleModel.build()`
returns a `FlexibleMesh` with:

- `vertices`, `normals`, `triangles`
- `vertex_count`, `triangle_count`
- `bounds`
- `surface_area`
- `is_watertight`
- `panels` containing per-panel vertex/triangle ranges and material metadata

At minimum, check:

```python
import numpy as np

assert np.all(np.isfinite(mesh.vertices))
assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0, atol=1e-5)
assert int(mesh.triangles.max()) < mesh.vertex_count
assert mesh.triangle_count > 0
if material.thickness > 0:
    assert mesh.is_watertight

points = mesh.vertices[mesh.triangles]
areas = 0.5 * np.linalg.norm(
    np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]),
    axis=1,
)
assert float(areas.min()) > 1e-9
```

For a closed panel, also check each undirected edge occurs twice and every
directed edge has exactly one orientation in each direction. This catches
seam, wall, and winding mistakes that `is_watertight` alone cannot diagnose.

## Output methods

```python
mesh.write_obj("out/model.obj")
mesh.write_stl("out/model.stl")
mesh.write_json("out/model.json")
```

The OBJ preserves panel groups. STL is binary and contains the complete shell.
JSON records counts, bounds, area, watertightness, panel ranges, and material
metadata; it is a mesh manifest, not a dynamic simulation state.

## Resolution guidance

- Start with 16-24 control columns and 32-64 sampled columns for sectioned
  panels.
- Increase samples for folds or silhouette inspection, then rerun the
  degeneracy and watertight checks.
- Keep the control grid stable when comparing two design variants so changes
  are attributable to geometry parameters rather than sampling changes.
