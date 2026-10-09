"""Entry acceptance regressions. Predetermined fixtures; no experiment execution."""
from pathlib import Path
import argparse
import copy
import importlib
import inspect
import json
import sys
import unittest
import uuid

S1=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(S1/'tools'))
import analysis_fixture as fx
import entry_gate as gate
import select_dev as selection

parser=argparse.ArgumentParser()
parser.add_argument('--case',required=True)
parser.add_argument('--scratch-output',required=True)
parser.add_argument('--fixture-output')
parser.add_argument('--fixture-source')
args=parser.parse_args()

def scratch():
    allowed=(S1/'artifacts/analysis').resolve();root=Path(args.scratch_output).resolve()
    if not root.is_relative_to(allowed):raise ValueError('scratch outside workspace analysis artifacts')
    p=root/uuid.uuid4().hex;p.mkdir(parents=True);return p

def fixture_paths():
    root=Path(args.fixture_source or args.fixture_output) if args.fixture_source or args.fixture_output else S1/'artifacts/analysis/green_complete_03/dev_fixture'
    return sorted(root.glob('D*-*/pair_fixture.json'))

def receipt(name,**kw):
    return {'schema':'S1.entry.asset.v1','asset':name,'test_fixture':True,
            'origin':fx.ORIGIN,'protocol_sha256':gate.sha(gate.PROTOCOL),**kw}

class SelectionRed(unittest.TestCase):
    def test_fixture_cannot_be_frozen_as_production_selection(self):
        saved=gate.load(S1/'artifacts/analysis/green_complete_03/dev_fixture/selection_fixture.json')
        forged={'schema':'S1.entry.asset.v1','asset':'dev_selection','selected_theta':8,'selected_h':8192,
                'inputs':30,'children':960,'pair_manifest_sha':saved['pair_manifest_sha']}
        with self.assertRaises(ValueError):gate._inventory_identity('dev_selection',forged)
    def test_registered_but_wrong_thresholds_and_scores_cannot_pass(self):
        saved=gate.load(S1/'artifacts/analysis/green_complete_03/dev_fixture/selection_fixture.json')
        forged={**saved,'schema':'S1.entry.asset.v1','asset':'dev_selection','test_fixture':False,
                'selected_theta':8,'selected_h':8192,'scores':dict.fromkeys(fx.METHODS,-999.)}
        with self.assertRaises(ValueError):gate._inventory_identity('dev_selection',forged)

class ManifestRed(unittest.TestCase):
    def test_empty_entries_cannot_bind_a_start_or_selected_configuration(self):
        for name in ('start_manifest','final_start_manifest','selected_configs'):
            with self.subTest(asset=name),self.assertRaises(ValueError):
                gate._inventory_identity(name,{'schema':'S1.entry.asset.v1','asset':name,'entries':[{}]})

def aa_receipt(root,scope='dev',timepoints=('before',)):
    methods,cases=(('M_LIST','M_EVENT_16'),('D02','D06')) if scope=='dev' else (('Original','M_LIST','R6'),('F01','F03','F06'))
    entries=[]
    for timepoint in timepoints:
        for method in methods:
            for case in cases:
                for block in range(1,6):
                    p=fx.pair(root/f'{timepoint}-{method}-{case}-{block}',case=case,seed=92001,
                              candidate=method,reference=method,profile='aa',pair_id=f'{timepoint}:{method}:{case}:{block}')
                    entries.append({'timepoint':timepoint,'method':method,'case_id':case,'block':block,
                                    'batch_id':'ENGINEERING_FIXTURE','pair_path':str(p)})
    return receipt('dev_aa_inventory' if scope=='dev' else 'formal_aa_inventory',
                   batch_id='ENGINEERING_FIXTURE',environment_sha256='a'*64,entries=entries)

class AABeforeRed(unittest.TestCase):
    def test_complete_before_is_accepted_for_start_without_after(self):
        r=aa_receipt(scratch())
        # The old production identity path rejects the complete before set before
        # reading any fixture pair. The new explicit fixture mode permits schema
        # verification only; production still rejects every fixture pair.
        kw={'phase':'start','test_fixture':True} if 'phase' in inspect.signature(gate._inventory_identity).parameters else {}
        try:gate._inventory_identity('dev_aa_inventory',r,**kw)
        except ValueError as error:self.fail(f'complete before A/A must satisfy start identity: {error}')

class HardeningSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths=fixture_paths();cls.result=selection.select(cls.paths,test_fixture=True)
    def test_saved_selection_is_recomputed(self):
        verified=selection.verify_selection(self.result,test_fixture=True)
        self.assertEqual((verified['selected_theta'],verified['selected_h']),(16,128))
    def rejected_fields(self,fields):
        for field,value in fields:
            bad=copy.deepcopy(self.result);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):selection.verify_selection(bad,test_fixture=True)
    def test_saved_thresholds_are_recomputed(self):self.rejected_fields([('selected_theta',8),('selected_h',8192)])
    def test_saved_scores_are_recomputed(self):self.rejected_fields([('scores',dict.fromkeys(fx.METHODS,0.))])
    def test_saved_bindings_are_recomputed(self):self.rejected_fields([('input_cache_sha',{}),('identity_bindings',{}),('matrix_interval',{'started_ns':0,'ended_ns':999})])
    def test_saved_rules_are_registered(self):self.rejected_fields([('objective','online'),('write_once',False)])
    def test_production_refuses_fixture_even_with_frozen_outer_bytes(self):
        root=scratch();p=root/'dev_selection.json';bad=copy.deepcopy(self.result);bad['test_fixture']=False;fx.write_json(p,bad)
        trust={'sha256':fx.sha(p),'pair_trust':{str(q.resolve()):{'lock_sha256':fx.sha(q)} for q in self.paths}}
        with self.assertRaises(ValueError):selection.verify_selection(p,trust=trust)
        with self.assertRaises(ValueError):selection.verify_selection(dict(test_fixture=False,selected_theta=16,selected_h=128))
    def test_matrix_missing_duplicate_and_nonshared_input_rejected(self):
        for paths in [self.paths[:-1],self.paths[:-1]+[self.paths[0]]]:
            with self.assertRaises(ValueError):selection.select(paths,test_fixture=True)
        root=scratch();first=gate.load(self.paths[0]);p=fx.pair(root/'replacement',case=first['case_id'],seed=first['seed'],candidate=first['candidate'])
        m=gate.load(p);cache=Path(m['files']['cache']['path']);obj=gate.load(cache);obj['origin']+=' different bytes';fx.write_json(cache,obj)
        # Fully rebind every affected sidecar, retaining a valid individual pair.
        newsha=fx.sha(cache);meta=Path(m['files']['meta']['path']);metaobj=gate.load(meta)
        metaobj.update(cache_sha=newsha,selection_input_identity=f"{m['case_id']}:{m['seed']}:{newsha}");fx.write_json(meta,metaobj)
        fx.rebind_asset(p,'cache');fx.rebind_asset(p,'meta');m=gate.load(p)
        for i,child in enumerate(m['children']):
            d=Path(child['path'])
            for filename in ('raw_native.csv','phase.csv'):
                rows=gate.csv_rows(d/filename)
                for row in rows:row['cache_sha']=newsha
                fx.write_csv(d/filename,rows);fx.rebind_child(p,i,filename)
            r=gate.load(d/'run_receipt.json');r.update(cache_sha_before=newsha,cache_sha_after=newsha,metadata_sha=fx.sha(meta));fx.write_json(d/'run_receipt.json',r);fx.rebind_child(p,i,'run_receipt.json')
            process=gate.load(d/'process.json');process['command'][process['command'].index('--cache-sha')+1]=newsha;fx.write_json(d/'process.json',process);fx.rebind_child(p,i,'process.json')
        gate.validate_pair(p,test_fixture=True)
        with self.assertRaises(ValueError):selection.select([p,*self.paths[1:]],test_fixture=True)
    def test_p06_p07_require_the_same_verified_selection(self):
        a=importlib.import_module('analysis');root=scratch()
        for pair,method in [('P06','M_EVENT_16'),('P07','M_FIXED_128')]:
            paths=[fx.pair(root/f'{pair}-{s}',case='F01',seed=s,candidate='R6',reference=method,profile='final') for s in range(91001,91011)]
            result=a.summarize_pairs(paths,pair,'F01','total',0,test_fixture=True,selection=self.result)
            self.assertEqual(result['n'],10)
            with self.assertRaises(ValueError):a.summarize_pairs(paths,pair,'F01','total',0,test_fixture=True,selection={'test_fixture':True,'selected_theta':16,'selected_h':128})
    def test_write_once_selection_to_entry_wrapper_is_closed(self):
        root=scratch();p=root/'selection_fixture.json';selection.write_selection(p,self.result)
        bound={'path':str(p),'sha256':fx.sha(p)}
        wrapper=receipt('dev_selection',selection=bound,files=[bound])
        verified=gate._inventory_identity('dev_selection',wrapper,test_fixture=True)
        self.assertEqual(verified,self.result)
        self.assertEqual(gate.load(p)['schema'],'S1.dev_selection.v1')
        with self.assertRaises(ValueError):selection.write_selection(p,self.result)
        bad=copy.deepcopy(wrapper);bad['selection']['sha256']='0'*64
        with self.assertRaises(ValueError):gate._inventory_identity('dev_selection',bad,test_fixture=True)

