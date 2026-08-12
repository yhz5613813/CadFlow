# Static Flexible Material Modeling

`cadflow.flexible` builds high-density static surfaces and thin shells for
cloth, leather, sheet products, membranes, and other flexible parts. It does
not implement time integration, motion, gravity, collision, or other physical
simulation.

## C++ and Python Boundary

The native C++ module `native/src/flexible/shell_mesh.*` owns only the
geometry-intensive operations:

- Catmull-Rom sampling of a sparse control-point grid;
- periodic seam sampling without duplicate columns;
- smooth vertex-normal construction;
- normal-offset shell thickness;
- boundary-wall triangulation for closed thin shells.

The Python module `cadflow.flexible` owns design and workflow concerns:

- material thickness and appearance metadata;
- arbitrary control-surface panels;
- elliptical garment sections and procedural static wrinkles;
- multi-panel garment composition;
- mesh validation, measurements, and OBJ/STL/JSON export.

The boundary is one stateless array call per panel. No BREP session, OCCT
handle, time state, or Python callback is held by the C++ builder. Existing
`Model`, `Shape`, assembly, and BREP behavior is unchanged.

## Generic Panel

```python
from cadflow.flexible import FlexibleMaterial, FlexiblePanel

panel = FlexiblePanel(
    name="draped panel",
    control_points=control_grid,
    sample_rows=48,
    sample_columns=64,
    material=FlexibleMaterial(thickness=1.2),
)
mesh = panel.build()
```

Use `periodic_columns=True` for a closed ring of control columns. A positive
thickness creates two offset surfaces and closes every geometric boundary. A
zero thickness produces a single surface.

## Sectioned Garment Panel

```python
from cadflow.flexible import RingSection, sectioned_panel

sections = [
    RingSection(
        center=(0, 0, 0),
        axis_u=(1, 0, 0),
        axis_v=(0, 1, 0),
        radius_u=200,
        radius_v=120,
        wrinkle_amplitude=0.02,
        wrinkle_count=7,
    ),
    RingSection(
        center=(0, 0, 500),
        axis_u=(1, 0, 0),
        axis_v=(0, 1, 0),
        radius_u=240,
        radius_v=140,
    ),
]
panel = sectioned_panel("torso", sections)
```

`examples/cadflow_static_flexible_garment.py` builds a five-panel short-sleeve
jumpsuit and writes a high-density OBJ, binary STL, metadata JSON, and a PNG
containing front, side, top, and perspective geometry views.
