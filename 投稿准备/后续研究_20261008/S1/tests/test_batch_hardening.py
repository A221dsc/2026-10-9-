"""MF4/MF5 actual collector regressions; invented test-only process evidence.

Registered labels stay unchanged. case:seed:label is the execution identity
carried by lock/raw/phase/process; safe directory names deliberately omit ':'.
No measured binary, calibration or performance subprocess is started.
"""
from pathlib import Path
import argparse
import copy
import json
import shutil
import sys
import unittest
import uuid

S1=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(S1/'tools'))
import analysis_fixture as fx
import entry_gate as gate
import select_dev as selection

p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--scratch-output',required=True)
p.add_argument('--fixture-output');p.add_argument('--fixture-source');args=p.parse_args()
LABELS=['DIA01','DIA02',*[f'P{i:02}' for i in range(1,9)]]
METHODS={'P01':('Original','M_LIST'),'P02':('M_LIST','M_OBSERVE_LIST'),'P03':('M_LIST','R6'),
         'P04':('M_OBSERVE_LIST','R6'),'P05':('Original','R6'),'P06':('M_EVENT_16','R6'),
         'P07':('M_FIXED_128','R6'),'P08':('M_NO_IDLE','R6'),'DIA01':('M_EVENT_16','R6'),'DIA02':('M_FIXED_128','R6')}

def scratch():
    base=Path(args.scratch_output).resolve()
    if not base.is_relative_to((S1/'artifacts/analysis').resolve()):raise ValueError('workspace scratch required')
    q=base/uuid.uuid4().hex;q.mkdir(parents=True);return q

def source():
    q=Path(args.fixture_source or args.fixture_output or S1/'artifacts/analysis/batch_fixture_mf45_01/dev_fixture').resolve()
    if not q.is_relative_to((S1/'artifacts/analysis').resolve()):raise ValueError('workspace fixture source required')
    return q

def dev_paths():return sorted(source().glob('D*-*/pair_fixture.json'))
def formal_record():return gate.load(source().parent/'formal_matrix_fixture.json')

def clone_pair(path,root):
    # Copy only mutable child bytes; every untouched asset remains read-only.
    m=gate.load(path)
    if m.get('test_fixture') is not True:raise ValueError('fixture copies only')
    children=[];configs={}
    for i,c in enumerate(m['children']):
        d=root/f'child{i}';shutil.copytree(c['path'],d)
        process=gate.load(d/'process.json');process['command'][process['command'].index('--output')+1]=str(d)
        fx.write_json(d/'process.json',process)
        children.append({'path':str(d),'files':{name:fx.sha(d/name) for name in c['files']}})
        configs[str(d)]=m['config_logical'][c['path']]
    m['children']=children;m['config_logical']=configs;q=root/'pair_fixture.json';fx.write_json(q,m)
    gate.validate_pair(q,test_fixture=True);return q

def formal_call(record,root):
    q=root/'formal_matrix_fixture.json';fx.write_json(q,record)
    return gate.verify_formal_matrix(q,test_fixture=True)

class BatchPreparation(unittest.TestCase):
    def test_formal_seventy(self):
        label=LABELS[int(args.case[len('BatchFormal'):])];base=Path(args.fixture_output).parent/'formal_fixture'
        for i in range(1,8):
            for seed in range(91001,91011):
                ref,cand=METHODS[label];q=fx.pair(base/f'F{i:02}-{seed}-{label}',case=f'F{i:02}',seed=seed,
                    reference=ref,candidate=cand,profile='final',pair_id=f'F{i:02}:{seed}:{label}')
                out=gate.validate_pair(q,test_fixture=True);self.assertEqual((out['case_id'],out['seed'],out['reference'],out['candidate']),(f'F{i:02}',seed,ref,cand))
    def test_manifest(self):
        base=Path(args.fixture_output).parent;selected=Path(args.fixture_output)/'selection_fixture.json'
        entries=[{'case_id':f'F{i:02}','seed':s,'pair_id':label,'execution_pair_id':f'F{i:02}:{s}:{label}',
                  'pair_path':str(base/'formal_fixture'/f'F{i:02}-{s}-{label}'/'pair_fixture.json')}
                 for i in range(1,8) for s in range(91001,91011) for label in LABELS]
        self.assertEqual(len(entries),700);self.assertTrue(all(Path(e['pair_path']).exists() for e in entries))
        fx.write_json(base/'formal_matrix_fixture.json',{'schema':'S1.entry.asset.v1','asset':'formal_matrix_inventory',
            'test_fixture':True,'origin':fx.ORIGIN,'status':'COMPLETE','batch_id':'ENGINEERING_FIXTURE',
            'selection':{'path':str(selected),'sha256':fx.sha(selected)},'entries':entries})

