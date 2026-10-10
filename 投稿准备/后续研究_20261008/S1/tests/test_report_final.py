"""Counter presentation fixtures; these contain no performance measurements."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from report_final import COUNTER_FIELDS,summarize_counters,production_start_path

def fixture(pair,**overrides):
    return {'case_id':'F04','seed':'91001','method':'M_EVENT_16','pair_id':pair,
            **{k:'0' for k in COUNTER_FIELDS},**overrides}

class CounterPresentationChecks(unittest.TestCase):
    def test_resume_keeps_original_start_gate_reference(self):
        self.assertEqual(production_start_path(Path('fixture/resumed'),{'original_run':'fixture/original'}),
                         Path('fixture/original/FINAL_START_GATE.json'))
        self.assertEqual(production_start_path(Path('fixture/direct'),{}),
                         Path('fixture/direct/FINAL_START_GATE.json'))

    def test_contract_permits_address_tie_variants_without_extra_seed_samples(self):
        # Values observed in the real F04:91001:DIA01 Event_16 rounds.
        a=fixture('fixture:r1',total_avoidable_work='43778232',promotions='52',
                  scheduled_demotions='51',cleanup_demotions='1',total_demotions='52')
        b=fixture('fixture:r2',total_avoidable_work='43849408',promotions='51',
                  scheduled_demotions='50',cleanup_demotions='1',total_demotions='51')
        rows=summarize_counters([a,b])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['run_count'],2)
        self.assertEqual(rows[0]['unique_counter_variants'],2)
        self.assertEqual((rows[0]['promotions_min'],rows[0]['promotions_max']),(51,52))
        self.assertEqual(rows[0]['promotions'],'VARIES')

    def test_identical_repeats_and_na_keep_one_input_group(self):
        a=fixture('fixture:r1',method='Original',total_avoidable_work='NA')
        b={**a,'pair_id':'fixture:r2'}
        rows=summarize_counters([a,b])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['run_count'],2)
        self.assertEqual(rows[0]['unique_counter_variants'],1)
        self.assertEqual(rows[0]['total_avoidable_work_min'],'NA')

if __name__=='__main__':unittest.main()
