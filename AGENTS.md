# CadFlow Agent Instructions

Before changing or generating CAD geometry in this repository, select the
skill matching the requested artifact and read its `SKILL.md`:

1. `skills/cadflow-model-part/SKILL.md` for rigid mechanical parts.
2. `skills/cadflow-flexible-model/SKILL.md` for static cloth, sheet, membrane,
   garment, or thin-shell mesh modeling.
3. `skills/cadflow-step-brep/SKILL.md` for STEP/BREP inspection, comparison, or
   reverse engineering.
4. `skills/cadflow-validate-export/SKILL.md` for final geometry/file/replay
   validation and checked exports.
5. `skills/cadflow-contact-simulation/SKILL.md` for face-level mechanical
   properties, distributed contact laws, FEA handoff, and simulation packages.

Read the relevant `references/` file when an operation signature or format
detail is needed. Use `import cadflow as cad` and the public Python frontend as
the integration boundary. Keep scripts independent of `cadflow._engine`,
OpenCascade/OCP objects, private handles, and direct C++ library loading.
Static flexible modeling is geometry-only: do not add motion, gravity,
collision, velocity, time integration, or XPBD code.
