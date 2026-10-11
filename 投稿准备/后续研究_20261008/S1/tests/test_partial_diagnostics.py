import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import report_diagnostics_partial as r


class PartialReportChecks(unittest.TestCase):
    def test_prefix_retains_source_path_for_latency_summary(self):
        self.assertTrue(hasattr(r, 'report_prefix'), 'prefix report adapter missing')
        rows, _ = r.report_prefix(r.S1 / 'artifacts/diagnostics/LATENCY_20261011_01')
        self.assertEqual(len(rows), 23)
        summary = r.latency_rows(rows)
        self.assertTrue(all(Path(x['evidence']).is_file() for x in summary))

    def test_markdown_tables_have_no_blank_rows(self):
        self.assertTrue(hasattr(r, 'markdown_sections'), 'table renderer missing')
        text = r.markdown_sections(['paragraph', '| a |', '|---|', '| b |', 'next'])
        self.assertEqual(text, 'paragraph\n\n| a |\n|---|\n| b |\n\nnext\n')


if __name__ == '__main__':
    unittest.main()
