# Validation Checklists

## Model JSON replay

```python
import cadflow as cad

result = build_model()
payload = cad.import_model_json(result.model_json)
replayed = cad.replay_model_json(result.model_json, strict=True)
assert len(replayed) == len(result.result_node_ids)
```

Check that graph operations are canonical, final outputs are explicit, and
replay does not depend on the source process's live shape objects.

## OBJ checks

Count `v`, `vn`, `f`, and panel `g` records. Ensure every face index is in
`1..vertex_count` and every requested panel group appears exactly once.

## STL checks

Read the unsigned little-endian triangle count at byte offset 80. Binary STL
length must equal `84 + 50 * triangle_count`. Also check the header is not being
mistaken for an ASCII STL file.

## PNG checks

The first eight bytes must be `89 50 4e 47 0d 0a 1a 0a`. Read width and height
from the IHDR chunk and require dimensions appropriate to the requested views.
For a rendered garment, inspect the image once visually or through a pixel
occupancy check; a valid PNG header alone does not prove the render is useful.

## Reproducibility

Run the builder twice with identical inputs. For flexible meshes compare vertex,
normal, and triangle arrays exactly. For graph models compare canonical JSON or
the measured result within documented numeric tolerances. Record the command and
Python environment used for the check.
