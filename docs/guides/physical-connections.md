# Physical Connection Layer

CadFlow keeps physical connection semantics separate from the existing
kinematic `Assembly.constraints` graph. A kinematic constraint answers
"which relative motions are allowed?" A physical connection answers "which
parts are joined, where does the interface act, and how does it carry load?"

The public API is available from `cadflow.physical` and is also re-exported by
`cadflow`:

```python
import cadflow as cad

layer = cad.make_physical_connection_layer_rphysicalconnectionlayer(
    assembly,
    length_unit="mm",
    force_unit="N",
)
behavior = cad.make_connection_behavior_rconnectionbehavior(
    response_mode="interference",
    normal_stiffness=12000.0,
    tangential_stiffness=2500.0,
    friction_coefficient=0.35,
    interference=0.04,
    tensile_limit=800.0,
    shear_limit=450.0,
)
connection = cad.make_physical_connection_rphysicalconnection(
    connection_id="shelf_tenon",
    connection_kind="mortise_tenon",
    connector_a=cad.make_connector_ref_rconnectorref("shelf", "tenon_axis"),
    connector_b=cad.make_connector_ref_rconnectorref("side", "mortise_axis"),
    behavior=behavior,
    insertion_direction=(1.0, 0.0, 0.0),
    kinematic_constraint_id="shelf_side_fixed",
)
layer = cad.add_physical_connection_rphysicalconnectionlayer(layer, connection)
report = cad.validate_physical_connection_layer_rphysicalconnectionvalidationreport(
    layer, assembly
)
report.raise_for_errors()
```

`connection_kind` records the manufacturing/interface category. Built-in
values include `mortise_tenon`, `dovetail`, `dowel`, `bolt`, `screw`, `weld`,
`adhesive`, `press_fit`, `snap_fit`, `bearing`, `contact`, and `custom`.
`response_mode` selects the reduced-order load law:

- `bonded`: bilateral translational and rotational springs;
- `frictional_contact`: unilateral normal penalty plus Coulomb shear cap;
- `interference`: unilateral penalty using `interference` and `clearance`;
- `fastener`: bilateral springs with an axial preload;
- `compliant`: bilateral spring/damper response without fastener preload.

The mode is intentionally independent from the connection kind. For example,
a mortise-tenon connection may be modeled as bonded for a rigid reduced-order
model, or as interference/contact when fit and friction matter. The type name
alone does not invent stiffness, friction, strength, or tolerance values.

## Native response evaluation

`evaluate_physical_connections_rphysicalconnectionresponsebatch(...)` sends a
batch of relative states to the C++17 kernel. States are expressed in connector
A's local frame, and the returned wrench acts on component B in that frame.
The result includes force, torque, contact activation, and tensile/shear/torque
utilization. The backend is a constitutive response kernel; it does not perform
time integration, rigid-body solving, collision detection, or finite-element
meshing.

```python
state = cad.PhysicalConnectionState(
    "shelf_tenon",
    relative_translation=(0.002, 0.0, 0.0),
    relative_rotation=(0.0, 0.0, 0.0),
)
batch = cad.evaluate_physical_connections_rphysicalconnectionresponsebatch(
    layer, (state,)
)
print(batch.responses[0].to_dict())
```

The layer can be persisted independently of the existing model graph:

```python
cad.export_physical_connection_layer_json_rpath(layer, "connections.json")
reloaded = cad.import_physical_connection_layer_json_rphysicalconnectionlayer(
    "connections.json"
)
```

`ConnectionRegion` may still annotate where a reduced connection acts. When a
downstream continuum solver needs distributed traction over actual faces, use
`cadflow.simulation` instead; it exports stable face references, BREP geometry,
materials, surface laws, assembly transforms, and native gap evidence. See
[`surface-contact-simulation.md`](surface-contact-simulation.md). Neither layer
infers physical parameters from unannotated geometry.
