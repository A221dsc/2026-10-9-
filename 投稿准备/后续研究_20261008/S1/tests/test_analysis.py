"""SX20 / SX21 / SX23 deterministic behavior tests; no experiment execution."""
from pathlib import Path
import argparse
import copy
import importlib
import json
import math
import sys
import tempfile
import unittest
import uuid
import contextlib
import io
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import analysis_fixture as fx

parser=argparse.ArgumentParser(); parser.add_argument('--red',choices=['gm','decision','selection','sidecar']);
parser.add_argument('--case'); parser.add_argument('--fixture-output'); parser.add_argument('--scratch-output'); parser.add_argument('--prepare-batch',type=int); args,unittest_args=parser.parse_known_args()

def scratch_temp():
    # Child processes inherit a restricted Windows temp ACL. Keep reversible
    # test scratch inside the explicitly writable workspace instead.
    allowed=(Path(__file__).resolve().parents[1]/'artifacts/analysis').resolve()
    root=Path(args.scratch_output).resolve() if args.scratch_output else allowed/'scratch'
    if not root.is_relative_to(allowed):raise ValueError('fixture scratch outside analysis artifacts')
    root.mkdir(parents=True,exist_ok=True);path=root/uuid.uuid4().hex;path.mkdir()
    class RetainedScratch:
        name=str(path)
        def cleanup(self):pass  # Preserve even failed/damaged fixture attempts.
        def __enter__(self):return self.name
        def __exit__(self,*exc):return False
    return RetainedScratch()

class NegativeControls(unittest.TestCase):
    def test_gm(self):
        import red_analysis as r
        self.assertAlmostEqual(r.two_round_ratio([(1, .25),(1,4)]),1.0)
    def test_decision(self):
        import red_analysis as r
        self.assertEqual(r.classify([math.log(.8)]+[math.log(1.1)]*9,-.4,.3),'unresolved')
    def test_selection(self):
        import red_analysis as r
        self.assertEqual(r.choose([{'method':'E8','online':1,'total':100},
                                   {'method':'E16','online':2,'total':10}]),'E16')
    def test_sidecar(self):
        import red_analysis as r
        self.assertFalse(r.accept_pair({'raw':[{'status':'valid'}]*4,'failure.json':{'status':'invalid_attempt'}}))