def schema_context(root,formal=False):
    """Actual test-only files and cross-asset receipts; never production inputs."""
    root.mkdir(parents=True,exist_ok=True);context={}
    def add(name,r):
        p=root/(name+'_fixture.json');fx.write_json(p,r)
        context[name]={'path':str(p),'sha256':fx.sha(p),'receipt':r}
    config_template=gate.load(S1/'artifacts/driver/green_review_fixes_root_01/native_cli/R6/config.json')
    binary=root/'native_fixture.exe';binary.write_bytes(b'ENGINEERING_FIXTURE never executable')
    add('frozen_binaries',receipt('frozen_binaries',source_bundle_sha='b'*64,entries=[{'name':'s1_native.exe','path':str(binary),'sha256':fx.sha(binary)}]))
    add('protocol_and_sources',receipt('protocol_and_sources',source_bundle_sha='b'*64,frozen_R6=config_template['frozen_R6']))
    add('fresh_environment_receipt',{'schema':'ENGINEERING_FIXTURE.environment.v1','test_fixture':True,'origin':fx.ORIGIN})
    configs={}
    methods=['M_LIST',*fx.METHODS] if not formal else ['Original','M_LIST','M_OBSERVE_LIST','R6','M_NO_IDLE','M_EVENT_16','M_FIXED_128']
    for method in methods:
        obj=copy.deepcopy(config_template);obj.update(method=method,credit_unit='event' if method.startswith('M_EVENT_') else 'none' if method.startswith('M_FIXED_') else 'NA' if method in ('M_LIST','Original') else 'ns')
        p=root/(method+'_config.json');fx.write_json(p,obj)
        configs[method]={'path':str(p),'sha256':fx.sha(p),'logical_sha256':gate._config_logical(p)[1]}
    cases=range(1,8) if formal else range(1,11);seeds=range(91001,91011) if formal else range(90001,90004);prefix='F' if formal else 'D'
    traces=[]
    for i in cases:
        for seed in seeds:
            p=fx.pair(root/f'input-{i}-{seed}',case=f'{prefix}{i:02}',seed=seed,profile='final' if formal else 'dev')
            files=gate.load(p)['files']
            traces.append({'case_id':f'{prefix}{i:02}','seed':seed,**{key+'_path':files[name]['path'] for key,name in [('cache','cache'),('expected','expected'),('metadata','meta')]}})
    trace_name='formal_trace_inventory' if formal else 'dev_trace_inventory';add(trace_name,receipt(trace_name,entries=traces))
    aa_name='formal_aa_inventory' if formal else 'dev_aa_inventory';add(aa_name,receipt(aa_name,batch_id='ENGINEERING_FIXTURE',environment_sha256=context['fresh_environment_receipt']['sha256'],entries=[]))
    selected={'selected_theta':16,'selected_h':128}
    if formal:
        add('dev_selection',receipt('dev_selection',**selected))
        rows=[{'schema':'S1.selected.config.v1','method':m,'selected_theta':16 if m.startswith('M_EVENT') else None,
               'selected_h':128 if m.startswith('M_FIXED') else None,'mode':'native','binary':{'path':str(binary),'sha256':fx.sha(binary)},'config':configs[m],
               'source_bundle_sha':'b'*64,'protocol_sha256':gate.sha(gate.PROTOCOL)} for m in ('M_EVENT_16','M_FIXED_128')]
        r=receipt('selected_configs',entries=rows,bindings={n:{k:v[k] for k in ('path','sha256')} for n,v in context.items() if n in ('dev_selection','frozen_binaries','protocol_and_sources')})
        add('selected_configs',r)
    entries=[]
    pairs={'P01':('Original','M_LIST'),'P02':('M_LIST','M_OBSERVE_LIST'),'P03':('M_LIST','R6'),'P04':('M_OBSERVE_LIST','R6'),'P05':('Original','R6'),
           'P06':('M_EVENT_16','R6'),'P07':('M_FIXED_128','R6'),'P08':('M_NO_IDLE','R6'),'DIA01':('M_EVENT_16','R6'),'DIA02':('M_FIXED_128','R6')} if formal else {m:('M_LIST',m) for m in fx.METHODS}
    for trace in traces:
        for pid,(ref,cand) in pairs.items():
            inp={name:{'path':trace[key+'_path'],'sha256':fx.sha(trace[key+'_path'])} for name,key in [('cache','cache'),('expected','expected'),('meta','metadata')]}
            entries.append({'schema':'S1.start.pair.v1','status':'NOT_RUN','batch_id':'ENGINEERING_FIXTURE','profile':'final' if formal else 'dev',
                            'case_id':trace['case_id'],'seed':trace['seed'],'pair_id':pid,'reference':ref,'candidate':cand,'mode':'native','children':4,
                            'input':inp,'binary':{'path':str(binary),'sha256':fx.sha(binary)},'configs':{m:configs[m] for m in (ref,cand)},
                            'source_bundle_sha':'b'*64,'protocol_sha256':gate.sha(gate.PROTOCOL)})
    name='final_start_manifest' if formal else 'start_manifest'
    required=('frozen_binaries','protocol_and_sources',trace_name,aa_name,'fresh_environment_receipt')+(('dev_selection','selected_configs') if formal else ())
    r=receipt(name,batch_id='ENGINEERING_FIXTURE',profile='final' if formal else 'dev',status='NOT_RUN',entries=entries,
              bindings={n:{k:context[n][k] for k in ('path','sha256')} for n in required})
    return r,context

