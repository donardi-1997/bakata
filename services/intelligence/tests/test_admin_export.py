import json
import unittest
from intelligence.admin_export import fixture_snapshot


class AdminExportTests(unittest.TestCase):
    def test_versioned_synthetic_snapshot(self):
        data = fixture_snapshot()
        self.assertEqual(data["schema"], "bakata-intelligence-preview-v1")
        self.assertEqual(data["mode"], "fixture")
        self.assertEqual(len(data["rows"]), 2)
        ready, incomplete = data["rows"]
        self.assertEqual(ready["score_bp"], 7777)
        self.assertEqual(ready["status"], "review-ready")
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertIsNone(incomplete["score_bp"])
        self.assertIsNone(incomplete["price_minor"])
        self.assertEqual(json.loads(json.dumps(data)), data)
