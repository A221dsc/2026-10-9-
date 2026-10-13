import gzip
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'prepare_nasa.py'

class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file(), 'S2 timestamp preparation tool is not implemented')
        spec = importlib.util.spec_from_file_location('prepare_nasa', TOOL)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'artifacts' / 'diagnostics')
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def archive(self, content):
        path = self.dir / 'mini.gz'
        path.write_bytes(gzip.compress(content, mtime=0))
        return path

    def line(self, timestamp):
        return b'opaque - - [' + timestamp.encode('ascii') + b'] opaque\n'

    def project(self, content, exclusion=None):
        archive = self.archive(content)
        target = self.dir / 'projection.bin'
        stats = self.m.project_gzip(archive, target, exclusion=exclusion)
        raw = target.read_bytes()
        head = struct.unpack('<8sQQ', raw[:24])
        records = list(struct.iter_unpack('<QQ', raw[24:]))
        return stats, head, records

    def test_duplicate_records_preserve_original_identity(self):
        stats, head, records = self.project(self.line('01/Jul/1995:00:00:01 -0400') * 2 + self.line('01/Jul/1995:00:00:03 -0400'))
        self.assertEqual(head, (b'S2TIME01', 3, 3))
        self.assertEqual(records, [(1, 1), (1, 2), (3, 3)])
        self.assertEqual(stats['unique_timestamps'], 2)
        self.assertEqual(stats['stride'], 4)
        self.assertEqual(stats['adjacent_time_decreases'], 0)
        self.assertFalse(stats['hosts_and_request_paths_analyzed'])

    def test_equivalent_timezone_offsets_have_equal_time(self):
        self.assertEqual(self.m.parse_timestamp(self.line('01/Jul/1995:04:00:01 +0000')), 1)

    def test_invalid_calendar_date_fails(self):
        with self.assertRaisesRegex(ValueError, 'date|day'):
            self.m.parse_timestamp(self.line('31/Feb/1995:00:00:01 -0400'))

    def test_invalid_timezone_fails(self):
        with self.assertRaisesRegex(ValueError, 'timezone'):
            self.m.parse_timestamp(self.line('01/Jul/1995:00:00:01 +2460'))

    def test_exact_final_truncation_excluded_without_inventing_time(self):
        stats, head, records = self.project(self.line('01/Jul/1995:00:00:01 -0400') + b'fragment', {'ordinal': 2, 'length_bytes': 8, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'})
        self.assertEqual(head, (b'S2TIME01', 1, 2))
        self.assertEqual(records, [(1, 1)])
        self.assertEqual(stats['excluded_lines'], [{'ordinal': 2, 'length_bytes': 8, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'}])

    def test_exclusion_cannot_be_nonfinal(self):
        with self.assertRaisesRegex(ValueError, 'final'):
            self.project(b'fragment' + b'\n' + self.line('01/Jul/1995:00:00:01 -0400'), {'ordinal': 1, 'length_bytes': 9, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'})

    def test_unknown_bad_line_fails(self):
        with self.assertRaisesRegex(ValueError, 'line 2'):
            self.project(self.line('01/Jul/1995:00:00:01 -0400') + b'unknown\n')

    def test_exclusion_with_wrong_length_fails(self):
        with self.assertRaisesRegex(ValueError, 'line 2'):
            self.project(self.line('01/Jul/1995:00:00:01 -0400') + b'bad', {'ordinal': 2, 'length_bytes': 8, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'})

    def test_decreasing_time_fails(self):
        with self.assertRaisesRegex(ValueError, 'decrease'):
            self.project(self.line('01/Jul/1995:00:00:02 -0400') + self.line('01/Jul/1995:00:00:01 -0400'))

    def test_out_of_domain_fails(self):
        with self.assertRaisesRegex(ValueError, 'domain'):
            self.project(self.line('01/Aug/1995:00:00:00 -0400'))

    def test_projection_overwrite_refused(self):
        archive = self.archive(self.line('01/Jul/1995:00:00:01 -0400'))
        target = self.dir / 'exists.bin'
        target.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            self.m.project_gzip(archive, target)
        self.assertEqual(target.read_bytes(), b'preserve')

    def test_output_directory_overwrite_refused(self):
        archive = self.archive(self.line('01/Jul/1995:00:00:01 -0400'))
        out = self.dir / 'out'
        out.mkdir()
        with self.assertRaises(FileExistsError):
            self.m.prepare_nasa(archive, out)

    def test_crc_corruption_fails(self):
        archive = self.archive(self.line('01/Jul/1995:00:00:01 -0400'))
        raw = bytearray(archive.read_bytes())
        raw[-8] ^= 1
        archive.write_bytes(raw)
        with self.assertRaises((gzip.BadGzipFile, OSError, EOFError)):
            self.m.project_gzip(archive, self.dir / 'projection.bin')

    def test_strict_real_source_rejects_mini_archive(self):
        archive = self.archive(self.line('01/Jul/1995:00:00:01 -0400'))
        with self.assertRaisesRegex(ValueError, 'archive identity'):
            self.m.prepare_nasa(archive, self.dir / 'strict_out')
        self.assertFalse((self.dir / 'strict_out').exists())

    def test_missing_expected_exclusion_fails(self):
        with self.assertRaisesRegex(ValueError, 'exclusion'):
            self.project(self.line('01/Jul/1995:00:00:01 -0400'), {'ordinal': 2, 'length_bytes': 8, 'reason': 'missing_timestamp_bracket_at_truncated_final_line'})

if __name__ == '__main__':
    unittest.main()
