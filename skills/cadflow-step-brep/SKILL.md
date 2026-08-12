---
name: cadflow-step-brep
description: Inspect STEP/BREP files, characterize geometry and topology, reverse engineer a readable CadFlow model, and compare a candidate against a target. Use for .step/.stp inputs, CAD inspection, feature inference, reconstruction, BREP validation, section analysis, and difference diagnosis. Do not modify the SDK or treat visual similarity alone as proof.
---

# CadFlow STEP/BREP Inspection and Reverse Engineering

Treat the STEP file as an input artifact to inspect, not as a script to copy.
Use the diagnostic namespace outside modeling sessions:

```python
from cadflow.inspect import brep
```

Read `references/inspection-api.md` for the exact functions and payload fields.

## Choose the task

- **Inspect**: summarize entities, bounds, volume, area, carrier types, and
  topology without constructing a candidate.
- **Diagnose**: localize differences with sections, entity comparisons,
  boundary distances, material regions, or render maps.
- **Reconstruct**: infer a readable feature sequence and write a new CadFlow
  script that does not read the target STEP at runtime.
- **Compare**: evaluate target and candidate using global properties first, then
  strict material or BREP comparisons when the candidate is close enough.

## Required workflow

1. Record the target path, file hash, benchmark mode, units/coordinate
   assumptions, and output directory.
2. Run `inspect_step_rsummary` and record validity, body/shell counts, bounds,
   volume, area, centroid, and surface/curve statistics.
3. Inspect only the entities needed for the current hypothesis. Use stable
   IDs such as `face:0` and `edge:0`; they are deterministic for the same
   unchanged file but are not semantic IDs across different models.
4. Establish openings, cavities, symmetry, repeated features, section planes,
   and likely analytic carriers before choosing primitives or features.
5. Reconstruct with public `cadflow` APIs. Use `import cadflow as cad`, keep
   the final script independent of the target STEP, and expose inferred
   dimensions as named parameters.
6. Replay the candidate independently and validate it before comparison.
7. Compare cheaply first: global properties and bounded sections. Use material
   difference with `include_components=True` and no fuzzy tolerance for an
   equality claim. Use strict BREP comparison only when explicitly required.
8. Save reports, candidate source, replay payload, renders, and comparison
   results under the output directory. State what was measured versus inferred.

## Inspection boundary

- BREP inspection is diagnostic and must not run inside `GraphSession` or an
  `@cad.model` callback.
- Do not import private engine modules or direct OCP types in the reconstruction
  script.
- Do not search outside the authorized target directory for prior solutions,
  caches, deleted files, or another agent's output.
- Do not embed, copy, or re-export target STEP contents into the candidate.

## Evidence hierarchy

1. Exact BREP topology identity is the strongest result.
2. Strict bidirectional material equality proves the occupied point set matches,
   even if feature histories differ.
3. Matching volume, area, bounds, centroid, and sections are useful gates but
   do not prove equality alone.
4. Similar renders are diagnostic evidence only.

Never stop at “looks close” when a better feature order or supported operation
could still be tested. If stopping with a structurally different candidate,
record the exhausted hypothesis or unsupported operation that justifies it.

## Failure handling

- A timeout or fuzzy Boolean leaves equivalence unproved; it is not a pass.
- A large global volume mismatch disproves equality cheaply; do not spend time
  on strict difference computation first.
- For a local mismatch, use `inspect_section`, `compare_sections`,
  `compare_boundary_distance`, or `render_region` rather than rerunning every
  expensive comparison.
- Preserve compact reports and hashes; do not paste huge control-point arrays
  into the final narrative.
