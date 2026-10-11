"""Recovery is structural prefix reuse, never a performance-based retry."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import diagnostic_launch as d

ROOT = Path(__file__).resolve().parents[1] / 'artifacts/diagnostics/LATENCY_20261011_01'


class RecoveryChecks(unittest.TestCase):
    def tool(self):
        self.assertTrue(hasattr(d, 'verified_prefix'), 'sealed prefix recovery is missing')
        return d.verified_prefix

    def test_actual_sealed_prefix_has_exact_order_and_no_replay(self):
        records, seals = self.tool()(ROOT, 'latency')
        self.assertEqual(len(records), 23)
        self.assertEqual([tuple(d.gate.load(s['path'])['cell']) for s in seals], d.cells('latency')[:23])
        self.assertEqual(sum(r['API_samples'] for r in records), 23 * 525312)

    def test_gap_or_reordering_is_a_blocker(self):
        self.tool()
        original = d.gate.load
        def bad(path):
            doc = original(path)
            if Path(path).name == 'START.json':
                doc['cells'][0], doc['cells'][1] = doc['cells'][1], doc['cells'][0]
            return doc
        with patch.object(d.gate, 'load', side_effect=bad), self.assertRaises(ValueError):
            d.verified_prefix(ROOT, 'latency')

    def test_unsealed_or_tampered_child_is_a_blocker(self):
        self.tool()
        with patch.object(d, 'check_binding', side_effect=ValueError('tampered sealed record')):
            with self.assertRaises(ValueError):
                d.verified_prefix(ROOT, 'latency')

    def test_wrong_mode_is_a_blocker(self):
        with self.assertRaises(ValueError):
            self.tool()(ROOT, 'resource')


if __name__ == '__main__':
    unittest.main()
