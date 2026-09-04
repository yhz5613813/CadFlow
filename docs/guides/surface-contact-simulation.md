# Surface Contact Simulation Handoff

CadFlow's contact-simulation layer describes distributed interactions between
assembly faces without committing to Abaqus, CalculiX, Code_Aster, ANSYS, or a
particular mesher. C++/OCCT measures exact BREP geometry; Python owns named
regions, units, materials, constitutive declarations, validation, JSON, and
package layout.

This layer is separate from `PhysicalConnectionLayer`. A physical connection
returns a concentrated connector wrench and uses stiffness in force/length. A
surface penalty produces traction and uses force/length^3.

## Build a model

Start from an `Assembly` whose contacting components are direct `Part` values.
Select faces from each part in component-local coordinates:

```python
import cadflow as cad

top_face = max(block_a.get_faces(), key=lambda face: face.get_center().z)
bottom_face = min(block_b.get_faces(), key=lambda face: face.get_center().z)

surface_a = cad.make_surface_region_rsurfaceregion(
    surface_id="base.top",
    component_id="base",
    faces=(top_face,),
)
surface_b = cad.make_surface_region_rsurfaceregion(
    surface_id="slider.bottom",
    component_id="slider",
    faces=(bottom_face,),
)
```

The helper converts each face into a replayable `GeometryRef`. Validation later
resolves that selector against the current component body and rejects missing
or ambiguous matches. `flip=True` reverses the semantic normal when the BREP
orientation is opposite to the intended contact side.

Declare the law, pair, and material in one explicit unit system:

```python
law = cad.SurfaceContactLaw(
    "dry_contact",
    normal_model="penalty",
    normal_penalty_stiffness=2.0e5,  # N/mm^3
    friction_model="coulomb",
    friction_coefficient=0.2,
    tangential_penalty_stiffness=8.0e4,  # N/mm^3
)
pair = cad.SurfaceContactPair(
    "slider_pair",
    "base.top",
    "slider.bottom",
    "dry_contact",
    search_tolerance=0.2,
    sliding="finite",
)
steel = cad.MechanicalMaterial(
    "steel",
    youngs_modulus=210000.0,  # N/mm^2
    poisson_ratio=0.3,
    density=7.85e-9,  # N*s^2/mm^4
    yield_stress=355.0,
)
simulation = cad.make_contact_simulation_model_rcontactsimulationmodel(
    assembly,
    surfaces=(surface_a, surface_b),
    contact_laws=(law,),
    contact_pairs=(pair,),
    materials=(steel,),
    component_materials={"base": "steel", "slider": "steel"},
    length_unit="mm",
    force_unit="N",
    time_unit="s",
    temperature_unit="K",
)
```

`hard`, `penalty`, `tabular`, and `cohesive` normal laws are supported as
declarations. Tangential response may be `frictionless` or `coulomb`. CadFlow
validates required parameters and dimensions but does not estimate engineering
values from shape or material names.

## Validate and export

```python
report = cad.validate_contact_simulation_model_rcontactsimulationvalidationreport(
    simulation, assembly
)
report.raise_for_errors()

analysis = cad.analyze_contact_simulation_model_rcontactsimulationanalysis(
    simulation, assembly
)
print(analysis.pair_metrics)

manifest = cad.export_contact_simulation_package_rpath(
    simulation, assembly, "outputs/contact-package"
)
```

The native analysis transforms faces into assembly coordinates and reports:

- face area, centroid, oriented normal, bounding box, analytic surface type,
  mean/Gaussian/principal curvatures, and BREP validity;
- closest points, minimum distance, normal dot product, signed normal gap, and
  tangential offset for every face combination;
- solver initial gap after declared clearance/overlap and an initial contact
  candidate flag based on search tolerance and opposed normals.

The package contains `simulation.json`, complete component-local BREP solids,
and each selected component-local BREP face. The manifest records SHA-256 and
byte length for every BREP, stable component face indices, material assignments,
and row-major 3x4 rigid transforms. A downstream adapter can therefore mesh the
solid, map the selected face, apply the assembly placement, and translate the
neutral law into solver-specific contact cards.

## Boundary and limitations

- The current surface resolver accepts direct `Part` components. Flatten nested
  assemblies or expose the target part as a direct component before handoff.
- The OCCT backend is required for exact BREP metrics and package export. The
  analytic fallback raises an explicit error.
- Candidate detection is preprocessing evidence, not collision detection or a
  nonlinear solve. Curved or moving interfaces still require solver-side
  discretization, tracking, stabilization, and convergence controls.
- CadFlow preserves contact intent and geometric evidence; mesh size, element
  formulation, time stepping, load cases, and boundary conditions remain
  solver inputs.
