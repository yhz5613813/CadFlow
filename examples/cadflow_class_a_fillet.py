"""Compare a circular fillet with a curvature-continuous (G2) smooth fillet.

Rounds every edge of a 12 mm cube with a 3 mm setback twice, once with OCCT's
circular fillet and once with ``Model.smooth_fillet``, measures the continuity
of every edge, and renders zebra stripes and mean curvature side by side.
Rendering requires Pillow.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import cadflow as cad
from cadflow import surface_analysis as sa


OUTPUT_DIR = Path("examples/out/cadflow_class_a_fillet")
VIEW = (-1.0, -0.8, -0.7)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with cad.Model() as model:
        cube = model.box(12.0, 12.0, 12.0)
        variants = {
            "circular": model.fillet(cube, 3.0),
            "smooth": model.smooth_fillet(cube, 3.0),
        }
        for name, shape in variants.items():
            levels = Counter(edge["level"] for edge in shape.continuity()["edges"])
            print(f"{name}: {dict(levels)}, issues: {shape.surface_quality()['issues']}")
            mesh = shape.curvature_mesh(0.01)
            sa.render_png(
                mesh, str(OUTPUT_DIR / f"{name}_zebra.png"), mode="zebra",
                view_direction=VIEW, size=700, stripes=40,
                stripe_axis=(0.35, -0.25, 1.0), face_outlines=False,
            )
            sa.render_png(
                mesh, str(OUTPUT_DIR / f"{name}_mean.png"), mode="mean",
                view_direction=VIEW, size=700,
            )
    print(f"renders written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
