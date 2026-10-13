import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'record_execution.py'

class RecordExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'artifacts' / 'diagnostics')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'tools').mkdir()
        (self.root / 'tests').mkdir()
        self.log = self.root / 'artifacts' / 'diagnostics' / 'TDD_PREPARE_NASA_20261013_01'
        self.log.mkdir(parents=True)
        self.tool = self.root / 'tools' / 'record_execution.py'
        self.tool.write_bytes(TOOL.read_bytes())
        self.marker = self.root / 'child_was_started.txt'
        (self.root / 'tests' / 'test_child.py').write_text("from pathlib import Path\nimport unittest\nclass Child(unittest.TestCase):\n    def test_marker(self):\n        Path(__file__).resolve().parents[1].joinpath('child_was_started.txt').write_text('started')\n", encoding='utf-8')
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def cli(self, label):
        return subprocess.run([sys.executable, '-B', str(self.tool), label], capture_output=True, env=self.env)

    def assert_collision(self, suffixes):
        label = 'GREEN_COLLISION'
        originals = {}
        for suffix in suffixes:
            path = self.log / (label + suffix)
            originals[path] = b'original evidence\x00\xff\r\n' + suffix.encode('ascii')
            path.write_bytes(originals[path])
        result = self.cli(label)
        self.assertNotEqual(result.returncode, 0, 'duplicate evidence label must be rejected')
        self.assertFalse(self.marker.exists(), 'child process must not start before duplicate-label rejection')
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original, 'existing evidence must remain byte-for-byte intact')

    def test_duplicate_full_label_rejected_before_child_start(self):
        self.assert_collision(('.stdout.txt', '.stderr.txt', '.execution.json'))

    def test_stdout_only_collision_preserved_without_starting_child(self):
        self.assert_collision(('.stdout.txt',))

    def test_stderr_only_collision_preserved_without_starting_child(self):
        self.assert_collision(('.stderr.txt',))

    def test_receipt_only_collision_preserved_without_starting_child(self):
        self.assert_collision(('.execution.json',))

    def test_fresh_label_records_real_output_and_exit(self):
        result = self.cli('GREEN_FRESH')
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.marker.exists())
        receipt = json.loads((self.log / 'GREEN_FRESH.execution.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['exit_code'], 0)
        self.assertEqual(receipt['formal_runs'], 0)
        self.assertIn(b'Ran 1 test', (self.log / 'GREEN_FRESH.stderr.txt').read_bytes())
        snapshots = {path: path.read_bytes() for path in self.log.glob('GREEN_FRESH.*') if path.is_file()}
        self.marker.unlink()
        duplicate = self.cli('GREEN_FRESH')
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertFalse(self.marker.exists())
        self.assertEqual(snapshots, {path: path.read_bytes() for path in snapshots})

    def api_probe(self, command, label):
        code = "import runpy,sys; from pathlib import Path; sys.argv=[sys.argv[1], 'GREEN_IMPORT']; ns=runpy.run_path(sys.argv[0], run_name='probe'); ns['record_command'](" + repr(command) + ", " + repr(label) + ", Path(" + repr(str(self.root)) + "), Path(" + repr(str(self.log)) + "))"
        return subprocess.run([sys.executable, '-B', '-c', code, str(self.tool)], capture_output=True, env=self.env)

    def test_spawn_error_leaves_actual_failure_receipt(self):
        missing = str(self.root / 'nonexistent_program.exe')
        self.api_probe([missing], 'SPAWN_FAILED')
        receipt_path = self.log / 'SPAWN_FAILED.execution.json'
        self.assertTrue(receipt_path.is_file(), 'spawn failure must leave a truthful receipt')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        self.assertIsNone(receipt['exit_code'])
        self.assertEqual(receipt['status'], 'SPAWN_FAILED')
        self.assertEqual(receipt['spawn_error']['type'], 'FileNotFoundError')
        self.assertEqual(receipt['command_argv'], [missing])
        self.assertEqual((self.log / 'SPAWN_FAILED.stdout.txt').read_bytes(), b'')
        self.assertTrue((self.log / 'SPAWN_FAILED.stderr.txt').read_bytes())

    def test_atomic_attempt_reservation_blocks_child_before_any_outputs(self):
        (self.log / 'GREEN_RESERVED.attempt').mkdir()
        result = self.cli('GREEN_RESERVED')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.log / 'GREEN_RESERVED.stdout.txt').exists())
        self.assertFalse((self.log / 'GREEN_RESERVED.execution.json').exists())

if __name__ == '__main__':
    unittest.main()
