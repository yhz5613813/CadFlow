---
name: cadflow-contact-simulation
description: Add solver-neutral, face-level mechanical simulation metadata to CadFlow assemblies and export verified contact packages. Use for FEA handoff, contact pairs, friction, penalty or cohesive laws, surface roughness/coatings, component materials, face normals, initial gaps, interference, or BREP surface regions. Do not use for concentrated connector springs alone; use the physical connection API for reduced 6-DOF joints.
---

# CadFlow Contact Simulation

Build distributed surface-contact semantics on already valid rigid assembly
geometry. Use `import cadflow as cad` and public APIs only. Read
`references/contact-api.md` for constructors, units, and package fields.

## Select the physical model

- Use `ContactSimulationModel` when tractions act over BREP faces and the
  downstream consumer is an FEA or continuum solver.
- Use `PhysicalConnectionLayer` when the interface is intentionally reduced to
  a connector-local 6-DOF wrench law.
- Do not copy a connector stiffness into a surface penalty. Their dimensions
  differ: force/length versus force/length^3.
- CadFlow exports geometry and constitutive declarations; it does not mesh,
  solve equilibrium, or claim solver convergence.

## Required workflow

1. Validate every part and assemble it in a documented coordinate system.
2. Select component-local `Face` objects and create named `SurfaceRegion`
   values. Use `flip=True` only when the intended contact normal opposes the
   BREP face orientation.
3. Declare explicit length, force, time, and temperature units. Add mechanical
   materials and assign them to all contacting components.
4. Define surface properties when roughness or coatings matter. Define contact
   laws with an explicit normal model, separation behavior, friction model,
   penalty data, damping, or cohesive strengths as applicable.
5. Define directed contact pairs, search tolerance, initial clearance or
   interference, normal-opposition threshold, and sliding formulation.
6. Run semantic validation, then native analysis. Reject unresolved or
   ambiguous face references and inspect candidate count, oriented normals,
   minimum distance, signed gap, and solver-adjusted gap.
7. Export a contact package only after validation. Reopen its BREP files and
   verify recorded hashes when it crosses a process or machine boundary.

## Minimal pattern

```python
import cadflow as cad

surface_a = cad.make_surface_region_rsurfaceregion(
    surface_id="housing.seat", component_id="housing", faces=(seat_face,)
)
surface_b = cad.make_surface_region_rsurfaceregion(
    surface_id="bearing.outer", component_id="bearing", faces=(outer_face,)
)
law = cad.SurfaceContactLaw(
    "steel_contact",
    normal_model="penalty",
    normal_penalty_stiffness=2.0e5,
    friction_model="coulomb",
    friction_coefficient=0.15,
)
pair = cad.SurfaceContactPair(
    "seat_pair", "housing.seat", "bearing.outer", "steel_contact",
    search_tolerance=0.1, sliding="finite",
)
simulation = cad.make_contact_simulation_model_rcontactsimulationmodel(
    assembly,
    surfaces=(surface_a, surface_b),
    contact_laws=(law,),
    contact_pairs=(pair,),
    length_unit="mm", force_unit="N", time_unit="s",
)
simulation = simulation.with_material(
    cad.MechanicalMaterial("steel", 210000.0, 0.3, density=7.85e-9)
)
simulation = simulation.assign_material("housing", "steel")
simulation = simulation.assign_material("bearing", "steel")

report = cad.validate_contact_simulation_model_rcontactsimulationvalidationreport(
    simulation, assembly
)
report.raise_for_errors()
analysis = cad.analyze_contact_simulation_model_rcontactsimulationanalysis(
    simulation, assembly
)
cad.export_contact_simulation_package_rpath(
    simulation, assembly, "outputs/contact-package"
)
```

## Failure handling

- An unresolved or ambiguous face is a failed simulation handoff. Re-select it
  from the rebuilt part; do not substitute a nearby face silently.
- A pair with zero candidates is valid only when delayed contact is intended.
  Otherwise inspect placement, normal orientation, gap, and search tolerance.
- The analytic fallback cannot produce BREP surface evidence. Rebuild with the
  OCCT backend instead of fabricating metrics in Python.
- Preserve declared values. Do not invent material, friction, penalty, coating,
  or cohesive parameters from geometry alone.
