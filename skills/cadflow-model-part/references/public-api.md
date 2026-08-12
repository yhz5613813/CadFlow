# CadFlow Part API Reference

Use `import cadflow as cad`. Numeric arguments are unitless floats; choose one
consistent unit, normally millimetres, for the whole script.

## Current frontend

```python
with cad.Model() as model:
    box = model.box(width=20.0, depth=30.0, height=10.0)
    cylinder = model.cylinder(radius=3.0, height=14.0)
    profile = model.polyline(
        [(0, 0, 0), (20, 0, 0), (20, 10, 0), (0, 10, 0)],
        closed=True,
    )
    face = model.face(profile)
```

Common constructors include `box`, `cylinder`, `sphere`, `cone`, `polyline`,
`circle_profile`, `face`, `arc`, `interpolate`, `helix`, `bezier_surface`, and
`fit_surface`. Use `model.workplane(...).sketch(...)` for constrained planar
profiles.

## Features and transforms

```python
solid = model.extrude(face, x=0.0, y=0.0, z=10.0)
turned = model.revolve(face, degrees=360.0, axis=(0, 0, 1), origin=(0, 0, 0))
lofted = model.loft((profile_a, profile_b), solid=True, ruled=False)
swept = model.sweep(face, path, solid=True, frenet=False)
rounded = model.fillet(solid, radius=1.0, edges=(0, 1))
beveled = model.chamfer(solid, distance=0.5, edges=(0, 1))
hollow = model.shell(solid, thickness=1.0, faces=(0,), tolerance=1e-3)

cut_part = model.cut(body, tool)
joined = model.union(left, right)
common = model.intersect(left, right)
placed = model.translate(shape, x=dx, y=dy, z=dz)
rotated = model.rotate(shape, degrees=90.0, axis=(0, 0, 1), origin=(0, 0, 0))
mirrored = model.mirror(shape, normal=(1, 0, 0), origin=(0, 0, 0))
scaled = model.scale(shape, factor=2.0, center=(0, 0, 0))
```

## Sketch boundary

```python
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
    solve = sketch.inspect(strict=False)
    face = sketch.to_native_face(model, strict=False)
```

## Replayable graph boundary

```python
@cad.model(graph_id="drilled_block")
def build_model():
    body = cad.make_box_rsolid(width=10, height=6, depth=2)
    tool = cad.make_cylinder_rsolid(radius=1, height=4, bottom_face_center=(0, 0, -1))
    result = cad.cut_rsolid(body, tool)
    cad.capture_result(value=result)
    return result

result = build_model()
replayed = result.replay()
```

Use `cad.export_model_json`, `cad.import_model_json`, and
`cad.replay_model_json` for explicit interchange. Do not infer final outputs
from arbitrary graph leaves when `capture_result` can declare them.

## Inspection and export

Shape diagnostics are available as `kind`, `volume`, `area`, `length`,
`center_of_mass`, `bbox`, `topology`, `describe()`, `validate()`, and `mesh()`.
Always compare bbox extents (`xmax-xmin`, etc.), not only the origin.

```python
assert final_part.validate().to_dict()["ok"]
assert final_part.topology["solids"] == 1
assert final_part.volume > 0.0
```

Export with `shape.export_step(path)` and
`shape.export_stl(path, binary=True)` after creating the parent directory.