class HardeningManifest(unittest.TestCase):
    def test_empty_entry_regression(self):
        for name in ('start_manifest','final_start_manifest','selected_configs'):
            with self.subTest(asset=name),self.assertRaises(ValueError):
                gate._inventory_identity(name,{'schema':'S1.entry.asset.v1','asset':name,'entries':[{}]})
    def test_complete_dev_and_formal_start_plans(self):
        for formal,total in [(False,240),(True,700)]:
            r,ctx=schema_context(scratch(),formal)
            gate._inventory_identity(r['asset'],r,test_fixture=True,context=ctx)
            self.assertEqual(len(r['entries']),total);self.assertTrue(all(e['status']=='NOT_RUN' for e in r['entries']))
            if formal:gate._inventory_identity('selected_configs',ctx['selected_configs']['receipt'],test_fixture=True,context=ctx)
    def test_rehashed_malformed_start_and_selected_assets_rejected(self):
        r,ctx=schema_context(scratch(),True)
        changes=[lambda x:x['entries'][0].pop('configs'),lambda x:x['entries'][0].update(batch_id='wrong'),
                 lambda x:x['entries'].pop(),lambda x:x['entries'].append(copy.deepcopy(x['entries'][0])),
                 lambda x:x['entries'][0].update(candidate='M_EVENT_8'),lambda x:x['entries'][0].update(status='valid'),
                 lambda x:x['bindings']['formal_trace_inventory'].update(sha256='0'*64)]
        for mutate in changes:
            bad=copy.deepcopy(r);mutate(bad);p=scratch()/'rehashed_fixture.json';fx.write_json(p,bad)
            self.assertEqual(gate.sha(p),fx.sha(p))
            with self.assertRaises((ValueError,KeyError)):gate._inventory_identity('final_start_manifest',gate.load(p),test_fixture=True,context=ctx)
        selected=ctx['selected_configs']['receipt']
        for mutate in [lambda x:x['entries'][0].update(selected_theta=8),lambda x:x['entries'][0]['config'].update(logical_sha256='0'*64),
                       lambda x:x['entries'][0]['binary'].update(sha256='0'*64),lambda x:x['entries'].pop()]:
            bad=copy.deepcopy(selected);mutate(bad)
            with self.assertRaises((ValueError,KeyError)):gate._inventory_identity('selected_configs',bad,test_fixture=True,context=ctx)
    def test_production_never_accepts_test_only_start_plan(self):
        r,ctx=schema_context(scratch())
        with self.assertRaises(ValueError):gate._inventory_identity('start_manifest',r,context=ctx)