class Statistics(unittest.TestCase):
    def setUp(self): self.a=importlib.import_module('analysis')
    def test_two_round_gm_and_invalid(self):
        self.assertEqual(self.a.two_round_ratio([(1,.25),(1,4)]),1)
        self.assertAlmostEqual(self.a.two_round_ratio([(2,1),(8,2)]),math.sqrt(.125))
        for v in [[(1,1)],[(0,1),(1,1)],[(1,-1),(1,1)],[(1,float('inf')),(1,1)]]:
            with self.subTest(v=v),self.assertRaises(ValueError): self.a.two_round_ratio(v)
    def test_quantile_sd_ci_scales(self):
        ratios=[.8,.82,.84,.86,.88,.90,.92,.94,.96,.98]
        out=self.a.summarize(ratios,'P03','F01','total',0)
        logs=[math.log(x) for x in ratios]; mean=sum(logs)/10
        sd=math.sqrt(sum((x-mean)**2 for x in logs)/9)
        self.assertAlmostEqual(out['median'],.89); self.assertAlmostEqual(out['q25'],.845)
        self.assertAlmostEqual(out['q75'],.935); self.assertAlmostEqual(out['iqr'],.09)
        self.assertEqual(out['wins'],10); self.assertAlmostEqual(out['mean_log'],mean)
        self.assertAlmostEqual(out['sample_sd_log'],sd)
        self.assertAlmostEqual(out['log_ci_lower'],mean-4.6568750120624305*sd/math.sqrt(10),places=12)
        self.assertAlmostEqual(out['ratio_ci_upper'],math.exp(out['log_ci_upper']))
        self.assertEqual(out['ci_estimand'],'geometric_mean'); self.assertNotIn('median_ci',out)
    def test_student_t_independent_oracle(self):
        self.assertAlmostEqual(self.a.student_t_quantile(.975,9),2.262157162798205,places=12)
        self.assertAlmostEqual(self.a.student_t_quantile(1-.05/(2*42),9),4.6568750120624305,places=11)
        # Independent Simpson integration of normalized density, no implementation CDF reuse.
        for x in [.1,1,2.262157162798205,4.6568750120624305]:
            n=10000; h=x/n; norm=math.gamma(5)/(math.sqrt(9*math.pi)*math.gamma(4.5))
            f=lambda v:norm*(1+v*v/9)**-5
            oracle=.5+h/3*(f(0)+f(x)+sum((4 if i%2 else 2)*f(i*h) for i in range(1,n)))
            self.assertAlmostEqual(self.a.student_t_cdf(x,9),oracle,places=13)
        for p in [.001,.025,.5,.975,1-.05/84]:
            self.assertAlmostEqual(self.a.student_t_cdf(self.a.student_t_quantile(p,9),9),p,places=13)
        for p,df in [(0,9),(1,9),(.5,0)]:
            with self.assertRaises(ValueError):self.a.student_t_quantile(p,df)
    def test_strict_fast_slow_unresolved(self):
        for ratios,want in [([.8]*10,'strong_fast'),([1.2]*10,'strong_slow'),([1]*10,'unresolved'),
                            ([.8]*9+[1],'unresolved'),([1.2]*9+[1],'unresolved')]:
            self.assertEqual(self.a.summarize(ratios,'P03','F01','online',0)['classification'],want)
        t=-max(0,-math.log(.95)); self.assertEqual(self.a.classify([t]*10,t,t,0),'unresolved')
        t=max(0,math.log(1.05)); self.assertEqual(self.a.classify([t]*10,t,t,0),'unresolved')
        self.assertEqual(self.a.classify([-.2]*10,-.3,-.051,0),'unresolved')
        self.assertEqual(self.a.summarize([.8]*10,'P03','F01','online',.3)['classification'],'unresolved')
    def test_fixed_42_family_and_input_count(self):
        family=self.a.confirmatory_family(); self.assertEqual(len(family),42)
        self.assertEqual(len(set(family)),42)
        for cell in family: self.assertEqual(self.a.summarize([.9]*10,*cell,0)['family_size'],42)
        for pair,component in [('P03','build'),('P01','online'),('DIA01','total')]:
            self.assertEqual(self.a.summarize([.9]*10,pair,'F01',component,0)['family_size'],1)
        for ratios in [[1]*9,[1]*11,[1]*9+[0],[1]*9+[float('nan')]]:
            with self.assertRaises(ValueError):self.a.summarize(ratios,'P03','F01','total',0)
    def test_aa_complete_envelope(self):
        for scope,methods,cases in [('dev',['M_LIST','M_EVENT_16'],['D02','D06']),
                                    ('final',['Original','M_LIST','R6'],['F01','F03','F06'])]:
            rows=[]
            for time in ['before','after']:
                for method in methods:
                    for case in cases:
                        for block in range(1,6):
                            for rnd,role in [(1,'A'),(1,'B'),(2,'B'),(2,'A')]:
                                rows.append({'timepoint':time,'method':method,'case_id':case,'seed':92001,
                                             'block':block,'round':rnd,'role':role,'status':'valid',
                                             'build':100,'online':100 if role=='A' else 120,
                                             'total':200 if role=='A' else 220})
            out=self.a.aa_floor(rows,scope); self.assertAlmostEqual(out['online'],math.log(1.2))
            self.assertAlmostEqual(out['total'],math.log(1.1)); self.assertEqual(out['build'],0)
            self.assertEqual(out['interpretation'],'finite_observed_envelope_not_confidence_bound')
            for bad in [rows[:-1],rows+[rows[0]], [dict(r,status='invalid') if i==0 else r for i,r in enumerate(rows)]]:
                with self.assertRaises(ValueError):self.a.aa_floor(bad,scope)

