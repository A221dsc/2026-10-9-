"""Registered S2 statistics and immutable output contract tests."""
import copy
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import unittest

S2=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(S2/'tools'))
import s2_launch as launch
import report_s2 as report


def fixture():
    rows=[]
    for unit in launch.formal_plan()['units']:
        for child in unit['children']:
            row={k:str(v) for k,v in child.items()}
            row.update(kind=unit['kind'],N='262144',cache_sha='same',source_sha='source',protocol_sha='protocol',source_bundle_sha='bundle',trace_hash='1',initial_sha='init',final_sha='final',queries='1',returned='2',query_hash='3',API_calls='4',batch_id='batch')
            row.update(build_ns='100',online_ns='1000',total_ns='1100')
            rows.append(row)
    return rows


class S2ReportTests(unittest.TestCase):
    def test_complete_counts_and_54_family(self):
        rows=fixture(); result=report.analyze_native(rows)
        self.assertEqual(len(result['paired']),810)
        self.assertEqual(len(result['summary']),81)
        self.assertEqual(sum(r['scope']=='primary' for r in result['summary']),54)
        self.assertEqual(len(result['aa_blocks']),90)
        self.assertEqual(result['floor']['blocks'],90)
        self.assertTrue(all(r['classification']=='unresolved' for r in result['summary'] if r['scope']=='primary'))
        self.assertTrue(all(r['classification']=='exploratory' for r in result['summary'] if r['scope']=='exploratory'))

    def test_pair_direction_includes_BA_B_over_A(self):
        rows=fixture(); group=[r for r in rows if r['kind']=='formal_native'][:4]
        # AB reference 100, candidate 25; BA candidate 144, reference 400.
        for row,value in zip(group,[100,25,144,400]):row['online_ns']=str(value)
        paired=report.pair_rows(group)
        self.assertAlmostEqual(paired['online'],.3,places=14)
        self.assertNotAlmostEqual(paired['online'],(25+144)/(100+400))

    def test_missing_duplicate_wrong_seed_mode_rejected(self):
        rows=fixture()
        for mutation in ('missing','duplicate','seed','mode','method','identity'):
            damaged=copy.deepcopy(rows)
            if mutation=='missing':damaged.pop()
            elif mutation=='duplicate':damaged[-1]=damaged[0].copy()
            elif mutation=='seed':damaged[181]['seed']='100011'
            elif mutation=='mode':damaged[181]['mode']='resource'
            elif mutation=='method':damaged[181]['method']='TLX'
            elif mutation=='identity':damaged[181]['cache_sha']='other'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):report.analyze_native(damaged)

    def test_corrected_interval_numerical_integration(self):
        s=report.summarize([math.exp(.01*i) for i in range(10)],'online',0)
        t=s['critical_t']; df=9
        # Independent Simpson quadrature of Student density, no S1 cdf reuse.
        n=40000; step=t/n
        factor=math.gamma(5)/(math.sqrt(9*math.pi)*math.gamma(4.5))
        density=lambda x:factor*(1+x*x/9)**(-5)
        area=step/3*(density(0)+density(t)+4*sum(density(i*step) for i in range(1,n,2))+2*sum(density(i*step) for i in range(2,n,2)))
        self.assertAlmostEqual(.5+area,1-.05/108,places=11)
        self.assertEqual(s['family_size'],54)
        self.assertEqual(s['ci_estimand'],'geometric_mean')
        self.assertAlmostEqual(s['mean_log'],.045)
        self.assertAlmostEqual(s['sample_sd_log'],math.sqrt(.00825/9))
        self.assertAlmostEqual(s['log_ci_upper'],.045+t*math.sqrt(.00825/9)/math.sqrt(10))

    def test_symmetric_strict_boundary_and_all_ten_requirement(self):
        d=math.log(1.05)
        self.assertEqual(report.classify([-d]*10,-d,-d,d),'unresolved')
        self.assertEqual(report.classify([d]*10,d,d,d),'unresolved')
        self.assertEqual(report.classify([-d-.001]*10,-d-.002,-d-.0001,d),'strong_fast')
        self.assertEqual(report.classify([d+.001]*10,d+.0001,d+.002,d),'strong_slow')
        self.assertEqual(report.classify([-d-.01]*9+[0],-1,-d-.001,d),'unresolved')
        self.assertEqual(report.summarize([.97]*10,'online',0)['classification'],'unresolved')
        self.assertEqual(report.summarize([.9]*10,'online',.2)['classification'],'unresolved')

    def test_aa_pools_before_after_and_preserves_extreme(self):
        rows=fixture()
        for row in rows:
            if row['kind']=='aa_after' and row['pair_id'].endswith('L03_101001_h4_TLX') and row['role']=='B':row['online_ns']='2000'
        r=report.analyze_native(rows)
        self.assertAlmostEqual(r['floor']['components']['online']['E'],math.log(2))
        self.assertEqual(len(r['aa_blocks']),90)
        with self.assertRaises(ValueError):report.analyze_native([r for r in rows if r['kind']!='aa_after'])

    def test_wrong_seed_set_summary_rejected(self):
        with self.assertRaises(ValueError):report.summarize_seed_pairs({s:1. for s in range(100002,100012)},'total',0)

    def test_resource_na_and_persistent_current_not_peak_sum(self):
        raw={'method':'TLX',**{a+'_'+suffix:'NA' for a in launch.ACCOUNTS for suffix in ('current','peak')}}
        snap={'whole_current':'111','whole_peak':'222','whole_live':'3'}
        self.assertEqual(report.resource_values(raw,snap)['persistent_current'],'NA')
        raw={'method':'R6',**{a+'_current':'10' for a in launch.ACCOUNTS},**{a+'_peak':'999' for a in launch.ACCOUNTS}}
        values=report.resource_values(raw,snap)
        self.assertEqual(values['persistent_current'],40)
        self.assertEqual(values['whole_peak'],222)

    def test_resource_pairs_keep_seed_pairing_and_zero_na(self):
        rows=[]
        for case in ('L01','L02','L03'):
            for seed in range(100001,100011):
                for method in ('M_LIST','M_EVENT_16','R6','TLX'):
                    row=dict(case_id=case,seed=str(seed),method=method,mode='resource')
                    for metric in report.RESOURCE_PAIR_METRICS:row[metric]='NA' if method=='TLX' else (2 if method=='R6' else 5)
                    rows.append(row)
        result=report.pair_resources(rows)
        self.assertEqual(len(result),90)
        self.assertTrue(all(r['promotions_ratio']==.4 for r in result if r['reference']!='TLX'))
        self.assertTrue(all(r['promotions_ratio']=='NA' for r in result if r['reference']=='TLX'))
        for row in rows:row['promotions']=0
        self.assertTrue(all(r['promotions_ratio']=='NA' for r in report.pair_resources(rows)))
        with self.assertRaises(ValueError):report.pair_resources(rows[:-1])

    def test_output_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'existing';path.mkdir();sentinel=path/'sentinel';sentinel.write_text('original')
            with self.assertRaises(FileExistsError):report.claim_output(path)
            self.assertEqual(sentinel.read_text(),'original')
            self.assertEqual(list(path.iterdir()),[sentinel])


if __name__=='__main__':unittest.main()
