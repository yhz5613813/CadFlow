# Text2CAD boiler workpiece

This artifact assembles local Text2CAD components into a detailed vertical
multi-tube fire-tube boiler. The hollow pressure boundary contains a
water-backed combustion chamber, horizontal furnace tube, two tube sheets,
18 fire tubes, a central uptake, six stays, steam riser ports, a dry-steam
collector, an upper smokebox, and a bored chimney.

External details include two safety valves, a main steam stop valve, feed check
and blowdown valves with handwheels, a siphon pressure gauge, two guarded sight
glasses, three water-level limiters, a fusible plug, manhole, handholes,
sampling cock, forced-draft burner, observation port, cleanout door, lifting
lugs, cladding bands, and four gusseted supports.

`boiler.step`, `boiler.stl`, `boiler.glb`, and `boiler.png` are the complete
workpiece. The `boiler_section.*` files are generated from the same pressure
core by removing a real three-dimensional quarter, exposing the furnace,
combustion chamber, tube bundle, tube sheets, smokebox, and chimney passage.

The model is intended for visual CAD and real-time preview. Its representative
4.5 mm wall is not a pressure-code calculation, and no thermal, combustion,
fluid, or structural simulation is claimed. Source attribution, assumptions,
component inventory, and measured validation are in `report.json`.
