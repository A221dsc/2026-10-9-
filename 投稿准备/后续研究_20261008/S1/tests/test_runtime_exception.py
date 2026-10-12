"""Explicit human exception is narrow and never admits native or changed assets."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import diagnostic_launch as d

APPROVAL = d.S1 / 'S1_运行环境例外批准_20261012.json'
PRIVATE = d.S1 / 'artifacts/diagnostics/RUNTIME_REVIEW_20261012_01/python/python.exe'
PREFIX = d.S1 / 'artifacts/diagnostics/LATENCY_20261011_01'


class RuntimeExceptionChecks(unittest.TestCase):
    def verifier(self):
        self.assertTrue(hasattr(d, 'verify_runtime_exception'), 'approved runtime exception gate missing')
        return d.verify_runtime_exception

    def test_actual_authorized_private_runtime_and_prefix(self):
        doc = self.verifier()(APPROVAL, 'latency', PRIVATE, PREFIX)
        self.assertEqual(doc['prefix_cells'], 23)
        self.assertEqual(doc['remaining_latency_cells'], 467)

    def test_no_native_resource_capacity_or_changed_path(self):
        f = self.verifier()
        for mode in ('native', 'resource', 'mechanism', 'capacity'):
            with self.assertRaises(ValueError):
                f(APPROVAL, mode, PRIVATE, PREFIX)
        with self.assertRaises(ValueError):
            f(APPROVAL, 'latency', Path(sys.executable).with_name('different.exe'), PREFIX)
        with self.assertRaises(ValueError):
            f(APPROVAL, 'latency', PRIVATE, PREFIX.with_name('different'))

    def test_pending_or_widened_authorization_is_rejected(self):
        f = self.verifier()
        original = d.gate.load
        for field, value in [('status', 'PENDING'), ('native_reruns', 1),
                             ('scope_modes', ['latency', 'cpu', 'native'])]:
            def altered(path, field=field, value=value):
                doc = original(path)
                if Path(path).resolve() == APPROVAL.resolve():
                    doc[field] = value
                return doc
            with patch.object(d.gate, 'load', side_effect=altered), self.assertRaises(ValueError):
                f(APPROVAL, 'latency', PRIVATE, PREFIX)

    def test_tampered_dependency_binding_stops_entry(self):
        f = self.verifier()
        with patch.object(d, 'check_binding', side_effect=ValueError('changed runtime dependency')):
            with self.assertRaises(ValueError):
                f(APPROVAL, 'latency', PRIVATE, PREFIX)


if __name__ == '__main__':
    unittest.main()
