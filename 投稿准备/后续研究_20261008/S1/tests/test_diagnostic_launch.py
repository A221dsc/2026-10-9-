"""Entry and accounting regressions; fixtures contain no measured performance."""
import importlib.util
import sys
import uuid
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.find_spec('diagnostic_launch')
diag = __import__('diagnostic_launch') if spec else None


class DiagnosticChecks(unittest.TestCase):
    def entry(self):
        self.assertIsNotNone(diag, 'independent diagnostic entry is missing')
        return diag

    def test_exact_registered_matrices(self):
        d = self.entry()
        for mode in ('resource', 'latency'):
            cells = d.cells(mode)
            self.assertEqual(len(cells), 490)
            self.assertEqual(len(set(cells)), 490)
            self.assertEqual({x[2] for x in cells}, set(d.METHODS))
        mechanism = d.cells('mechanism')
        self.assertEqual(len(mechanism), 18)
        self.assertNotIn('Original', {x[2] for x in mechanism})
        with self.assertRaises(ValueError):
            d.cells('native')

    def test_cleanup_exempt_from_epoch_quota_but_counted(self):
        d = self.entry()
        events = [{'type': 'promotion', 'epoch': '8', 'slot': '0', 'n': '128'},
                  {'type': 'scheduled', 'epoch': '8', 'slot': '1', 'n': '128'},
                  {'type': 'cleanup', 'epoch': '8', 'slot': '2', 'n': '0'},
                  {'type': 'cleanup', 'epoch': '8', 'slot': '3', 'n': '0'}]
        d.check_event_counts(events, {'promotions': '1', 'scheduled_demotions': '1',
                                     'cleanup_demotions': '2', 'total_demotions': '3'})
        with self.assertRaises(ValueError):
            d.check_event_counts(events + [events[0]], {'promotions': '2',
                'scheduled_demotions': '1', 'cleanup_demotions': '2', 'total_demotions': '3'})
        with self.assertRaises(ValueError):
            d.check_event_counts(events, {'promotions': '1', 'scheduled_demotions': '1',
                'cleanup_demotions': '2', 'total_demotions': '2'})

    def test_event_records_cannot_be_dropped(self):
        d = self.entry()
        with self.assertRaises(ValueError):
            d.check_event_counts([], {'promotions': '1', 'scheduled_demotions': '0',
                                      'cleanup_demotions': '0', 'total_demotions': '0'})

    def test_quantiles_are_linear_iqr_is_not_ci(self):
        d = self.entry()
        result = d.distribution([0, 10, 20, 30])
        for k, v in {'count': 4, 'p50': 15.0, 'p95': 28.5, 'p99': 29.7, 'max': 30}.items():
            self.assertAlmostEqual(result[k], v)
        self.assertEqual(d.distribution([])['count'], 0)

    def test_lossless_archive_and_failure_retention(self):
        d = self.entry()
        root = TOOLS.parent / 'artifacts/diagnostics/test_fixtures' / uuid.uuid4().hex
        root.mkdir(parents=True)
        if True:
            path = root / 'latency.csv'
            payload = b'API,ns\ninsert,10\n'
            path.write_bytes(payload)
            receipt = d.archive_csv(path)
            self.assertEqual(d.read_archive(root / 'latency.csv.gz'), payload)
            self.assertEqual(receipt['raw_bytes'], len(payload))
            self.assertFalse(path.exists())
            # A pre-existing archive is an actual blocker, never overwritten.
            path.write_bytes(b'failed attempt retained')
            with self.assertRaises(FileExistsError):
                d.archive_csv(path)
            self.assertEqual(path.read_bytes(), b'failed attempt retained')

    def test_completed_resume_requires_external_binding(self):
        d = self.entry()
        root = TOOLS.parent / 'artifacts/diagnostics/test_fixtures' / uuid.uuid4().hex
        root.mkdir(parents=True)
        if True:
            path = root / 'result.json'
            path.write_bytes(b'original')
            import hashlib
            binding = {'path': str(path), 'sha256': hashlib.sha256(b'original').hexdigest()}
            d.check_binding(binding)
            path.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                d.check_binding(binding)

    def test_native_mode_and_engineering_results_cannot_enter_formal_gate(self):
        d = self.entry()
        for mode, engineering in [('native', False), ('resource', True), ('latency', True)]:
            with self.assertRaises(ValueError):
                d.check_mode({'measurement_mode': mode, 'engineering_only': engineering}, 'resource')


if __name__ == '__main__':
    unittest.main()
