# DXF machining-profile export

CadFlow can export the ordered boundary loops of one planar BREP face as a 2D
DXF machining profile. This is a face-boundary export, not a hidden-line view of
the complete solid: side walls, rear edges, annotations, and dimensions are not
added.

## Select the machining face

Select the planar face whose outer edge and holes define the required stock or
tool path. For example, this exports the top face of a drilled plate:

```python
import cadflow as cad

with cad.Model() as model:
    plate = model.box(80, 50, 8)
    drill = model.translate(model.cylinder(5, 8), 40, 25, 0)
    part = model.cut(plate, drill)
    top = max(model.faces(part), key=lambda face: face.center_of_mass[2])
    top.export_dxf("plate-profile.dxf", tolerance=0.01)
```

The selected value must be exactly one planar `Shape` of kind `face`. Passing a
solid or a cylindrical, conical, or freeform face fails instead of silently
producing a misleading drawing.

## Output contract

- The DXF version is ASCII AC1015 (AutoCAD 2000).
- Coordinates use the selected plane's local `(u, v)` axes and CadFlow's
  canonical millimeter unit.
- The outer boundary is a closed `LWPOLYLINE` on `PROFILE_OUTER`.
- Every hole or island boundary is a closed `LWPOLYLINE` on `PROFILE_INNER`.
- Lines remain exact line segments. Circular edges remain exact through DXF
  bulge values and are split into arcs of at most 90 degrees.
- Other bounded curves are adaptively converted to line segments using the
  requested chord-tolerance target. The default target is `0.01` mm.

The target directory must already exist and the filename must end in `.dxf`.
CadFlow writes through a temporary sibling and only replaces the target after a
complete file has been produced.

## Manufacturing checks

Before machining, reopen the DXF in the downstream CAM/CAD application and
check the unit, loop count, overall dimensions, hole diameters, and curve
tolerance. A successful export proves the selected face boundary was encoded;
it does not choose the correct manufacturing face for the user.
