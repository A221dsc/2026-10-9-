"""Reporting arithmetic and phase attribution without performance fixtures."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from report_diagnostics import paired_resources, mechanism_rows


class ReportChecks(unittest.TestCase):
    def test_resource_pairing_uses_same_seed_and_preserves_all_ten(self):
        rows = []
        values = {'R6': 125, 'M_LIST': 100, 'M_EVENT_16': 200,
                  'M_FIXED_2048': 500, 'M_NO_IDLE': 250}
        for seed in range(91001, 91011):
            for method, value in values.items():
                rows.append({'case_id': 'F05', 'seed': seed, 'method': method,
                             'persistent_final': value * seed, 'whole_peak': value * seed + seed})
        result = paired_resources(rows)
        event = next(r for r in result if r['reference'] == 'M_EVENT_16' and r['metric'] == 'persistent_final')
        self.assertEqual((event['median_ratio'], event['wins'], event['total'], event['IQR']), (.625, 10, 10, 0))
        baseline = next(r for r in result if r['reference'] == 'M_LIST' and r['metric'] == 'persistent_final')
        self.assertEqual((baseline['median_ratio'], baseline['wins']), (1.25, 0))

    def test_missing_seed_is_not_silently_dropped(self):
        rows = [{'case_id': 'F05', 'seed': 91001, 'method': m, 'persistent_final': 100, 'whole_peak': 100}
                for m in ('R6', 'M_LIST', 'M_EVENT_16', 'M_FIXED_2048', 'M_NO_IDLE')]
        with self.assertRaises(KeyError):
            paired_resources(rows)

    def test_phase_clock_uses_own_run_events_and_work_remains_na(self):
        record = {'raw': {'method': 'R6', 'seed': '93001'}, 'evidence_path': 'fixture_only',
                  'phases': [{'phase': 'A_hot', 'begin_unit': '0', 'end_unit': '256',
                              'phase_query_count': '0', 'online_ns': '1000'},
                             {'phase': 'idle1', 'begin_unit': '256', 'end_unit': '512',
                              'phase_query_count': '0', 'online_ns': '2000'}],
                  'resources': [{'snapshot_reason': 'phase', 'phase': '0', 'tree_buckets': '1',
                                 'persistent_requested_bytes': '100', 'whole_peak': '200'},
                                {'snapshot_reason': 'phase|final', 'phase': '1', 'tree_buckets': '0',
                                 'persistent_requested_bytes': '50', 'whole_peak': '200'}],
                  'conversion_events': [{'type': 'promotion', 'slot': '0', 'API_ordinal': '512'},
                                        {'type': 'scheduled', 'slot': '0', 'API_ordinal': '1024'}]}
        result = mechanism_rows([record])
        self.assertEqual([(r['tree_A'], r['tree_B'], r['promotions'], r['scheduled_demotions'])
                          for r in result], [(1, 0, 1, 0), (0, 0, 0, 1)])
        self.assertTrue(all(r['phase_avoidable_work'].startswith('NA') for r in result))


if __name__ == '__main__':
    unittest.main()