class HardeningAA(unittest.TestCase):
    def test_before_start_and_complete_before_after_envelope(self):
        for scope in ('dev','final'):
            r=aa_receipt(scratch(),scope,('before','after'));name=r['asset']
            before=copy.deepcopy(r);before['entries']=[e for e in r['entries'] if e['timepoint']=='before']
            result=gate._inventory_identity(name,before,test_fixture=True,phase='start')
            self.assertEqual(result['phase'],'start');self.assertIsNone(result['observed_floor'])
            with self.assertRaises(ValueError):gate._inventory_identity(name,before,test_fixture=True,phase='complete')
            rows=[]
            for e in r['entries']:
                for row in gate.validate_pair(e['pair_path'],test_fixture=True)['rows']:
                    rows.append({**{k:e[k] for k in ('timepoint','method','case_id','block')},'seed':92001,'round':int(row['round']),'role':row['role'],'status':'valid',**{c:int(row[c+'_ns']) for c in ('build','online','total')}})
            r['observed_floor']=importlib.import_module('analysis').aa_floor(rows,scope)
            complete=gate._inventory_identity(name,r,test_fixture=True,phase='complete')
            self.assertEqual(complete['observed_floor'],r['observed_floor'])
            with self.assertRaises(ValueError):importlib.import_module('analysis').aa_floor([row for row in rows if row['timepoint']=='before'],scope)
    def test_aa_batch_duplicate_and_environment_identity(self):
        r=aa_receipt(scratch());name=r['asset']
        for mutate in [lambda x:x['entries'][0].update(batch_id='wrong'),lambda x:x.update(batch_id='wrong'),lambda x:x['entries'].append(x['entries'][0])]:
            bad=copy.deepcopy(r);mutate(bad)
            with self.assertRaises(ValueError):gate._inventory_identity(name,bad,test_fixture=True,phase='start')
        ctx={'fresh_environment_receipt':{'sha256':'b'*64}}
        with self.assertRaises(ValueError):gate._inventory_identity(name,r,test_fixture=True,phase='start',context=ctx)
        with self.assertRaises(ValueError):gate._inventory_identity(name,r,phase='start')
    def test_readiness_phase_is_explicit_and_remains_false_without_real_assets(self):
        for scope in ('dev','final'):
            for phase in ('start','complete'):
                out=gate.readiness({'kernel':True,'driver':True,'analysis':True},{},phase=phase,scope=scope)
                self.assertEqual(out['gate_phase'],phase);self.assertEqual(out['gate_scope'],scope)
                self.assertFalse(out['DEV_READY']);self.assertFalse(out['FINAL_READY'])
                self.assertIsNone(out['selected_theta']);self.assertIsNone(out['selected_h'])
                if scope=='final' and phase=='complete':self.assertIn('formal_matrix_inventory',out['missing_final_assets'])
        with self.assertRaises(ValueError):gate.readiness({}, {},phase='after-only')
        with self.assertRaises(ValueError):gate.readiness({}, {},scope='unknown')

