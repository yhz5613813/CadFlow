# STEP/BREP Inspection API

## Initial inventory

```python
from cadflow.inspect import brep

summary = brep.inspect_step_rsummary(path="part.step")
report = brep.inspect_step_rbrepinspection(path="part.step")
model = brep.load_step_rbrepmodel(path="part.step")
```

Use `summary` for bounded global facts. Use `model.summary()`,
`model.describe_entity("face:0")`, and `model.adjacency_details("face:0")` when
multiple queries target the same file.

## Entity and topology queries

```python
entity = brep.inspect_step_entity_rdescriptor(
    path="part.step", entity_id="face:0"
)
neighbors = brep.inspect_topology_neighborhood_rdescriptor(
    model_or_path="part.step", entity_id="face:0", depth=2
)
boundary = brep.inspect_face_boundaries_rdescriptor(
    model_or_path="part.step", face_id="face:0", compact=True
)
section = brep.inspect_section_rdescriptor(
    model_or_path="part.step",
    origin=[0, 0, 10],
    normal=[0, 0, 1],
    compact=True,
)
```

Start compact. Request exact curve or surface definitions only for selected
entities and record why the definition is needed. Keep complete arrays in an
output parameter file, not in prompts or summaries.

## Comparisons

```python
global_delta = brep.compare_global_properties_rdescriptor(
    target="target.step", current="candidate.step"
)
material = brep.compare_material_rdescriptor(
    target="target.step", current="candidate.step",
    include_components=True,
    boolean_tolerance=None,
)
boundary_delta = brep.compare_boundary_distance_rdescriptor(
    target="target.step", current="candidate.step", max_samples=200
)
strict = brep.compare_steps_rbrepcomparison(
    target_path="target.step", candidate_path="candidate.step"
)
evaluation = brep.evaluate_reconstruction_rdescriptor(
    target="target.step", current="candidate.step", replay_succeeded=True
)
```

Use the actual function signature exposed by the installed package; inspect
`docs/api/` when an argument name is uncertain. Do not pass a fuzzy tolerance
when claiming strict equality. `include_components=True` is required for
difference-region localization or exporting material components.

## Rendering diagnostics

```python
brep.render_step_views_rpath("part.step", "out/part_views.png")
brep.render_entity_map_rpath(
    "part.step", ["face:0", "edge:2"], "out/entities.png"
)
brep.render_region_rpath(
    "part.step", ["face:0"], "out/region.png", neighborhood_depth=1
)
```

Rendering is for diagnosis and communication. It cannot replace geometric or
topological comparison.

## Candidate requirements

The reconstruction script must:

- import only public CadFlow APIs;
- not load the target STEP at runtime;
- use explicit parameters and a reproducible coordinate frame;
- validate and replay independently;
- write candidate artifacts and evidence under the designated output path.
