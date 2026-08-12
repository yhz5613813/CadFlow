# Agentic Reconstruction Dataset Example

This example converts one real Autodesk Fusion 360 Gallery Reconstruction
record into an executable, OpenAI-style tool-call trajectory backed by the
public CadFlow API.

## Source sample

- Dataset: Reconstruction `r1.0.1`
- Sample: `118433_f14b7df9_0000`
- Units: centimeters and radians
- Features: `NewBody`, symmetric `Cut`, symmetric `Join`
- Planes: XZ and XY construction planes

The selected record contains three rectangular profiles. It is deliberately
small enough to audit while still exercising sketches, two plane coordinate
systems, extrusions, symmetric extents, two Boolean operations, QL grounding,
STEP export, graph replay, rendering, and B-Rep evaluation.

## Tool coverage

The generated trajectory uses these tools:

1. `reconstruction_read_sample`
2. `brep_inspect_step`
3. `cad_create_profile`
4. `cad_extrude_profile`
5. `cad_apply_feature`
6. `cad_inspect_model`
7. `cad_export_artifacts`
8. `cad_heal_same_domain`
9. `brep_evaluate_reconstruction`

The tool schemas are OpenAI function schemas. The modeling tools lower to
public CadFlow calls such as `make_line_redge`,
`make_wire_from_edges_rwire`, `make_face_from_wires_rface`,
`extrude_rsolid`, `translate_shape`, `cut_rsolid`, `union_rsolid`, QL,
`export_step`, and `ModelResult.replay`.

`cad_heal_same_domain` is the deliberate exception: CadFlow enables OCC
same-domain cleanup internally, but does not expose its linear tolerance. The
adapter calls `ShapeUpgrade_UnifySameDomain.SetLinearTolerance` and validates
the exported STEP by reading it back through `brep.load_step_rshape`. This
round-trip matters because OCC can report the tolerance-healed in-memory shape
as invalid before STEP transfer normalizes its tolerances. The raw replayable
STEP is kept separately, so the dataset does not pretend this post-process is
part of the current graph schema.

## Compatibility adapters

Fusion and CadFlow do not expose identical concepts. The adapter handles the
gaps explicitly:

- Fusion sketch-local points are transformed into world coordinates with the
  sketch origin and basis vectors.
- Reconstruction JSON lengths are centimeters, while the Fusion STEP and
  CadFlow/OpenCascade interchange boundary are millimeters. Tool arguments
  stay in source centimeters and the adapter applies an explicit `x10` kernel
  scale; reported volumes are converted back to cubic centimeters.
- Fusion trimmed profile loops are converted to connected CadFlow edges,
  wires, and faces. Construction and reference curves outside the selected
  profile are ignored.
- `SymmetricFeatureExtentType` is lowered to a total-length one-sided
  extrusion followed by a negative half-length translation.
- `NewBodyFeatureOperation`, `JoinFeatureOperation`, and
  `CutFeatureOperation` map to current-body assignment, `union_rsolid`, and
  `cut_rsolid`.
- The source mixes float32-like sketch coordinates (`38.099999427795 mm`) with
  exact feature dimensions (`38.1 mm`). A `1e-6 mm` same-domain healing step
  removes the two resulting splitter edges and matches the target topology.

The executable example currently accepts `Line3D` profile carriers. A
production converter should add exact circle, arc, ellipse, conic, and spline
builders, multi-profile operations, face-based sketch planes, taper angles,
two-sided extents, and multi-body tracking.

## Run

```bash
/data/yihongzhu/CadFlow-venv/bin/python \
  examples/agentic_reconstruction_dataset/generate_example.py
```

Generated artifacts are written only under:

```text
/data/yihongzhu/CadFlow/examples/agentic_reconstruction_dataset/out/
```

The primary dataset artifact is `agentic_reconstruction_sample.jsonl`. It
contains one complete record with tool schemas, assistant tool calls, tool
results, source paths, execution status, and generated artifact paths. It does
not store hidden chain-of-thought.

`*.raw.step` is the exact CadFlow graph result. `*.candidate.step` is the
deterministically healed final artifact used for evaluation. Both are retained
to make the compatibility boundary auditable.
