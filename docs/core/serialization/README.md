# Serialization and Replay Operation Guides

This directory documents how CadFlow serializes replayable modeling operations into the canonical low-level `model.json` operation graph.

The long-form schema reference remains [`../operation_graph_json_spec.md`](../operation_graph_json_spec.md). These files are more practical, operation-by-operation guides intended for people comparing source code with exported JSON.

## Recommended workflow

```python
import json
import cadflow as cad

@cad.model(graph_id="drilled_block")
def build_model():
    body = cad.make_box_rsolid(width=10, height=6, depth=2)
    hole = cad.make_cylinder_rsolid(
        radius=1, height=4, bottom_face_center=(0, 0, -1)
    )
    result = cad.cut_rsolid(body, hole)
    cad.capture_result(value=result)
    return result

model = build_model()
payload = json.loads(model.model_json)
rebuilt = model.replay()
```

Inspect these fields:

- `payload["graph"]["nodes"]`: canonical operation nodes in topological order.
- `node["op"]`: stable replay operation name.
- `node["params"]`: numeric / JSON-compatible parameter snapshot.
- `node["param_exprs"]`: optional expression links into `expression_graph`.
- `node["inputs"]`: upstream node ids used by replay.
- `payload["leaf_ids"]`: explicit final result node ids.
- `payload["expression_graph"]`: expression DAG used by expression-backed parameters.
- `payload["tolerance_graph"]`: dimension-chain requirements and validation evidence.

For new top-level models, `ModelResult.model_json` is the preferred artifact
accessor. Use `@cad.requires_session` for reusable builders and
`cad.capture_result(...)` when the final output should not be inferred from
all graph leaves. If a model invocation also needs durable CAD/viewer files,
pass `export_dir=...` to `@cad.model`; its captured geometry/product values
then produce one self-contained `<graph_id>.scene.zip`. It embeds
`model/model.json`, mapped project-relative Python sources, and the evaluated
render/selection assets. It does not create adjacent model/session JSON, STEP,
or STL files. No files are written when `export_dir` is omitted.

## Important rule: source API is not always graph API

Many user-facing functions are convenience APIs. During an active `GraphSession`, they lower to canonical low-level nodes:

| Source call | Serialized graph result |
| --- | --- |
| `make_box_rsolid(...)` | rectangle profile + `make_extrude_rsolid` |
| `make_cylinder_rsolid(...)` | circle face + `make_extrude_rsolid` |
| `make_sphere_rsolid(...)` | profile + `make_revolve_rsolid` |
| `make_cone_rsolid(...)` | profile + `make_revolve_rsolid` |
| `make_rectangle_rwire(...)` | line edges + `make_wire_from_edges_rwire` |
| `make_circle_rface(...)` | circle edge + wire + face |
| `make_polyline_rwire(...)` | line edges + wire |
| `linear_pattern_rsolidlist(...)` | explicit `make_translate_rshape` nodes |
| `radial_pattern_rsolidlist(...)` | explicit `make_rotate_rshape` nodes |
| `helical_sweep_rsolid(...)` | helix wire + profile face + `make_sweep_rsolid` |

## Guides

- [Primitive and profile operations](primitives-and-profiles.md)
- [Features, booleans, transforms, patterns, and selectors](features-booleans-transforms.md)
- [Expressions and replay behavior](expressions-and-replay.md)
- [Physical units and dimension inference](../physical-units.md)
- [Dimension tolerance chains](../dimension-tolerance-chains.md)
