"""Material definitions for the compact reducer."""

from __future__ import annotations

import cadflow as cad


@cad.requires_session
def make_reducer_materials_rdict() -> dict[str, cad.Material]:
    """Create the small set of reusable material records for the assembly."""

    materials = {
        "housing": cad.make_material_rmaterial(
            material_id="hard_anodized_aluminum",
            name="Hard anodized aluminum",
            density=2.70e-6,
            density_unit="kg/mm^3",
            color=(0.26, 0.28, 0.30),
        ),
        "carrier": cad.make_material_rmaterial(
            material_id="aluminum_7075",
            name="7075 aluminum carrier",
            density=2.81e-6,
            density_unit="kg/mm^3",
            color=(0.48, 0.50, 0.52),
        ),
        "gear": cad.make_material_rmaterial(
            material_id="case_hardened_steel",
            name="Case hardened gear steel",
            density=7.85e-6,
            density_unit="kg/mm^3",
            color=(0.68, 0.70, 0.72),
        ),
        "shaft": cad.make_material_rmaterial(
            material_id="tempered_shaft_steel",
            name="Tempered shaft steel",
            density=7.85e-6,
            density_unit="kg/mm^3",
            color=(0.55, 0.57, 0.60),
        ),
    }
    print("materials: " + ",".join(material.material_id for material in materials.values()))
    return materials
