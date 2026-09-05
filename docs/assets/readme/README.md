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

Only the approved figures and editable SVGs are included here. Large CAD
exports, local runtime environments, rough layout candidates, and review-only
PDF/PNG duplicates are intentionally outside this documentation change.