class Sidecar(unittest.TestCase):
    def setUp(self):
        self.tmp=scratch_temp(); self.addCleanup(self.tmp.cleanup)
        self.e=importlib.import_module('entry_gate'); self.root=Path(self.tmp.name)
    def newpair(self,name='p',**kw):return fx.pair(self.root/name,**kw)
    def test_legal_pair_and_fixture_refusal(self):
        p=self.newpair(); out=self.e.validate_pair(p,test_fixture=True)
        self.assertEqual(out['ratios']['total'],1); self.assertEqual(len(out['rows']),4)
        with self.assertRaises(ValueError):self.e.validate_pair(p)
        original=self.newpair('original',candidate='Original');out=self.e.validate_pair(original,test_fixture=True)
        self.assertEqual(out['rows'][1]['conversion_failures'],'NA')
    def test_existing_engineering_cache_byte_identity(self):
        s1=Path(__file__).resolve().parents[1];d=s1/'artifacts/driver/green_review_fixes_root_01/native_cli/input'
        try:obj=self.e.cache_identity(d/'cache.bin',d/'cache.expected.bin')
        except ValueError as e:self.fail(f'legal frozen engineering cache must validate: {e}')
        self.assertEqual(obj['N'],128);self.assertEqual(obj['U'],16);self.assertEqual(obj['queries'],16)
        self.assertEqual(obj['returned'],128);self.assertEqual(obj['query_hash'],3248282998135947347)
        meta=json.loads((d/'cache.meta.json').read_text(encoding='utf-8'))
        self.assertEqual(self.e._record_sha(obj['initial']),meta['initial_sha'])
        self.assertEqual(self.e._record_sha(obj['final']),meta['final_sha'])
    def test_config_file_hash_distinct_from_logical_crlf(self):
        p=self.newpair('crlf');m=json.loads(p.read_text());d=Path(m['children'][0]['path'])/'config.json'
        original=d.read_bytes();d.write_bytes(original[:-1]+b'\r\n');fx.rebind_child(p,0,'config.json')
        o=self.e.validate_pair(p,test_fixture=True);self.assertEqual(o['ratios']['total'],1)
        self.assertNotEqual(fx.sha(d),o['rows'][0]['config_sha'])
        d.write_bytes(d.read_bytes()+b'\n');fx.rebind_child(p,0,'config.json')
        with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_phase_nonpositive_definition_and_sum_rehashed(self):
        import csv
        for field,value in [('online_ns','0'),('online_ns','99'),('begin_unit','1'),('phase','wrong'),('phase_returned','2')]:
            p=self.newpair('phase-'+field+'-'+value);m=json.loads(p.read_text());d=Path(m['children'][0]['path'])/'phase.csv'
            with d.open(encoding='utf-8') as f:rows=list(csv.DictReader(f))
            rows[0][field]=value;fx.write_csv(d,rows);fx.rebind_child(p,0,'phase.csv')
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_formal_complete_ten_paired_inputs(self):
        paths=[self.newpair('formal-'+str(seed),case='F01',seed=seed,candidate='R6',total=160,online=80,profile='final') for seed in range(91001,91011)]
        a=importlib.import_module('analysis');o=a.summarize_pairs(paths,'P03','F01','total',0,test_fixture=True)
        self.assertEqual(o['classification'],'strong_fast');self.assertEqual(o['family_size'],42)
        for bad in [paths[:-1],paths+[paths[0]],paths[:-1]+[paths[0]]]:
            with self.assertRaises(ValueError):a.summarize_pairs(bad,'P03','F01','total',0,test_fixture=True)
    def test_every_byte_binding(self):
        for name in ['raw_native.csv','phase.csv','config.json','run_receipt.json','process.json','stdout.txt','stderr.txt']:
            p=self.newpair('child-'+name); m=json.loads(p.read_text()); d=Path(m['children'][0]['path'])/name
            d.write_bytes(d.read_bytes()+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
        for name in ['cache','expected','meta','protocol','binary','generator','pin','topology']:
            p=self.newpair('asset-'+name); m=json.loads(p.read_text()); d=Path(m['files'][name]['path'])
            d.write_bytes(d.read_bytes()+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
        p=self.newpair('source'); m=json.loads(p.read_text()); Path(next(iter(m['source_files'].values()))['path']).write_bytes(b'bad')
        with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_failure_or_missing_receipt(self):
        p=self.newpair('failure'); d=Path(json.loads(p.read_text())['children'][0]['path']); fx.write_json(d/'failure.json',{'status':'invalid_attempt'})
        with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
        p=self.newpair('receipt'); d=Path(json.loads(p.read_text())['children'][0]['path']); (d/'run_receipt.json').unlink()
        with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_semantic_corruption_even_rehashed(self):
        for field,value in [('status','invalid'),('role','B'),('round','3'),('case_id','D02'),('seed','90002'),
                            ('placement_end_cpu','2'),('placement_start_group','1'),('placement_start_mask','4'),
                            ('binary_sha','0'*64),('config_sha','0'*64),('source_bundle_sha','0'*64),
                            ('protocol_sha','0'*64),('cache_sha','0'*64),('query_hash','124'),('returned','2'),
                            ('API_calls','6'),('total_ns','999'),('lifecycle_ns','999'),('online_ns','0'),
                            ('pool_current','0'),('peak_tree_buckets','33'),('cand_max','4097')]:
            p=self.newpair('semantic-'+field); m=json.loads(p.read_text()); d=Path(m['children'][0]['path'])
            import csv
            rows=list(csv.DictReader((d/'raw_native.csv').open(encoding='utf-8'))); rows[0][field]=value
            fx.write_csv(d/'raw_native.csv',rows); fx.rebind_child(p,0,'raw_native.csv')
            with self.subTest(field=field),self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_meta_identity_not_boolean(self):
        for field,value in [('generator_sha','0'*64),('initial_sha','0'*64),('final_sha','0'*64),
                            ('selection_input_identity','D99:90001:x'),('expected_sha','0'*64),('seed',90002),('N',3)]:
            p=self.newpair('meta-'+field); m=json.loads(p.read_text()); d=Path(m['files']['meta']['path'])
            obj=json.loads(d.read_text()); obj[field]=value; fx.write_json(d,obj); fx.rebind_asset(p,'meta')
            # Receipt kept consistent so rejection must arise from identity semantics.
            m=json.loads(p.read_text())
            for i,c in enumerate(m['children']):
                r=Path(c['path'])/'run_receipt.json'; o=json.loads(r.read_text());o['metadata_sha']=m['files']['meta']['sha256'];fx.write_json(r,o);fx.rebind_child(p,i,'run_receipt.json')
            with self.subTest(field=field),self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_process_phase_receipt_and_missing_duplicate(self):
        for filename,key,value in [('process.json','exit_code',2),('process.json','order_index',3),
                                   ('run_receipt.json','cache_sha_after','0'*64),('run_receipt.json','status','invalid')]:
            p=self.newpair(filename+key); d=Path(json.loads(p.read_text())['children'][0]['path'])/filename
            obj=json.loads(d.read_text()); obj[key]=value; fx.write_json(d,obj);fx.rebind_child(p,0,filename)
            with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
        p=self.newpair('command');d=Path(json.loads(p.read_text())['children'][0]['path'])/'process.json'
        obj=json.loads(d.read_text()); obj['command'][3]='selftest';fx.write_json(d,obj);fx.rebind_child(p,0,'process.json')
        with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
        for mutate in [lambda m:m['children'].pop(),lambda m:m['children'].append(m['children'][0])]:
            p=self.newpair('shape'+str(len(list(self.root.iterdir()))));m=json.loads(p.read_text());mutate(m);fx.write_json(p,m)
            with self.assertRaises(ValueError):self.e.validate_pair(p,test_fixture=True)
    def test_resume_only_complete_attempt(self):
        p=self.newpair(); self.assertTrue(self.e.can_resume(p,test_fixture=True))
        d=Path(json.loads(p.read_text())['children'][2]['path']);fx.write_json(d/'failure.json',{'status':'environment_interrupted'})
        self.assertFalse(self.e.can_resume(p,test_fixture=True));q=self.newpair('newattempt');self.assertTrue(self.e.can_resume(q,test_fixture=True));self.assertTrue((d/'failure.json').exists())

class Selection(unittest.TestCase):
    def setUp(self):
        self.s=importlib.import_module('select_dev');self.tmp=scratch_temp();self.addCleanup(self.tmp.cleanup)
        self.root=Path(args.fixture_output) if args.fixture_output and self._testMethodName=='test_full_960_total_equal_tie_and_write_once' else Path(self.tmp.name)
        self.root.mkdir(parents=True,exist_ok=True)
    def matrix(self):
        pairs=[]
        for case in [f'D{i:02}' for i in range(1,11)]:
            for seed in [90001,90002,90003]:
                for method in fx.METHODS:
                    total=300 if method.endswith('_8') else 200
                    online=1 if method.endswith('_8') else 100
                    p=self.root/f'{case}-{seed}-{method}'/'pair_fixture.json'
                    if args.fixture_output:
                        self.assertTrue(p.exists(),f'missing preconstructed fixture {p}')
                        pairs.append(p)
                    else:pairs.append(fx.pair(p.parent,case,seed,method,total,online))
        return pairs
    def test_full_960_total_equal_tie_and_write_once(self):
        pairs=self.matrix();o=self.s.select(pairs,test_fixture=True)
        self.assertEqual(o['children'],960);self.assertEqual(o['inputs'],30);self.assertEqual(o['selected_theta'],16)
        self.assertEqual(o['selected_h'],128);self.assertEqual(len(o['scores']),8)
        self.assertEqual(set(o['family_input_counts'].values()),{6});self.assertTrue(o['test_fixture'])
        self.assertEqual(len(o['pair_manifest_sha']),240)
        dest=self.root/'selection_fixture.json';self.s.write_selection(dest,o)
        with self.assertRaises(ValueError):self.s.write_selection(dest,o)
        with self.assertRaises(ValueError):self.s.write_selection(self.root/'dev_selection.json',o)
        for bad in [pairs[:-1],pairs+[pairs[0]]]:
            with self.assertRaises(ValueError):self.s.select(bad,test_fixture=True)
    def test_exact_tie_not_epsilon(self):
        self.assertEqual(self.s.choose_score([(8,0.0),(16,0.0)]),8)
        self.assertEqual(self.s.choose_score([(8,1e-15),(16,0.0)]),16)
    def test_wrong_input_set(self):
        with self.assertRaises(ValueError):self.s.select([],test_fixture=True)

class FixturePreparation(unittest.TestCase):
    def test_prepare_thirty_inputs(self):
        self.assertIn(args.prepare_batch,range(8));self.assertIsNotNone(args.fixture_output)
        method=fx.METHODS[args.prepare_batch];root=Path(args.fixture_output)
        created=[]
        for case in [f'D{i:02}' for i in range(1,11)]:
            for seed in [90001,90002,90003]:
                total=300 if method.endswith('_8') else 200
                online=1 if method.endswith('_8') else 100
                p=fx.pair(root/f'{case}-{seed}-{method}',case,seed,method,total,online)
                m=json.loads(p.read_text(encoding='utf-8'));self.assertEqual(len(m['children']),4)
                self.assertTrue(m['test_fixture']);created.append((m['case_id'],m['seed']))
        self.assertEqual(set(created),{(f'D{i:02}',s) for i in range(1,11) for s in (90001,90002,90003)})

class AdapterGate(unittest.TestCase):
    def setUp(self):self.p=importlib.import_module('pair_adapter');self.e=importlib.import_module('entry_gate')
    def test_order_mapping_and_aa_blocks(self):
        x=self.p.schedule(2);self.assertEqual([(r['round'],r['role'],r['old_arm']) for r in x],[(1,'A',0),(1,'B',1),(2,'B',1),(2,'A',0)])
        aa=self.p.schedule(10,aa=True);self.assertEqual(len(aa),20)
        self.assertEqual({r['block'] for r in aa},set(range(1,6)))
        self.assertEqual(len({r['block_pair_id'] for r in aa}),5)
        for block in range(1,6):self.assertEqual([r['round'] for r in aa if r['block']==block],[1,1,2,2])
    def test_adapter_plan_no_old_cli(self):
        with scratch_temp() as d:
            cache=Path(d)/'cache.bin';cache.write_bytes(b'fixture')
            x=self.p.command_plan('pin.exe','native.exe',cache,'a'*64,'M_LIST','R6',Path(d)/'out','batch','attempt','pair')
            self.assertEqual(len(x),4)
            for c in x:self.assertIn('--cache',c['command']);self.assertIn('--role',c['command']);self.assertNotIn('--data',c['command']);self.assertIn('run',c['command'])
    def test_frozen_runner_hash_and_static_rotation(self):
        out=self.p.verify_legacy();self.assertEqual(out['sha256'],'bd38435b1e5b51d71bafbe0b92a6280f8b9b6af27e4dbb87832b5fa51ca9dea7')
        self.assertFalse(out['run_once_compatible_with_cache_cli'])
    def test_readiness_layers_and_fresh_receipt(self):
        o=self.e.readiness({'kernel':True,'driver':True,'analysis':True},{})
        self.assertTrue(o['code_correctness_complete']);self.assertFalse(o['DEV_READY']);self.assertFalse(o['FINAL_READY'])
        self.assertIsNone(o['selected_theta']);self.assertIn('fresh_environment_receipt',o['missing_dev_assets'])
        with self.assertRaises(ValueError):self.e.verify_environment({'status':'valid'})
        forged={name:{'validated':True,'test_fixture':False} for name in o['missing_dev_assets']+o['missing_final_assets']}
        forged['dev_selection'].update(selected_theta=8,selected_h=128)
        forged_status=self.e.readiness({'kernel':True,'driver':True,'analysis':True},forged)
        self.assertFalse(forged_status['DEV_READY']);self.assertFalse(forged_status['FINAL_READY'])
    def test_driver_actual_complete_evidence(self):
        s1=Path(__file__).resolve().parents[1]
        out=self.e.verify_driver(s1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        self.assertEqual(out['suite_count'],35);self.assertEqual(out['command_count'],78)
        self.assertEqual(out['compiles'],6);self.assertEqual(out['compile_warnings'],0)
        self.assertEqual(out['mode_counts'],{'native':23,'latency':6,'resource':6})
        self.assertTrue(out['verified'])
    def test_driver_green_label_cannot_replace_suite_coverage(self):
        s1=Path(__file__).resolve().parents[1];original=s1/'artifacts/driver/green_review_fixes_root_01/manifest.json'
        m=json.loads(original.read_text(encoding='utf-8'));m['coverage']=m['coverage'][:1]
        with scratch_temp() as d:
            p=Path(d)/'manifest.json';fx.write_json(p,m)
            with self.assertRaises(ValueError):self.e.verify_driver(p,expected_sha=fx.sha(p))
    def test_kernel_actual_99_cases(self):
        s1=Path(__file__).resolve().parents[1]
        o=self.e.verify_kernel(s1/'artifacts/kernel/green_coverage_fix_01/manifest.json')
        self.assertEqual(o['case_count'],99);self.assertEqual(o['random_cases'],30);self.assertTrue(o['verified'])
    def test_engineering_runner_flags_allowlist(self):
        r=importlib.import_module('run_engineering')
        for argv in [['--tag','a','--benchmark'],['--tag','a','--task','performance'],['--tag','../a']]:
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises((ValueError,SystemExit)):r.arguments(argv)
        self.assertEqual(r.arguments(['--tag','engineering_fixture']).task,'fixtures')

if __name__=='__main__':
    if args.red:
        suite=unittest.TestSuite([NegativeControls('test_'+args.red)])
    elif args.prepare_batch is not None:
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(FixturePreparation)
    elif args.case:
        suite=unittest.defaultTestLoader.loadTestsFromName(args.case,sys.modules[__name__])
    else:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in [Statistics,Sidecar,Selection,AdapterGate])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