class HardeningHistory(unittest.TestCase):
    def test_complete_selection_needs_dev_after_and_uses_historical_environment(self):
        selected=selection.select(fixture_paths(),test_fixture=True);r=aa_receipt(scratch(),'dev',('before','after'))
        rows=[]
        for e in r['entries']:
            for row in gate.validate_pair(e['pair_path'],test_fixture=True)['rows']:
                rows.append({**{k:e[k] for k in ('timepoint','method','case_id','block')},'seed':92001,'round':int(row['round']),'role':row['role'],'status':'valid',**{c:int(row[c+'_ns']) for c in ('build','online','total')}})
        r['observed_floor']=importlib.import_module('analysis').aa_floor(rows,'dev')
        before=copy.deepcopy(r);before['entries']=[e for e in r['entries'] if e['timepoint']=='before']
        traces=[]
        for case,seed in sorted(selection.INPUTS):
            p=next(p for p in fixture_paths() if gate.load(p)['case_id']==case and gate.load(p)['seed']==seed)
            traces.append({'case_id':case,'seed':seed,'cache_path':gate.load(p)['files']['cache']['path']})
        historical={'fresh_environment_receipt':{'sha256':'a'*64},'start_manifest':{'receipt':{'batch_id':'ENGINEERING_FIXTURE'}},
                    'dev_selection':{'verified':selected},'dev_trace_inventory':{'receipt':{'entries':traces}},
                    'dev_aa_inventory':{'receipt':before,'verified':gate._inventory_identity(before['asset'],before,test_fixture=True,phase='start')}}
        with self.assertRaisesRegex(ValueError,'dev after AA required'):gate._dev_completion_identity(historical,test_fixture=True)
        historical['dev_aa_inventory']={'receipt':r,'verified':gate._inventory_identity(r['asset'],r,test_fixture=True,phase='complete',context=historical)}
        current={'fresh_environment_receipt':{'sha256':'b'*64}}
        result=gate._dev_completion_identity({**current,**historical},test_fixture=True)
        self.assertEqual(result['observed_floor'],r['observed_floor'])
        self.assertNotEqual(current['fresh_environment_receipt']['sha256'],historical['fresh_environment_receipt']['sha256'])

class HardeningFinalAnalysis(unittest.TestCase):
    def test_complete_pairs_require_after_aa_and_recomputed_floor(self):
        root=scratch();paths=[fx.pair(root/f'final-{s}',case='F01',seed=s,candidate='R6',profile='final') for s in range(91001,91011)]
        r=aa_receipt(root/'aa','final',('before','after'));p=root/'formal_aa_fixture.json';a=importlib.import_module('analysis')
        before=copy.deepcopy(r);before['entries']=[e for e in r['entries'] if e['timepoint']=='before'];fx.write_json(p,before)
        try:
            with self.assertRaisesRegex(ValueError,'AA inventory missing'):
                a.summarize_pairs(paths,'P03','F01','total',0,test_fixture=True,aa_inventory=p)
        except TypeError as error:self.fail(f'final summary lacks complete A/A acceptance: {error}')
        rows=[]
        for e in r['entries']:
            for row in gate.validate_pair(e['pair_path'],test_fixture=True)['rows']:
                rows.append({**{k:e[k] for k in ('timepoint','method','case_id','block')},'seed':92001,'round':int(row['round']),'role':row['role'],'status':'valid',**{c:int(row[c+'_ns']) for c in ('build','online','total')}})
        r['observed_floor']=a.aa_floor(rows,'final');fx.write_json(p,r)
        out=a.summarize_pairs(paths,'P03','F01','total',None,test_fixture=True,aa_inventory=p)
        self.assertEqual(out['aa_log_floor'],r['observed_floor']['total']);self.assertEqual(out['aa_inventory_sha256'],fx.sha(p))
        with self.assertRaisesRegex(ValueError,'AA floor mismatch'):a.summarize_pairs(paths,'P03','F01','total',.5,test_fixture=True,aa_inventory=p)
        with self.assertRaisesRegex(ValueError,'production final summary requires complete AA'):a.summarize_pairs(paths,'P03','F01','total',0)

