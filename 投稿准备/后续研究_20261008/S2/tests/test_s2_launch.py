"""Launch safety tests use real subprocesses and immutable on-disk receipts."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
try:
    import s2_launch as launch
except ModuleNotFoundError:
    class Missing:
        def __getattr__(self, name):
            raise AssertionError('missing launch implementation: ' + name)
    launch = Missing()


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def file(self, name, text='bound'):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf8')
        return p

    def test_actual_success_receipt(self):
        cmd = [sys.executable, '-c', 'print("child")']
        r = launch.actual_process(cmd, self.root / 'ledger')
        self.assertIs(type(r['exit_code']), int)
        self.assertEqual(r['exit_code'], 0)
        self.assertTrue(r['actual_exit_observed'])
        self.assertEqual(r['command'], cmd)
        self.assertIn('child', Path(r['stdout']['path']).read_text())
        self.assertGreaterEqual(r['ended_ns'], r['started_ns'])

    def test_failed_child_preserves_receipt_and_stops(self):
        with self.assertRaises(RuntimeError):
            launch.actual_process([sys.executable, '-c', 'import sys; print("bad"); sys.exit(7)'], self.root / 'failed')
        r = json.loads((self.root / 'failed' / 'process.json').read_text())
        self.assertEqual(r['exit_code'], 7)
        self.assertEqual(r['status'], 'FAILURE')
        self.assertTrue(r['actual_exit_observed'])
        self.assertIn('bad', (self.root / 'failed' / 'stdout.txt').read_text())

    def test_spawn_error_has_null_exit_not_invented_integer(self):
        with self.assertRaises(RuntimeError):
            launch.actual_process([str(self.root / 'missing.exe')], self.root / 'spawn')
        r = json.loads((self.root / 'spawn' / 'process.json').read_text())
        self.assertIsNone(r['exit_code'])
        self.assertFalse(r['actual_exit_observed'])

    def test_ledger_exists_does_not_execute_or_overwrite(self):
        ledger = self.root / 'exists'; ledger.mkdir()
        sentinel = self.root / 'executed'
        with self.assertRaises(FileExistsError):
            launch.actual_process([sys.executable, '-c', 'from pathlib import Path; Path(' + repr(str(sentinel)) + ').touch()'], ledger)
        self.assertFalse(sentinel.exists())

    def test_binding_changed_rejected(self):
        p = self.file('source'); b = launch.bind(p)
        p.write_text('changed')
        with self.assertRaises(ValueError): launch.verify_bindings([b])

    def test_sourceguard_rejects_wrong_projection(self):
        with self.assertRaises(ValueError): launch.source_guard(self.file('timestamps'))

    def test_sourceguard_registered_sha(self):
        self.assertEqual(launch.SOURCE_SHA, '8914c691dc39f0f425ade34d34789e2b1985a9434fe31d1300bccb79a641c81c')

    def test_complete_prefix_and_binding(self):
        p = self.file('child'); seal = {'unit_id':'a', 'files':[launch.bind(p)]}
        self.assertEqual(launch.resume_prefix(['a','b'], [seal]), 1)

    def test_resume_gap_rejected(self):
        with self.assertRaises(ValueError): launch.resume_prefix(['a','b','c'], [{'unit_id':'b','files':[]}])

    def test_resume_binding_interruption_rejected(self):
        p = self.file('child'); seal = {'unit_id':'a','files':[launch.bind(p)]}
        p.unlink()
        with self.assertRaises(ValueError): launch.resume_prefix(['a'], [seal])

    def test_unsealed_directory_blocks_resume(self):
        p = self.root / 'units' / '000000_a'; p.mkdir(parents=True)
        with self.assertRaises(ValueError): launch.load_prefix(self.root / 'units', ['a'])

    def test_plan_counts_and_unique_children(self):
        plan = launch.formal_plan()
        self.assertEqual(plan['counts'], {'formal_native':1080,'aa_before':180,'aa_after':180,'resource':120,'children':1560,'prepare':33})
        ids = [c['child_id'] for u in plan['units'] for c in u['children']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_pair_order_and_independent_R6(self):
        units = [u for u in launch.formal_plan()['units'] if u['kind']=='formal_native']
        first = units[0]['children']
        self.assertEqual([(c['round'],c['role']) for c in first], [('AB','A'),('AB','B'),('BA','B'),('BA','A')])
        self.assertEqual([c['method'] for c in first], ['M_LIST','R6','R6','M_LIST'])
        self.assertNotEqual(units[0]['unit_id'], units[1]['unit_id'])

    def test_capacity_plan_engineering_seeds_only(self):
        plan = launch.capacity_plan('full', 102002)
        self.assertEqual(len(plan['units']), 8)
        self.assertTrue(all(u['children'][0]['profile']=='engineering' for u in plan['units']))
        self.assertTrue(all(u['children'][0]['case_id']=='L03' for u in plan['units']))
        with self.assertRaises(ValueError): launch.capacity_plan('full', 100001)

    def test_unsafe_tag_rejected(self):
        for tag in ('../bad', '中文', '', 'a/b'):
            with self.assertRaises(ValueError): launch.safe_tag(tag)

    def test_json_duplicate_or_float_identity_rejected(self):
        for text in ('{"trace_hash":1,"trace_hash":2}', '{"trace_hash":1.0}'):
            with self.assertRaises(ValueError): launch.load_json(self.file('dup.json', text))

    def test_large_integer_metadata_stays_exact(self):
        n = 18446744073709551615
        self.assertEqual(launch.load_json(self.file('large.json', json.dumps({'trace_hash':n})))['trace_hash'], n)

    def test_runtime_imposter_rejected(self):
        p = self.file('fake_python.exe')
        manifest = {'file_count':1,'files':[launch.bind(p)]}
        with self.assertRaises(ValueError): launch.verify_runtime(manifest, self.file('other_python.exe'), p, expected_count=1)

    def test_runtime_every_dependency_rechecked(self):
        p = self.file('python.exe'); dep = self.file('dep.dll')
        manifest = {'file_count':2,'files':[launch.bind(p), launch.bind(dep)]}
        launch.verify_runtime(manifest, p, p, expected_count=2)
        dep.write_text('tampered')
        with self.assertRaises(ValueError): launch.verify_runtime(manifest, p, p, expected_count=2)

    def fixture(self, mode='native'):
        out = self.root / 'output'; out.mkdir()
        meta = {'case_id':'L03','profile':'engineering','seed':102001,'N':768,'U':3072,'horizon':4,'cache_sha':'c','source_sha':'s','protocol_sha':'p','source_bundle_sha':'b','trace_hash':18446744073709551615,'initial_sha':'i','final_sha':'f','queries':136,'returned':6,'query_hash':18446744073709551614,'API_calls':6280}
        expected = dict(meta, batch_id='T',pair_id='pair',round='AB',role='A',mode=mode,method='M_LIST',binary_sha='bin')
        row = dict(expected, schema='S2.raw.v1',verified='true',build_ns=10,online_ns=30,total_ns=40,destroy_ns=2,owner_current_after_destroy='NA' if mode=='native' else 0,owner_live_after_destroy='NA' if mode=='native' else 0,owner_peak='NA' if mode=='native' else 8,promotions=0,scheduled_demotions=0,cleanup_demotions=0,total_demotions=0,peak_tree_buckets=0,final_tree_buckets=0,candidate_max=0,nodes_allocated=768,process_mask_start=8,cpu_start=3,group_start=0,process_mask_end=8,cpu_end=3,group_end=0)
        for name in ('pool','buckets','tree','manager'):
            row[name+'_current']='NA' if mode=='native' else 1
            row[name+'_peak']='NA' if mode=='native' else 2
        self.csv(out/'raw.csv',[row])
        phases = [{'phase':i,'name':name,'begin':begin,'end':end,'queries':q,'returned':2,'online_ns':10} for i,(name,begin,end,q) in enumerate((('sparse_before',0,1024,4),('shuffle',1024,2048,128),('sparse_after',2048,3072,4)))]
        self.csv(out/'phases.csv',phases)
        receipt = dict(expected, schema='S2.run.v1', verified=True,engineering_only=True,owner_current_after_destroy=row['owner_current_after_destroy'],owner_live_after_destroy=row['owner_live_after_destroy'],raw_sha=launch.sha(out/'raw.csv'),phases_sha=launch.sha(out/'phases.csv'))
        if mode=='resource':
            snapshots=[]
            for unit in (768,1024,1536,2048,3072):
                snap={'unit':unit,'phase_boundary':'true' if unit in (1024,2048,3072) else 'false','whole_current':4,'whole_peak':8,'whole_live':4}
                for name in ('pool','buckets','tree','manager'):snap[name+'_current']=1;snap[name+'_peak']=2
                for name in ('promotions','scheduled_demotions','cleanup_demotions','total_demotions','peak_tree_buckets','final_tree_buckets','candidate_max'):snap[name]=0
                snap['nodes_allocated']=768;snapshots.append(snap)
            self.csv(out/'snapshots.csv',snapshots);receipt['snapshots_sha']=launch.sha(out/'snapshots.csv')
        (out/'receipt.json').write_text(json.dumps(receipt))
        process={'command':['exe'], 'actual_exit_observed':True,'exit_code':0,'status':'COMPLETE'}
        return out, expected, process

    @staticmethod
    def csv(path, rows):
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

    def test_accept_bound_actual_raw_phases(self):
        out,e,p=self.fixture()
        self.assertEqual(launch.accept_child(out,e,['exe'],p)['trace_hash'],str(18446744073709551615))

    def test_accept_rejects_float_exit_even_zero(self):
        out,e,p=self.fixture();p['exit_code']=0.0
        with self.assertRaises(ValueError):launch.accept_child(out,e,['exe'],p)

    def test_raw_receipt_disagreement_rejected(self):
        out,e,p=self.fixture();r=json.loads((out/'receipt.json').read_text());r['returned']=5;(out/'receipt.json').write_text(json.dumps(r))
        with self.assertRaises(ValueError):launch.accept_child(out,e,['exe'],p)

    def test_raw_hash_modification_rejected(self):
        out,e,p=self.fixture();(out/'raw.csv').write_text((out/'raw.csv').read_text().replace('18446744073709551615','15'))
        with self.assertRaises(ValueError):launch.accept_child(out,e,['exe'],p)

    def test_phase_total_mismatch_even_rehashed_rejected(self):
        out,e,p=self.fixture();phases=list(csv.DictReader((out/'phases.csv').read_text().splitlines()));phases[0]['online_ns']='9';self.csv(out/'phases.csv',phases)
        r=json.loads((out/'receipt.json').read_text());r['phases_sha']=launch.sha(out/'phases.csv');(out/'receipt.json').write_text(json.dumps(r))
        with self.assertRaises(ValueError):launch.accept_child(out,e,['exe'],p)

    def test_wrong_cpu_end_rejected(self):
        out,e,p=self.fixture();rows=list(csv.DictReader((out/'raw.csv').read_text().splitlines()));rows[0]['cpu_end']='4';self.csv(out/'raw.csv',rows)
        r=json.loads((out/'receipt.json').read_text());r['raw_sha']=launch.sha(out/'raw.csv');(out/'receipt.json').write_text(json.dumps(r))
        with self.assertRaises(ValueError):launch.accept_child(out,e,['exe'],p)

    def test_resource_checkpoints_accepted(self):
        out,e,p=self.fixture('resource');self.assertEqual(launch.accept_child(out,e,['exe'],p)['mode'],'resource')

    def test_resource_missing_checkpoint_rejected(self):
        out,e,p=self.fixture('resource');snaps=list(csv.DictReader((out/'snapshots.csv').read_text().splitlines()));self.csv(out/'snapshots.csv',snaps[1:]);r=json.loads((out/'receipt.json').read_text());r['snapshots_sha']=launch.sha(out/'snapshots.csv');(out/'receipt.json').write_text(json.dumps(r))
        with self.assertRaises(ValueError):launch.accept_child(out,e,['exe'],p)

    def test_formal_preflight_cannot_accept_engineering_lock(self):
        with self.assertRaises(ValueError):launch.validate_lock_shape({'schema':'S2.launch.lock.v1','engineering_only':True},formal=True)

    def test_topology_actual_csv_core3(self):
        text='logical,efficiency_class,kind,ns_per_iter,mask_hex\n2,1,P,1.3,0x4\n3,1,P,1.2,0x8\n# physical_cores=20\n'
        self.assertEqual(launch.parse_topology(text)['logical'], '3')

    def test_topology_rejects_E_or_wrong_mask(self):
        for kind,mask in (('E','0x8'),('P','0x4')):
            with self.assertRaises(ValueError):launch.parse_topology('logical,efficiency_class,kind,ns_per_iter,mask_hex\n3,1,'+kind+',1.2,'+mask+'\n')

    def test_command_plan_separates_output_and_ledger(self):
        lock={'pin':{'path':'pin'},'binaries':{'native':{'path':'native'},'resource':{'path':'resource'}},'timestamps':{'path':'source'}}
        plan=launch.command_plan(lock,launch.capacity_plan('mini',102001),self.root)
        self.assertEqual(len(plan['prepare']),1)
        self.assertEqual(len(plan['run']),8)
        for item in plan['run']:
            output=Path(item['argv'][item['argv'].index('--output')+1])
            self.assertFalse(output.is_relative_to(Path(item['ledger'])))
            self.assertIn('--engineering',item['argv'])

    def test_external_capacity_rejects_summary_only(self):
        path=self.file('capacity/CAPACITY_COMPLETE.json',json.dumps({'schema':'S2.capacity.v1','status':'PASS','engineering_only':True,'N':262144,'U':1048576,'case_id':'L03','seed':102001,'actual_runs':8,'formal_runs':0,'runs':[]}))
        with self.assertRaises(ValueError):launch.verify_capacity(path,{'binaries':{}})

    def test_lock_requires_launcher_binding(self):
        p=self.file('python.exe')
        lock={'schema':'S2.launch.lock.v1','engineering_only':True,'bindings':[launch.bind(p)],'build_manifest':launch.bind(p),'environment':launch.bind(p),'binaries':{},'timestamps':launch.bind(p),'source_bundle_sha':launch.SOURCE_BUNDLE_SHA,'protocol_sha':launch.PROTOCOL_SHA,'runtime_manifest':launch.bind(p),'python':launch.bind(p),'pin':launch.bind(p),'topology':launch.bind(p)}
        with self.assertRaises(ValueError):launch.validate_lock_shape(lock)

    def test_seal_embedded_csv_identity_loads_exact_strings(self):
        doc={'unit_id':'a','files':[],'children':[{'row':{'seed':'102001','trace_hash':'18446744073709551615'},'expected':{'seed':102001}}]}
        p=self.file('seal.json',json.dumps(doc))
        self.assertEqual(launch.load_json(p),doc)

    def test_seal_embedded_csv_fraction_identity_rejected(self):
        p=self.file('seal.json',json.dumps({'row':{'trace_hash':'1.5'}}))
        with self.assertRaises(ValueError):launch.load_json(p)

    def test_freeze_allows_only_registered_evidence_changes(self):
        launch.validate_freeze_diff(['S2/review.json'],['S2/review.json'])
        for changed,allowed in ((['S2/driver.py'],['S2/driver.py']),(['S2/other.json'],['S2/review.json'])):
            with self.assertRaises(ValueError):launch.validate_freeze_diff(changed,allowed)

    def recovery_fixture(self):
        """Golden benchmark exports plus an actually exited toy launch child."""
        output,expected,_=self.fixture()
        self.file('toy_runtime/run','print("actual toy execution")\n')
        self.file('toy_runtime/0x8','import subprocess,sys; sys.exit(subprocess.run([sys.executable,*sys.argv[2:]]).returncode)\n')
        source=self.file('source.bin','toy projection')
        lock={'pin':{'path':sys.executable},'binaries':{'native':launch.bind(sys.executable)},'timestamps':launch.bind(source),'source_bundle_sha':launch.SOURCE_BUNDLE_SHA}
        child={'child_id':'toy_child','pair_id':'pair','round':'AB','role':'A','method':'M_LIST','mode':'native','profile':'engineering','seed':102001,'case_id':'L03','U':3072,'horizon':4}
        unit={'unit_id':'pair','kind':'capacity','children':[child]}
        plan={'units':[unit],'engineering_only':True,'scale':'mini'}
        launch.dump(self.root/'plan.json',plan);launch.dump(self.root/'lock.json',lock)
        cache=self.file('caches/engineering_L03_102001/h4/cache.bin','toy cache')
        expected.update(cache_sha=launch.sha(cache),binary_sha=lock['binaries']['native']['sha256'],batch_id=self.root.name,
                        source_sha=launch.SOURCE_SHA,protocol_sha=launch.PROTOCOL_SHA,source_bundle_sha=launch.SOURCE_BUNDLE_SHA)
        rows=list(csv.DictReader((output/'raw.csv').read_text().splitlines()));rows[0].update({k:str(v) for k,v in expected.items()});self.csv(output/'raw.csv',rows)
        receipt=json.loads((output/'receipt.json').read_text());receipt.update(expected,raw_sha=launch.sha(output/'raw.csv'));(output/'receipt.json').write_text(json.dumps(receipt))
        cacheout=cache.parent.parent
        for horizon in (1,2,4):
            current=cache if horizon==4 else self.file('caches/engineering_L03_102001/h'+str(horizon)+'/cache.bin','toy prefix')
            queries=sum(p[3] for p in launch.expected_phases('L03',768,768*horizon))
            metadata={k:expected[k] for k in launch.IDENTITY_KEYS}
            metadata.update(schema='S2.cache.v1',horizon=horizon,U=768*horizon,Umax=3072,queries=queries,API_calls=2*768*horizon+queries,
                            cache_sha=launch.sha(current),longest_cache_sha=launch.sha(cache),engineering_only=True)
            launch.dump(current.with_name('cache.meta.json'),metadata)
        self.file('toy_runtime/prepare','print('+repr(json.dumps({'schema':'S2.prepare.v1','longest_cache_sha':launch.sha(cache),'prefixes':[1,2,4]}))+')\n')
        prepdir=self.root/'prepare/engineering_L03_102001'
        prepare_command=[launch.short_executable(sys.executable),'prepare','--timestamps',str(source),'--source-sha',launch.SOURCE_SHA,
                         '--output',str(cacheout),'--seed','102001','--case','L03','--profile','engineering','--scale','mini']
        prepare_process=launch.actual_process(prepare_command,prepdir,cwd=self.root/'toy_runtime')
        prepared=launch.accept_prepare(cacheout,'engineering','L03',102001,prepare_process,prepare_command,lock)
        prep=prepdir/'seal.json';launch.dump(prep,prepared)
        unitdir=self.root/'units/000000_pair';out=unitdir/'outputs/toy_child';out.parent.mkdir(parents=True);shutil.move(str(output),str(out))
        ledger=unitdir/'processes/toy_child'
        command=launch.command_run(sys.executable,sys.executable,cache,expected['cache_sha'],child,self.root.name,out)
        process=launch.actual_process(command,ledger,cwd=self.root/'toy_runtime')
        row=launch.accept_child(out,expected,command,process)
        accepted={'child_id':'toy_child','expected':expected,'row':row,'files':[launch.bind(p) for p in out.iterdir()]+[launch.bind(p) for p in ledger.iterdir()]}
        launch.dump(ledger/'accepted.json',accepted)
        seal={'schema':'S2.unit.seal.v1','unit_id':'pair','kind':'capacity','children':[accepted],
              'files':[launch.bind(prep),*prepared['files'],*accepted['files'],launch.bind(ledger/'accepted.json')]}
        launch.dump(unitdir/'seal.json',seal)
        return unitdir,seal,ledger

    def test_recover_real_exited_child_and_original_exports(self):
        self.recovery_fixture()
        self.assertEqual(len(launch.load_prefix(self.root/'units',['pair'])),1)

    def test_recover_rejects_embedded_seal_time_tamper(self):
        unitdir,seal,_=self.recovery_fixture();seal['children'][0]['row']['online_ns']='999'
        (unitdir/'seal.json').write_text(json.dumps(seal))
        with self.assertRaises(ValueError):launch.load_prefix(self.root/'units',['pair'])

    def test_recover_rejects_embedded_seal_role_tamper(self):
        unitdir,seal,_=self.recovery_fixture();seal['children'][0]['expected']['role']='B'
        (unitdir/'seal.json').write_text(json.dumps(seal))
        with self.assertRaises(ValueError):launch.load_prefix(self.root/'units',['pair'])

    def test_recover_rejects_actual_command_role_even_rehashed(self):
        unitdir,seal,ledger=self.recovery_fixture();p=ledger/'process.json';record=json.loads(p.read_text());record['command'][record['command'].index('--role')+1]='B';p.write_text(json.dumps(record))
        for binding in seal['files']:
            if binding['path']==str(p.resolve()):binding['sha256']=launch.sha(p)
        (unitdir/'seal.json').write_text(json.dumps(seal))
        with self.assertRaises(ValueError):launch.load_prefix(self.root/'units',['pair'])

    def test_recover_rejects_missing_original_plan(self):
        self.recovery_fixture();(self.root/'plan.json').unlink()
        with self.assertRaises(ValueError):launch.load_prefix(self.root/'units',['pair'])

    def test_capacity_mini_cannot_be_relabelled_full_summary(self):
        mini={'schema':'S2.launch.complete.v1','status':'COMPLETE','scale':'full','engineering_only':True,'accepted_children':8,'N':768,'U':3072,'files':[]}
        path=self.file('mini_disguised_full.json',json.dumps(mini))
        with self.assertRaises(ValueError):launch.verify_capacity(path,{})

    def test_recover_rejects_prepare_identity_tamper_even_rebound(self):
        unitdir,seal,_=self.recovery_fixture();p=self.root/'prepare/engineering_L03_102001/seal.json';prepared=json.loads(p.read_text());prepared['identities']['4']['query_hash']=1;p.write_text(json.dumps(prepared))
        for binding in seal['files']:
            if binding['path']==str(p.resolve()):binding['sha256']=launch.sha(p)
        (unitdir/'seal.json').write_text(json.dumps(seal))
        with self.assertRaises(ValueError):launch.load_prefix(self.root/'units',['pair'])

    def test_recover_rejects_prepare_actual_command_tamper_even_rebound(self):
        unitdir,seal,_=self.recovery_fixture();p=self.root/'prepare/engineering_L03_102001/process.json';record=json.loads(p.read_text());record['command'][record['command'].index('--seed')+1]='102002';p.write_text(json.dumps(record))
        prepared_path=p.parent/'seal.json';prepared=json.loads(prepared_path.read_text())
        for binding in prepared['files']:
            if binding['path']==str(p.resolve()):binding['sha256']=launch.sha(p)
        prepared_path.write_text(json.dumps(prepared))
        for binding in seal['files']:
            if binding['path'] in (str(p.resolve()),str(prepared_path.resolve())):binding['sha256']=launch.sha(binding['path'])
        (unitdir/'seal.json').write_text(json.dumps(seal))
        with self.assertRaises(ValueError):launch.load_prefix(self.root/'units',['pair'])

    def test_duplicate_completed_preflight_tag_preserves_entire_archive_bytes(self):
        archive=self.root/'artifacts/launch/COMPLETE_PREFLIGHT'
        archive.mkdir(parents=True)
        (archive/'COMPLETE.json').write_bytes(b'{"status":"COMPLETE"}\n')
        (archive/'stdout.txt').write_bytes(b'original execution output\x00\xff')
        lock=self.file('candidate_lock.json','{}')
        before={str(p.relative_to(archive)):p.read_bytes() for p in archive.rglob('*') if p.is_file()}
        with mock.patch.object(launch,'S2',self.root):
            with self.assertRaises(FileExistsError):launch.main(['preflight','--engineering','--tag','COMPLETE_PREFLIGHT','--lock',str(lock)])
        after={str(p.relative_to(archive)):p.read_bytes() for p in archive.rglob('*') if p.is_file()}
        self.assertEqual(after,before)

    def test_fresh_failed_preflight_preserves_this_attempt_failure(self):
        lock=self.file('candidate_lock.json','{}')
        with mock.patch.object(launch,'S2',self.root):
            with self.assertRaises(KeyError):launch.main(['preflight','--engineering','--tag','NEW_PREFLIGHT','--lock',str(lock)])
        archive=self.root/'artifacts/launch/NEW_PREFLIGHT'
        self.assertEqual(launch.load_json(archive/'FAILURE.json')['status'],'FAILURE')
        self.assertTrue((archive/'START.json').is_file())


if __name__=='__main__':unittest.main()
