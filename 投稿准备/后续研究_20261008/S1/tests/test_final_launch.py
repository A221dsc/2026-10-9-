"""Check final orchestration scope and historical DEV provenance."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from final_launch import formal_cells, formal_methods, historical_assets
from pair_adapter import registered_order

class FinalLauncherChecks(unittest.TestCase):
    def test_all_independent_formal_cells_in_registered_order(self):
        cells=formal_cells()
        self.assertEqual(len(cells),700)
        self.assertEqual(len(set(cells)),700)
        self.assertEqual(cells,sorted(cells,key=lambda c:registered_order(c,'final')))
        self.assertEqual(cells[0],('F01',91001,'DIA01'))
        self.assertEqual(cells[-1],('F07',91010,'P08'))
        self.assertTrue(set(c[1] for c in cells).isdisjoint({90001,90002,90003,92001}))

    def test_dev_selected_thresholds_do_not_change_diagnostic_arms(self):
        methods=formal_methods(16,2048)
        self.assertEqual(methods['P03'],('M_LIST','R6'))
        self.assertEqual(methods['P06'],('M_EVENT_16','R6'))
        self.assertEqual(methods['P07'],('M_FIXED_2048','R6'))
        self.assertEqual(methods['DIA02'],('M_FIXED_128','R6'))
        alternative=formal_methods(8,512)
        self.assertEqual(alternative['DIA01'],('M_EVENT_16','R6'))
        self.assertEqual(alternative['P06'],('M_EVENT_8','R6'))
        with self.assertRaises(ValueError):formal_methods(17,2048)

    def test_preserve_historical_dev_bindings_without_mutation(self):
        original={'fresh_environment_receipt':'old/env.json','frozen_binaries':{'path':'old/bin.json'},
                  'start_manifest':{'path':'old/start.json'}}
        trust={'fresh_environment_receipt':{'sha256':'old-env'},'frozen_binaries':{'sha256':'old-bin'}}
        assets,external=historical_assets(original,trust)
        self.assertEqual(assets['dev_environment_receipt'],'old/env.json')
        self.assertEqual(assets['frozen_binaries'],original['frozen_binaries'])
        self.assertEqual(external['dev_environment_receipt'],trust['fresh_environment_receipt'])
        assets['frozen_binaries']['path']='new'
        external['frozen_binaries']['sha256']='new'
        self.assertEqual(original['frozen_binaries']['path'],'old/bin.json')
        self.assertEqual(trust['frozen_binaries']['sha256'],'old-bin')

if __name__=='__main__':unittest.main()