class BatchIdentity(unittest.TestCase):
    def test_copied_lock_is_not_an_independent_diagnostic(self):
        r=formal_record();root=scratch();target=next(e for e in r['entries'] if e['case_id']=='F01' and e['seed']==91001 and e['pair_id']=='P06')
        copied=root/'copied_pair_fixture.json';copied.write_bytes(Path(target['pair_path']).read_bytes())
        diag=next(e for e in r['entries'] if e['case_id']=='F01' and e['seed']==91001 and e['pair_id']=='DIA01');diag['pair_path']=str(copied)
        gate.validate_pair(copied,test_fixture=True)
        with self.assertRaises(ValueError):formal_call(r,root)
    def test_same_methods_wrong_cell_execution_is_rejected(self):
        r=formal_record();root=scratch()
        for labels in [('P06','DIA01'),('P07','DIA02')]:
            a,b=[next(e for e in r['entries'] if e['case_id']=='F01' and e['seed']==91001 and e['pair_id']==label) for label in labels]
            a['pair_path'],b['pair_path']=b['pair_path'],a['pair_path']
        with self.assertRaises(ValueError):formal_call(r,root)
    def test_shared_reference_children_are_rejected(self):
        paths=dev_paths();first=next(q for q in paths if q.parent.name=='D01-90001-M_EVENT_8');second=next(q for q in paths if q.parent.name=='D01-90001-M_EVENT_16')
        root=scratch();changed=clone_pair(second,root/'changed');a=gate.load(first);b=gate.load(changed)
        b['files']=copy.deepcopy(a['files']);b['source_files']=copy.deepcopy(a['source_files']);b['pair_id']=a['pair_id']
        for index in (0,3):b['children'][index]=copy.deepcopy(a['children'][index])
        b['config_logical']={c['path']:gate.load(Path(c['path'])/'config.json') for c in b['children']};fx.write_json(changed,b)
        for index in (1,2):
            d=Path(b['children'][index]['path'])
            for filename in ('raw_native.csv','phase.csv'):
                rows=gate.csv_rows(d/filename)
                for row in rows:row['pair_id']=a['pair_id']
                fx.write_csv(d/filename,rows);fx.rebind_child(changed,index,filename)
            process=gate.load(d/'process.json');process['command']=gate.child_command(a['files']['pin']['path'],a['files']['binary']['path'],a['files']['cache']['path'],a['files']['cache']['sha256'],b['candidate'],d,b['batch_id'],b['attempt_id'],a['pair_id'],1 if index==1 else 2,'B')
            process.update(started_ns=2000+index*2,ended_ns=2000+index*2+1);fx.write_json(d/'process.json',process);fx.rebind_child(changed,index,'process.json')
        gate.validate_pair(first,test_fixture=True);gate.validate_pair(changed,test_fixture=True)
        self.assertEqual(len({c['path'] for m in (a,gate.load(changed)) for c in m['children']}),6)
        with self.assertRaises(ValueError):selection.select([changed if q==second else q for q in paths],test_fixture=True)

class BatchChronology(unittest.TestCase):
    def test_start_plans_freeze_registered_order(self):
        import runpy
        previous=sys.argv;sys.argv=[str(S1/'tests/test_entry_hardening.py'),'--case','unused','--scratch-output',args.scratch_output]
        try:helper=runpy.run_path(str(S1/'tests/test_entry_hardening.py'),run_name='batch_support')
        finally:sys.argv=previous
        for formal in (False,True):
            r,context=helper['schema_context'](scratch(),formal);r['entries'][0],r['entries'][1]=r['entries'][1],r['entries'][0]
            with self.assertRaises(ValueError):gate._inventory_identity(r['asset'],r,test_fixture=True,context=context)
    def test_dev_pair_overlap_rejected(self):
        paths=dev_paths();root=scratch();target=next(q for q in paths if q.parent.name=='D01-90001-M_EVENT_16');changed=clone_pair(target,root/'changed');fx.set_pair_times(changed,2003)
        gate.validate_pair(changed,test_fixture=True)
        with self.assertRaises(ValueError):selection.select([changed if q==target else q for q in paths],test_fixture=True)
    def test_dev_serial_wrong_candidate_order_rejected(self):
        paths=dev_paths();root=scratch();replacements={}
        for label,start in [('M_EVENT_8',2040),('M_EVENT_16',2000)]:
            q=next(q for q in paths if q.parent.name==f'D01-90001-{label}');changed=clone_pair(q,root/label);fx.set_pair_times(changed,start);replacements[q]=changed
        with self.assertRaises(ValueError):selection.select([replacements.get(q,q) for q in paths],test_fixture=True)
    def test_formal_serial_wrong_main_diagnostic_order_rejected(self):
        r=formal_record();root=scratch()
        for label,start in [('DIA01',20080),('P01',20000)]:
            e=next(e for e in r['entries'] if e['case_id']=='F01' and e['seed']==91001 and e['pair_id']==label)
            q=clone_pair(e['pair_path'],root/label);fx.set_pair_times(q,start);e['pair_path']=str(q)
        with self.assertRaises(ValueError):formal_call(r,root)
    def test_aa_timepoint_overlap_rejected(self):
        # Import support without changing its independently frozen CLI parser.
        import runpy
        previous=sys.argv;sys.argv=[str(S1/'tests/test_entry_hardening.py'),'--case','unused','--scratch-output',args.scratch_output]
        try:helper=runpy.run_path(str(S1/'tests/test_entry_hardening.py'),run_name='batch_support')
        finally:sys.argv=previous
        r=helper['aa_receipt'](scratch());fx.set_pair_times(r['entries'][1]['pair_path'],3)
        with self.assertRaises(ValueError):gate._inventory_identity('dev_aa_inventory',r,test_fixture=True,phase='start')

