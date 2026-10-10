"""Corrupt copies of observed selftest CSVs; never alters frozen archives."""
from pathlib import Path
import csv
import gzip
import json
import shutil
import sys
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import diagnostic_launch as d


class AcceptanceChecks(unittest.TestCase):
    def fixture(self, mode='resource'):
        source = d.S1 / 'artifacts/diagnostics/engineering_cli_01' / mode
        root = d.S1 / 'artifacts/diagnostics/test_fixtures' / uuid.uuid4().hex
        root.mkdir(parents=True)
        for path in (source / 'R6').iterdir():
            if path.name.endswith('.csv.gz'):
                with gzip.open(path, 'rb') as f:
                    (root / path.name[:-3]).write_bytes(f.read())
            elif path.name in ('process.json', 'run_receipt.json', 'latency_summary.json', 'config.json'):
                shutil.copyfile(path, root / path.name)
        files = {k: d.bind(source / 'input' / name) for k, name in
                 [('cache', 'cache.bin'), ('expected', 'cache.expected.bin'), ('meta', 'cache.meta.json')]}
        receipt = d.gate.load(root / 'run_receipt.json')
        return root, files, receipt

    def accept(self, fixture, mode='resource'):
        root, files, receipt = fixture
        return d.validate_run(root, files, mode, 'R6', receipt['config_sha'], receipt['binary_sha'], engineering=True)

    def modify(self, path, change):
        with path.open(encoding='utf8', newline='') as f:
            r = csv.DictReader(f)
            fields, rows = r.fieldnames, list(r)
        change(rows)
        with path.open('w', encoding='utf8', newline='') as f:
            w = csv.DictWriter(f, fields)
            w.writeheader()
            w.writerows(rows)

    def test_actual_selftest_records_accepted_in_each_independent_mode(self):
        for mode in ('resource', 'latency'):
            self.assertEqual(self.accept(self.fixture(mode), mode)['API_samples'], 48)

    def test_missing_api_rejected(self):
        fixture = self.fixture()
        self.modify(fixture[0] / 'latency.csv', lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, 'identity/shape'):
            self.accept(fixture)

    def test_duplicate_api_rejected(self):
        fixture = self.fixture()
        self.modify(fixture[0] / 'latency.csv', lambda rows: rows[1].update(API_ordinal='1'))
        with self.assertRaisesRegex(ValueError, 'schedule/ordinal'):
            self.accept(fixture)

    def test_mixed_binary_identity_rejected(self):
        fixture = self.fixture()
        self.modify(fixture[0] / 'latency.csv', lambda rows: rows[1].update(binary_sha='0' * 64))
        with self.assertRaisesRegex(ValueError, 'identity/shape'):
            self.accept(fixture)

    def test_resource_output_release_violation_rejected(self):
        fixture = self.fixture()
        self.modify(fixture[0] / 'resource.csv', lambda rows: rows[-1].update(output_released='false'))
        with self.assertRaisesRegex(ValueError, 'dedup/output release'):
            self.accept(fixture)

    def test_failed_process_is_preserved_and_rejected(self):
        fixture = self.fixture()
        path = fixture[0] / 'process.json'
        doc = d.gate.load(path)
        doc['exit_code'] = 9
        path.write_text(json.dumps(doc), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'actual child failed'):
            self.accept(fixture)
        self.assertEqual(d.gate.load(path)['exit_code'], 9)

    def test_quantile_mismatch_rejected(self):
        fixture = self.fixture()
        path = fixture[0] / 'latency_summary.json'
        doc = d.gate.load(path)
        doc['p99'] = doc['max'] * 10
        path.write_text(json.dumps(doc), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'quantile reconciliation'):
            self.accept(fixture)


if __name__ == '__main__':
    unittest.main()