class HardeningTiming(unittest.TestCase):
    def test_rehashed_after_before_matrix_is_rejected(self):
        r=aa_receipt(scratch(),'final',('before','after'));r['observed_floor']={'build':0.,'online':0.,'total':0.,'interpretation':'finite_observed_envelope_not_confidence_bound'}
        p=scratch()/'bounded_aa_fixture.json';fx.write_json(p,r)
        trust={'test_matrix':{'batch_id':'ENGINEERING_FIXTURE','matrix_interval':{'started_ns':100,'ended_ns':200},'matrix_cells':{},'pair_manifest_sha':{}}}
        with self.assertRaisesRegex(ValueError,'AA actual process order'):
            gate.verify_complete_aa(p,test_fixture=True,trust=trust)
        for e in r['entries']:
            if e['timepoint']=='after':fx.shift_pair_times(e['pair_path'],300)
        out=gate.verify_complete_aa(p,test_fixture=True,trust=trust)
        self.assertEqual(out['observed_floor']['total'],0.)
        target=next(e for e in r['entries'] if e['timepoint']=='after');fx.shift_pair_times(target['pair_path'],-250)
        gate.validate_pair(target['pair_path'],test_fixture=True)
        with self.assertRaisesRegex(ValueError,'AA actual process order'):gate.verify_complete_aa(p,test_fixture=True,trust=trust)
    def test_formal_complete_shape_requires_all_700_pairs(self):
        labels=['P01','P02','P03','P04','P05','P06','P07','P08','DIA01','DIA02']
        rows=[{'case_id':f'F{i:02}','seed':s,'pair_id':label,'pair_path':str(S1/'artifacts/analysis'/f'fixture-{i}-{s}-{label}.json')}
              for i in range(1,8) for s in range(91001,91011) for label in labels]
        try:pairs=gate._formal_matrix_shape(rows,{'selected_theta':16,'selected_h':128})
        except AttributeError as error:self.fail(f'complete formal matrix acceptance missing: {error}')
        self.assertEqual(len(pairs),10);self.assertEqual(len(rows),700)
        for bad in (rows[:10],rows[:-1],rows[:-1]+[rows[0]]):
            with self.assertRaises(ValueError):gate._formal_matrix_shape(bad,{'selected_theta':16,'selected_h':128})
    def test_aa_identity_rejects_diagnostic_mode(self):
        p=fx.pair(scratch()/'native',case='D02',seed=92001,candidate='M_LIST',reference='M_LIST',profile='aa')
        out=gate.validate_pair(p,test_fixture=True);entry={'case_id':'D02','method':'M_LIST'}
        try:gate._aa_pair_identity(out,entry)
        except AttributeError as error:self.fail(f'native AA identity acceptance missing: {error}')
        for mode in ('latency','resource'):
            with self.assertRaises(ValueError):gate._aa_pair_identity({**out,'mode':mode},entry)

class HardeningPhaseClosure(unittest.TestCase):
    def test_dev_completion_requires_frozen_complete_selection(self):
        out=gate.readiness({'kernel':True,'driver':True,'analysis':True},{},scope='dev',phase='complete')
        self.assertFalse(out['DEV_READY']);self.assertIn('dev_selection',out['missing_dev_assets'])
    def test_original_start_before_binding_survives_complete_inventory(self):
        root=scratch();start,ctx=schema_context(root/'schema');aa=aa_receipt(root/'aa','dev',('before','after'))
        aa['environment_sha256']=ctx['fresh_environment_receipt']['sha256']
        aa['observed_floor']={'build':0.,'online':0.,'total':0.,'interpretation':'finite_observed_envelope_not_confidence_bound'}
        before=copy.deepcopy(aa);before['entries']=[e for e in aa['entries'] if e['timepoint']=='before'];before.pop('observed_floor')
        p=Path(ctx['dev_aa_inventory']['path']);fx.write_json(p,before)
        ctx['dev_aa_inventory']={'path':str(p),'sha256':fx.sha(p),'receipt':before}
        start['bindings']['dev_aa_inventory']={'path':str(p),'sha256':fx.sha(p)}
        gate._inventory_identity('start_manifest',start,test_fixture=True,context=ctx)
        aa['before_inventory']={'path':str(p),'sha256':fx.sha(p)};q=root/'complete_aa_fixture.json';fx.write_json(q,aa)
        complete=gate._inventory_identity('dev_aa_inventory',aa,test_fixture=True,context=ctx,phase='complete')
        ctx['dev_aa_inventory']={'path':str(q),'sha256':fx.sha(q),'receipt':aa,'verified':complete}
        try:gate._inventory_identity('start_manifest',start,test_fixture=True,context=ctx,phase='complete')
        except ValueError as error:self.fail(f'original frozen before binding must survive completion: {error}')
        damaged=copy.deepcopy(aa);damaged['before_inventory']['sha256']='0'*64
        with self.assertRaises(ValueError):gate._inventory_identity('dev_aa_inventory',damaged,test_fixture=True,context=ctx,phase='complete')

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromName(args.case,sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
