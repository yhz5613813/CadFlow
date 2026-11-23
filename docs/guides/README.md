# Engineering Guides

- [Physical Connections](physical-connections.md): declare manufacturing/interface connections separately from kinematic assembly constraints and evaluate reduced-order native responses.
- [STEP BREP Reverse Engineering](step-brep-reverse-engineering.md): full workflow from STEP inspection, geometric fingerprint analysis, feature-tree inference, and candidate iteration to geometric point-set, BREP topology, parameter history, and model replay acceptance.
- [Class-A Surface Construction](class-a-surfacing.md): G0/G1/G2 blends between faces, curvature-continuous fillets, exact Coons boundary filling, and why OCCT plate filling cannot deliver G2.
- [Surface Analysis](surface-analysis.md): G0/G1/G2 boundary continuity, exact curvature sampling, surface-definition diagnostics, and zebra/isophote/curvature inspection images.
- [DXF machining-profile export](dxf-profile-export.md): export one selected planar face as closed outer and inner 2D machining contours.

The corresponding runnable module and examples live in:

```text
python/cadflow/inspect/brep/
```
