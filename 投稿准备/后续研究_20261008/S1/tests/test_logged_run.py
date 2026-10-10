import sys
import uuid
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from logged_run import run_logged

class LoggedRunChecks(unittest.TestCase):
    def test_actual_success_is_not_an_assumed_exit(self):
        root=Path(__file__).resolve().parents[1]/'artifacts/logged_unit_tests'/('success_'+uuid.uuid4().hex)
        self.assertEqual(run_logged([sys.executable,'-B','-c','print("real stdout",flush=True)'],root),0)
        self.assertEqual((root/'stdout.txt').read_text().strip(),'real stdout')

    def test_actual_failure_and_stderr_are_preserved(self):
        root=Path(__file__).resolve().parents[1]/'artifacts/logged_unit_tests'/('failure_'+uuid.uuid4().hex)
        self.assertEqual(run_logged([sys.executable,'-B','-c','import sys; print("actual failure",file=sys.stderr); sys.exit(3)'],root),3)
        self.assertIn('actual failure',(root/'stderr.txt').read_text())

if __name__=='__main__':unittest.main()
