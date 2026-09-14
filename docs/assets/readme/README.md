# README figure sources

These documentation figures were reviewed on 2026-09-05 against CadFlow
[`fb0e45d`](https://github.com/yhz5613813/CadFlow/tree/fb0e45d129645cbb21eb5cd715d200f6127e978a).
They describe the implemented SDK and its optional experimental Agent DSL, not
a bundled trained model or an autonomous-agent benchmark.

| Figure | Purpose | Editable source |
| --- | --- | --- |
| [Case hero](cadflow-hero.svg) | External caller, native geometry, feedback, and artifacts | [SVG](source/cadflow-hero.svg) |
| [Mechanism overview](cadflow-overview.svg) | Public API, typed graphs, and native execution | [SVG](source/cadflow-overview.svg) |
| [Native boundary](cadflow-native-boundary.svg) | Python workflows and session-owned native geometry | [SVG](source/cadflow-native-boundary.svg) |
| [Agent DSL](cadflow-agent-dsl.svg) | Revisioned state, bounded feedback, and preview | [SVG](source/cadflow-agent-dsl.svg) |
| [Geometry feedback](cadflow-geometry-feedback.svg) | Quick-start plate and actual inspection data | [SVG](source/cadflow-geometry-feedback.svg) |
| [Model gallery](cadflow-examples.svg) | Real example geometry | [SVG](source/cadflow-examples.svg) |

## Formats and editing

The README-facing SVGs outline their text for consistent rendering without
installed fonts. Their CAD images are embedded PNGs; there are no remote image,
font, script, or stylesheet dependencies. Files in `source/` retain editable text
and vector layout, using Comic Sans MS and Menlo. Font files are not distributed.
The English and Chinese READMEs share the same approved figures and provide
localized captions and alternative text.

## Geometry provenance

The CAD images are conventional VTK renders of geometry exported by the public
CadFlow API. No generative image model was used to invent the mechanical shapes.

- **Mounting plate:** the [README quick start](../../../README.md#-quick-start),
  with design units in millimeters: `box(80, 50, 8)` minus a radius-6 cylinder
  translated to `(20, 25, -2)`. The native run returned volume
  `31095.221315766135 mm³`, 7 faces, 15 edges, 10 vertices, and 1 solid.
- **Reinforced bracket:**
  [`examples/cadflow_complex_mounting_bracket.py`](../../../examples/cadflow_complex_mounting_bracket.py).
  The generated shape has 1 solid and 50 faces; STEP reimport was checked.
- **Planetary reducer:**
  [`examples/16_compact_two_stage_planetary_reducer/`](../../../examples/16_compact_two_stage_planetary_reducer/).
  The source has 25 top-level components. Display-only translations separate
  the housing and axial groups; display colors distinguish components without
  changing source material records. Original assembly geometry is unchanged.
- **Ceramic cup:**
  [`examples/cadflow_ceramic_cup.py`](../../../examples/cadflow_ceramic_cup.py).
  This is an 18-solid composition, not a fused single manufacturing solid or a
  spline-surface demonstration.

The isolated rendering environment used macOS arm64, Python 3.13.15,
CadFlow 0.2.0, `cadquery-ocp==7.9.3.1`, and VTK 9.5.2. The figures' inspection
values are local geometry observations, not performance or generation scores.
Basic `validate()` reports do not establish manufacturability, collision
clearance, or numerical-simulation correctness. DXF labels refer to selected
planar-face profiles. Strict replay uses Model JSON; Scene packages do not
necessarily embed a source model.

The approved figures, editable SVGs, and demo media listed below are included here. Large CAD
exports, local runtime environments, rough layout candidates, and review-only
PDF/PNG duplicates are intentionally outside this documentation change.

## Demo videos

Updated on 2026-09-14 from the author's existing local CadFlow model viewers.
Both demonstrations were re-recorded at 1920 × 1080 with the original camera
and motion sequences. The videos contain no added titles, captions, footnotes,
or progress bar. Printed labels on the phone model are hidden for presentation.
The underlying model geometry and assembly motion are otherwise unchanged.

| Model | Full video | Animated preview | Duration |
| --- | --- | --- | --- |
| AUREL HAND R1 | [MP4](aurel-hand-r1.mp4) | [GIF](aurel-hand-r1.gif) | 25.8 s |
| AUREL ONE | [MP4](aurel-one.mp4) | [GIF](aurel-one.gif) | 27.2 s |

The MP4 files use H.264 at 30 fps. Looping GIF previews use the complete video
timeline at 640 × 360, 8 fps. The hand video shows joint motion and grasping
poses; the phone video shows the exterior, internal layout, exploded view,
and motherboard details. These are model demonstrations, not manufacturing
or numerical-simulation validation.

## CadFlow Studio phone workflow

Recorded on 2026-09-14 in the separate CadFlow Studio application using the pi
harness and GPT-6. [Full video](cadflow-studio-phone.mp4),
[preview frame](cadflow-studio-phone.png). Duration: 133 seconds, with Chinese
chapter captions and no audio. The 1280 × 720 browser capture uses a variable
capture rate (approximately 1–5 fps); the edited output is 1920 × 1080 H.264
at 30 fps. Long agent waits are omitted, and title cards are added. The preview
is an unaltered frame from the finished video at 114.2 seconds.

The recording demonstrates actual GLB edits: rear-cover color `#2563EB`,
roughness `0.48`, metallicity `0.15`; six camera rings/ring lips in `#D4AF37`,
metallicity `0.90`, roughness `0.20`; then rear-cover opacity `0.22` with
`alphaMode: BLEND`. It also shows component visibility, viewport rotation,
side-by-side comparison, and saved verification reports.

Independent checks confirmed the intended material values and changed-node
sets for all three versions. Geometry/texture binary chunks, accessors,
buffer views, primitive geometry references, and node transforms were
unchanged. The original phone file was preserved byte for byte. This is a
material-editing and application-workflow demonstration, not a CAD/BREP
rebuild or a manufacturing-validation result.

Video SHA-256: `afe00140409aeaafb0083e970dc49e42961d1584c3d357d30c0f75b767da47fd`.
