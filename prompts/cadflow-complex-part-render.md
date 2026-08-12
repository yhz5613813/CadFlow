# CadFlow Complex Part Modeling Prompt

You are working in the CadFlow repository. Read and follow:

- AGENTS.md
- skills/cadflow-model-part/SKILL.md
- skills/cadflow-model-part/references/public-api.md

Use only CadFlow's public Python frontend for modeling. Do not import
cadflow._engine, OCP/OpenCascade objects, private shape handles, or the C++
library directly.

## Task

Create one parametric mechanical part: a reinforced L-shaped mounting bracket
with a horizontal base, a vertical back plate, two triangular side gussets, a
central cylindrical boss, four base mounting holes with counterbores, and two
horizontal holes through the back plate.

Use millimetres and this coordinate system:

- X is left-to-right across the bracket.
- Y is front-to-back; the back plate occupies the high-Y side.
- Z is vertical; the base starts at Z=0.
- The base envelope is 80 x 50 x 8 mm.
- The back plate is 80 x 8 x 55 mm, placed at Y=42 and overlapping the base
  between Z=4 and Z=8.
- Each gusset is an 8 mm wide triangular prism near one X side. Its Y-Z
  profile has vertices (8,4), (46,4), and (46,38), and it is extruded along X.
- The boss is a radius-14 mm cylinder, starts at Z=6, and is 14 mm high,
  centered at (X=40, Y=25).
- Base through holes have radius 3.2 mm at
  (X,Y) = (10,10), (70,10), (10,40), and (70,40). Extend each cutter beyond
  the base thickness.
- Base counterbores have radius 5.0 mm and depth 3.0 mm from the top face.
- The boss has a radius-5.0 mm through hole and a radius-8.0 mm, 3.5 mm deep
  counterbore from its top.
- Back-plate through holes have radius 4.0 mm at (X,Z) = (20,35) and
  (60,35). Rotate the default Z-axis cylinders so they pass through Y.

Build incrementally and retain named intermediate shapes. Use sequential
subtractive cuts for the four disjoint base holes and two back-plate holes.
Fuse only overlapping additive features. Query the final kind, volume, area,
bounding box, center of mass, and topology; assert that the final result has
one solid and an envelope close to X=0..80, Y=0..50, Z=0..59.

## Required Outputs

Write a reproducible script at:

    examples/cadflow_complex_mounting_bracket.py

Write all generated artifacts under:

    examples/out/cadflow_complex_mounting_bracket/

The script must create:

- complex_mounting_bracket.step
- complex_mounting_bracket.stl
- complex_mounting_bracket.png
- complex_mounting_bracket_metrics.json

Export STEP/STL from the final CadFlow Shape. After the Model context closes,
render the exported STEP with the public inspection API:

    from cadflow.inspect import brep
    brep.render_step_views_rpath(
        step_path=step_path,
        output_path=png_path,
        title="CadFlow reinforced mounting bracket",
    )

Do not use a private renderer or read the generated STEP back into the
modeling pipeline. Check that every output exists and has non-zero size, then
print the exact paths and validation metrics.
