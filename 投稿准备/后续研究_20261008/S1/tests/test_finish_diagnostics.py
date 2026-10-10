import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
entry = __import__('finish_diagnostics') if importlib.util.find_spec('finish_diagnostics') else None


class SequenceChecks(unittest.TestCase):
    def tool(self):
        self.assertIsNotNone(entry, 'automatic diagnostic sequence is missing')
        return entry

    def test_actual_success_and_complete_matrix_required(self):
        self.tool().check_completion({'exit_code': 0, 'actual_exit_observed': True},
            {'status': 'PASS', 'mode': 'resource', 'actual_completed': 490, 'FAIL': 0}, 'resource', 490)

    def test_nonzero_or_unobserved_outer_cannot_advance(self):
        d = self.tool()
        matrix = {'status': 'PASS', 'mode': 'resource', 'actual_completed': 490, 'FAIL': 0}
        for proc in ({'exit_code': 1, 'actual_exit_observed': True},
                     {'exit_code': 0, 'actual_exit_observed': False}):
            with self.assertRaises(ValueError):
                d.check_completion(proc, matrix, 'resource', 490)

    def test_incomplete_or_wrong_mode_blocks_next_batch(self):
        d = self.tool()
        proc = {'exit_code': 0, 'actual_exit_observed': True}
        for doc in ({'status': 'PASS', 'mode': 'resource', 'actual_completed': 489, 'FAIL': 0},
                    {'status': 'PASS', 'mode': 'latency', 'actual_completed': 490, 'FAIL': 0},
                    {'status': 'PASS', 'mode': 'resource', 'actual_completed': 490, 'FAIL': 1}):
            with self.assertRaises(ValueError):
                d.check_completion(proc, doc, 'resource', 490)


if __name__ == '__main__':
    unittest.main()
