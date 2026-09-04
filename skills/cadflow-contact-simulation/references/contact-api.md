# Contact Simulation API Reference

Use `import cadflow as cad`. The model is immutable; `with_*` and
`assign_material` return updated copies.

## Data objects

- `SurfaceRegion(surface_id, component_id, geometry_refs, role, property_id)`
  binds one or more stable component-local face references.
- `SurfaceProperty` stores roughness and optional coating material/thickness.
- `MechanicalMaterial` stores isotropic Young's modulus, Poisson ratio, and
  optional density, yield stress, and thermal expansion.
- `SurfaceContactLaw` supports `hard`, `penalty`, `tabular`, and `cohesive`
  normal response plus `frictionless` or `coulomb` tangential response.
- `SurfaceContactPair` references two surface IDs and one law ID, with initial
  clearance or interference, search tolerance, opposed-normal threshold,
  `small`/`finite` sliding, and optional activation step.
- `ContactSimulationModel` owns the unit system and all cross references.

## Units

The JSON unit table is authoritative. With force `F`, length `L`, time `T`, and
temperature `Theta`:

| Quantity | Dimension |
| --- | --- |
| Young's modulus, yield/cohesive stress, pressure | `F/L^2` |
| Normal/tangential surface penalty | `F/L^3` |
| Damping per area | `F*T/L^3` |
| Density | `F*T^2/L^4` |
| Roughness, coating thickness, gap, interference | `L` |
| Thermal expansion | `1/Theta` |

## Geometry evidence

`model.faces(shape)` returns native face handles for the session frontend.
`face.surface_metrics()` returns area, centroid, oriented normal, bounding box,
mean/Gaussian/principal curvatures, analytic surface type, and BREP validity.
`face_a.contact_metrics(face_b)` additionally returns closest points, minimum
distance, normal dot product, signed normal gap, and tangential offset.

For replayable assembly parts, create regions with
`make_surface_region_rsurfaceregion(..., faces=(face,))`. Validation resolves
the stored geometric selector against the current component body and rejects
missing or ambiguous matches.

## Analysis and package

`analyze_contact_simulation_model_rcontactsimulationanalysis` transforms faces
into assembly coordinates and calls the C++ OCCT measurement kernel. Each pair
reports the raw geometric signed gap, `solver_initial_normal_gap` (raw gap plus
declared clearance minus interference), `initial_overclosure`, and whether the
face pair is an initial candidate.

`export_contact_simulation_package_rpath` writes:

```text
simulation.json
components/component-NNNNNN.brep
surfaces/surface-NNNNNN.brep
```

The manifest contains the complete semantic model, material assignments,
component transforms, stable component face indices, metrics, relative BREP
URIs, byte lengths, and SHA-256 hashes. Component and face BREPs remain in local
coordinates; consumers must apply the recorded row-major 3x4 rigid transform.
