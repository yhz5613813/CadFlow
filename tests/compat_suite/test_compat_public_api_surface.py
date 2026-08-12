"""Tests for stable public API surface.

The package may add a small number of necessary new APIs for graph/session and
serialization, but internal implementation modules should not be advertised from
the top-level namespace.
"""

import json
import subprocess
import sys
import unittest


class TestPublicApiSurface(unittest.TestCase):
    def test_internal_modules_not_in___all__(self):
        import cadflow as cad

        self.assertNotIn("tracking", cad.__all__)
        self.assertNotIn("autotag", cad.__all__)
        self.assertIn("topology", cad.__all__)
        self.assertNotIn("graph", cad.__all__)
        self.assertNotIn("serializer", cad.__all__)

    def test_only_necessary_new_top_level_apis_are_present(self):
        code = """
import json
import cadflow as cad
print(json.dumps({
  'has_tracking': hasattr(cad, 'tracking'),
  'has_autotag': hasattr(cad, 'autotag'),
  'has_topology': hasattr(cad, 'topology'),
  'has_graph_module': hasattr(cad, 'graph'),
  'has_serializer_module': hasattr(cad, 'serializer'),
  'has_graph_session': hasattr(cad, 'GraphSession'),
  'has_export_graph_json': hasattr(cad, 'export_graph_json'),
  'has_import_graph_json': hasattr(cad, 'import_graph_json'),
  'has_replay_graph': hasattr(cad, 'replay_graph'),
  'has_apply_tag': hasattr(cad, 'apply_tag'),
  'has_list_tags': hasattr(cad, 'list_tags'),
  'has_set_tag': hasattr(cad, 'set_tag'),
}))
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)

        self.assertFalse(payload["has_tracking"])
        self.assertFalse(payload["has_autotag"])
        self.assertTrue(payload["has_topology"])
        self.assertFalse(payload["has_graph_module"])
        self.assertFalse(payload["has_serializer_module"])
        self.assertTrue(payload["has_graph_session"])
        self.assertTrue(payload["has_export_graph_json"])
        self.assertTrue(payload["has_import_graph_json"])
        self.assertTrue(payload["has_replay_graph"])
        self.assertTrue(payload["has_apply_tag"])
        self.assertTrue(payload["has_list_tags"])
        self.assertFalse(payload["has_set_tag"])

    def test_canonical_tagging_exports(self):
        import cadflow as cad
        from cadflow import operations, tagging

        expected = {
            "apply_tag_rselection": operations.apply_tag_rselection,
            "explain_tag": operations.explain_tag,
            "LineageDerivation": tagging.LineageDerivation,
            "LineagePolicy": tagging.LineagePolicy,
            "TagAttachment": tagging.TagAttachment,
            "TagBinding": tagging.TagBinding,
            "TagBindingScope": tagging.TagBindingScope,
            "TagCertainty": tagging.TagCertainty,
            "TagEvidence": tagging.TagEvidence,
            "TagEvidenceKind": tagging.TagEvidenceKind,
            "TagLifecycle": tagging.TagLifecycle,
            "TagLineageWitness": tagging.TagLineageWitness,
            "TagProducer": tagging.TagProducer,
            "TagProducerKind": tagging.TagProducerKind,
            "TagPropagation": tagging.TagPropagation,
            "TagScope": tagging.TagScope,
            "TagTarget": tagging.TagTarget,
            "TagTargetKind": tagging.TagTargetKind,
            "TopologyPropagation": tagging.TopologyPropagation,
        }

        for name, implementation in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, cad.__all__)
                self.assertIs(getattr(cad, name), implementation)

    def test_tracking_policy_is_public(self):
        import cadflow as cad
        from cadflow.tracking import TrackingPolicy

        self.assertIn("TrackingPolicy", cad.__all__)
        self.assertIs(cad.TrackingPolicy, TrackingPolicy)
