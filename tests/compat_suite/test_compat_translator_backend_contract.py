"""Contract tests shared by translator backends."""

from __future__ import annotations

import importlib
from pathlib import Path
import unittest

from cadflow.serializer import CANONICAL_OP_SET
from cadflow.translator.base import BaseTranslator
from cadflow.translator.types import SupportLevel


class TestTranslatorBackendContract(unittest.TestCase):
    def test_backend_packages_have_required_modules(self):
        translator_root = (
            Path(__file__).resolve().parents[2]
            / "python"
            / "cadflow"
            / "_engine"
            / "exchange"
            / "translators"
        )
        backend_dirs = sorted(translator_root.glob("*_translator"))
        self.assertTrue(backend_dirs)

        for backend_dir in backend_dirs:
            for filename in (
                "__init__.py",
                "api.py",
                "translator.py",
                "capabilities.py",
            ):
                self.assertTrue(
                    (backend_dir / filename).is_file(),
                    f"{backend_dir.name} is missing required {filename}",
                )

    def test_backend_public_exports_and_capabilities_are_valid(self):
        from cadflow import translator

        for backend_package_name in translator.__all__:
            backend = importlib.import_module(
                f"cadflow.translator.{backend_package_name}"
            )
            for exported_name in backend.__all__:
                self.assertTrue(hasattr(backend, exported_name))

            capabilities = backend.CAPABILITIES
            expected_backend_name = backend_package_name.removesuffix("_translator")
            self.assertEqual(capabilities.backend_id, expected_backend_name)
            self.assertEqual(
                set(capabilities.operations), set(CANONICAL_OP_SET)
            )
            for op, capability in capabilities.operations.items():
                if capability.level is SupportLevel.UNSUPPORTED:
                    self.assertTrue(capability.reason, op)

            translator_class = getattr(
                backend, f"{capabilities.display_name}Translator"
            )
            self.assertTrue(issubclass(translator_class, BaseTranslator))

if __name__ == "__main__":
    unittest.main()
