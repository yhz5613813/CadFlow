"""TDD coverage for the OCP-native primitive solid slice."""

from __future__ import annotations

import unittest
import cadflow as cad


class TestOcpPrimitiveBuilders(unittest.TestCase):
    def test_kernel_ocp_builders_module_exposes_core_solid_builders(self):
        from cadflow.kernel.ocp_builders import (
            make_box_solid,
            make_cone_solid,
            make_cylinder_solid,
            make_sphere_solid,
        )

        box = cad.Solid(make_box_solid((0.0, 0.0, 0.0), 1.0, 2.0, 3.0))
        cylinder = cad.Solid(
            make_cylinder_solid((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0, 2.0)
        )
        cone = cad.Solid(
            make_cone_solid((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0, 0.5, 2.0)
        )
        sphere = cad.Solid(make_sphere_solid((1.0, 2.0, 3.0), 1.5))

        self.assertAlmostEqual(box.get_volume(), 6.0, places=5)
        self.assertGreater(cylinder.get_volume(), 0.0)
        self.assertGreater(cone.get_volume(), 0.0)
        self.assertGreater(sphere.get_volume(), 0.0)

    def test_make_box_rsolid_uses_ocp_wrapped_storage(self):
        solid = cad.make_box_rsolid(1.0, 2.0, 3.0)
        self.assertIsInstance(solid, cad.Solid)
        self.assertTrue(hasattr(solid, "wrapped"))
        self.assertFalse(hasattr(solid, "cq_solid"))
        self.assertAlmostEqual(solid.get_volume(), 6.0, places=5)

    def test_make_cylinder_rsolid_uses_ocp_wrapped_storage(self):
        solid = cad.make_cylinder_rsolid(1.0, 2.0)
        self.assertIsInstance(solid, cad.Solid)
        self.assertTrue(hasattr(solid, "wrapped"))
        self.assertFalse(hasattr(solid, "cq_solid"))
        self.assertGreater(solid.get_volume(), 0.0)

    def test_make_cone_rsolid_uses_ocp_wrapped_storage(self):
        solid = cad.make_cone_rsolid(1.0, 2.0, top_radius=0.5)
        self.assertIsInstance(solid, cad.Solid)
        self.assertTrue(hasattr(solid, "wrapped"))
        self.assertFalse(hasattr(solid, "cq_solid"))
        self.assertGreater(solid.get_volume(), 0.0)

    def test_make_sphere_rsolid_uses_ocp_wrapped_storage(self):
        solid = cad.make_sphere_rsolid(1.5, center=(1.0, 2.0, 3.0))
        self.assertIsInstance(solid, cad.Solid)
        self.assertTrue(hasattr(solid, "wrapped"))
        self.assertFalse(hasattr(solid, "cq_solid"))
        self.assertGreater(solid.get_volume(), 0.0)


if __name__ == "__main__":
    unittest.main()
