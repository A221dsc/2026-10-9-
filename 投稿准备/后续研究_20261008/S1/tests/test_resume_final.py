import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from resume_final import sealed_prefix
from final_launch import formal_cells

class ResumeChecks(unittest.TestCase):
    def test_complete_prefix_is_reused_without_repeating_finished_cells(self):
        cells=formal_cells()
        self.assertEqual(sealed_prefix(cells,set(cells[:267])),267)
        self.assertEqual(cells[267],('F03',91007,'P06'))
        self.assertEqual(sealed_prefix(cells,set()),0)
        self.assertEqual(sealed_prefix(cells,set(cells)),700)

    def test_holes_and_unregistered_cells_cannot_be_reordered_away(self):
        cells=formal_cells()
        for present in ({cells[1]},set(cells[:3])|{cells[4]},set(cells[:2])|{('F99',91001,'P03')}):
            with self.assertRaises(ValueError):sealed_prefix(cells,present)

if __name__=='__main__':unittest.main()
