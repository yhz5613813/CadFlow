# Modern Python Frontend

CadFlow's modern frontend has two intentionally separate layers:

- `CoordinateFrame` and `Workplane` are immutable Python values and context
  managers. They transform point/vector arguments and never mutate shapes.
- `SketchDocument` is a declarative Python document. Constraint solving uses
  the existing `py-slvs` backend; it is not duplicated in C++. A sketch is
  lowered to a native `Model` shape only at `to_native_face()`.
- `Shape.describe()`, `Shape.validate()`, `Model.capabilities()`,
  `Model.preflight()`, and `Model.apply()` form the Agent feedback boundary.
  Their results are JSON-safe `OperationReport`/`OperationResult` values.

Example:

```python
import cadflow as cad

with cad.Model() as model:
    with model.workplane(origin=(10, 0, 5), normal=(0, 1, 0)) as plane:
        sketch = plane.sketch("mounting_profile")
        sketch = sketch.add_point("a", 0, 0).add_point("b", 20, 0)
        sketch = sketch.add_point("c", 20, 10).add_point("d", 0, 10)
        sketch = (sketch.add_line("ab", "a", "b")
                        .add_line("bc", "b", "c")
                        .add_line("cd", "c", "d")
                        .add_line("da", "d", "a"))
        sketch = sketch.constrain_fix("a")
        result = sketch.inspect(strict=False)
        assert result.status in {"solved", "underconstrained"}
        face = sketch.to_native_face(model, strict=False)

    outcome = model.apply("extrude", face, 0, 0, 8)
    if not outcome.report.ok:
        print(outcome.report.to_dict())
    else:
        print(outcome.shape.describe())
```

The C++ backend remains responsible for OCCT construction, booleans,
tessellation, measurements, and exchange. Python remains responsible for
constraints, frames, operation policy, diagnostics, serialization, and Agent
recovery hints. This prevents solver/context state from crossing the opaque
native shape-handle ABI.