class BatchPositive(unittest.TestCase):
    def test_registered_adapter_keeps_diagnostic_independent(self):
        import pair_adapter as adapter
        root=scratch();cache=root/'cache.bin';cache.write_bytes(b'ENGINEERING_FIXTURE')
        plans=[]
        for label in ('DIA01','P06'):
            cell=('F01',91001,label);identity=adapter.registered_pair_id(*cell)
            plan=adapter.command_plan('pin.exe','native.exe',cache,fx.sha(cache),'M_EVENT_16','R6',root,'batch','attempt',identity,cell=cell)
            self.assertTrue(all(identity in row['command'] for row in plan));plans.extend(plan)
        self.assertEqual(len({row['command'][row['command'].index('--output')+1] for row in plans}),8)
        with self.assertRaises(ValueError):adapter.command_plan('pin.exe','native.exe',cache,fx.sha(cache),'M_EVENT_16','R6',root,'batch','attempt','F01:91001:P06',cell=('F01',91001,'DIA01'))
    def test_independent_registered_dev_batch_accepted(self):
        out=selection.select(list(reversed(dev_paths())),test_fixture=True);self.assertEqual((out['children'],out['selected_theta'],out['selected_h']),(960,16,128))
    def test_independent_formal_batch_accepts_unordered_entries(self):
        r=formal_record();r['entries'].reverse();out=formal_call(r,scratch());self.assertEqual(len(out['matrix_cells']),700);self.assertEqual(len(out['pair_manifest_sha']),700)

class BatchAAOrder(unittest.TestCase):
    def test_completed_inventory_order_independent(self):
        import runpy
        previous=sys.argv;sys.argv=[str(S1/'tests/test_entry_hardening.py'),'--case','unused','--scratch-output',args.scratch_output]
        try:helper=runpy.run_path(str(S1/'tests/test_entry_hardening.py'),run_name='batch_support')
        finally:sys.argv=previous
        root=scratch();r=helper['aa_receipt'](root/'aa','dev',('before','after'))
        before=copy.deepcopy(r);before['entries']=[e for e in r['entries'] if e['timepoint']=='before']
        gate._inventory_identity('dev_aa_inventory',before,test_fixture=True,phase='start')
        for e in r['entries']:gate.validate_pair(e['pair_path'],test_fixture=True)
        original=root/'before_inventory_fixture.json';fx.write_json(original,before);digest=fx.sha(original)
        r['before_inventory']={'path':str(original),'sha256':digest}
        r['observed_floor']={'build':0.,'online':0.,'total':0.,'interpretation':'finite_observed_envelope_not_confidence_bound'}
        r['entries'].reverse()  # Array order changes; frozen content and clocks do not.
        try:out=gate._inventory_identity('dev_aa_inventory',r,test_fixture=True,phase='complete')
        except ValueError as error:self.fail(f'complete AA inventory order must be independent of original before array order: {error}')
        self.assertEqual(out['observed_floor']['total'],0.);self.assertEqual(fx.sha(original),digest)
        duplicate=copy.deepcopy(r);duplicate['entries'].append(copy.deepcopy(duplicate['entries'][0]))
        with self.assertRaises(ValueError):gate._inventory_identity('dev_aa_inventory',duplicate,test_fixture=True,phase='complete')
        # Rehashing a different original file must not hide changed full entry
        # content or duplicate/missing registered cells.
        for mutate in (lambda x:x['entries'][0].update(changed_entry_content=True),
                       lambda x:x['entries'].__setitem__(1,copy.deepcopy(x['entries'][0]))):
            changed=copy.deepcopy(before);mutate(changed);q=scratch()/'different_before_fixture.json';fx.write_json(q,changed)
            bad=copy.deepcopy(r);bad['before_inventory']={'path':str(q),'sha256':fx.sha(q)}
            with self.assertRaises(ValueError):gate._inventory_identity('dev_aa_inventory',bad,test_fixture=True,phase='complete')

if __name__=='__main__':
    name='BatchPreparation.test_manifest' if args.case=='BatchFormalManifest' else 'BatchPreparation.test_formal_seventy' if args.case.startswith('BatchFormal') else args.case
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(name,sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
