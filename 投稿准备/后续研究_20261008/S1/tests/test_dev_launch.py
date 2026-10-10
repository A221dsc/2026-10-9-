"""Targeted launcher checks, independent of the frozen engineering suites."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from dev_launch import cpu_fraction, config_bytes, dev_cells
from pair_adapter import registered_order, command_plan

class LauncherChecks(unittest.TestCase):
    def test_counter_deltas(self):
        self.assertAlmostEqual(cpu_fraction([100,200,50],[190,290,60]),.1)
        for a,b in [([1,2,3],[1,2,3]),([4,5,6],[3,8,9]),([1,2,3],[12,3,4])]:
            with self.assertRaises(ValueError):cpu_fraction(a,b)

    def test_config_exact_cpp_bytes(self):
        s='{"schema":"S1.describe.v1","config_sha":"x","config":{ "method" : "M_LIST", "z":1.00 }}\n'
        self.assertEqual(config_bytes(s),b'{ "method" : "M_LIST", "z":1.00 }\n')
        with self.assertRaises(ValueError):config_bytes('{"config":{}}garbage')

    def test_complete_registered_order(self):
        cells=dev_cells()
        self.assertEqual(len(cells),240)
        self.assertEqual(len(set(cells)),240)
        self.assertEqual(cells,sorted(cells,key=lambda x:registered_order(x,'dev')))
        self.assertEqual(cells[0],('D01',90001,'M_EVENT_8'))
        self.assertEqual(cells[-1],('D10',90003,'M_FIXED_8192'))

    def test_serial_abba_commands(self):
        root=Path(__file__).resolve().parents[1]/'artifacts'/'launcher_test_never_executed'
        plan=command_plan(root/'pin.exe',root/'native.exe',root/'cache.bin','0'*64,
                          'M_LIST','M_EVENT_8',root,'b','a','D01:90001:M_EVENT_8',
                          cell=('D01',90001,'M_EVENT_8'))
        self.assertEqual([(r['round'],r['role']) for r in plan],[(1,'A'),(1,'B'),(2,'B'),(2,'A')])
        self.assertEqual([r['command'][r['command'].index('--method')+1] for r in plan],
                         ['M_LIST','M_EVENT_8','M_EVENT_8','M_LIST'])

if __name__=='__main__':unittest.main()
