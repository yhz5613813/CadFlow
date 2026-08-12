# CadFlow Agent Instructions

Before changing or generating CAD geometry in this repository, read:

1. skills/cadflow-model-part/SKILL.md
2. skills/cadflow-model-part/references/public-api.md when an operation or
   signature is needed

Use the public Python frontend (cadflow.Model, cadflow.Shape, and, when
appropriate, cadflow.Graph) as the integration boundary. Keep part scripts
independent of cadflow._engine, OpenCascade/OCP objects, private handles, and
direct C++ library loading. Follow the skill's validation and export checklist,
and leave a reproducible script plus the queried geometry results for every
completed part task.
