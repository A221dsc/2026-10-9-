"""Execute the frozen S0 DEV matrix; no algorithm or statistical changes.

No fixture authority, fabricated process receipts, performance-based retries,
or final experiments. Each invocation creates an exclusive production archive.
Versions are Git commits; legacy integrity fields are consumed by frozen gates.
"""
from pathlib import Path
import argparse
import csv
import ctypes
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
import traceback

import entry_gate as gate
import analysis
from pair_adapter import DEV_CANDIDATES, command_plan, registered_pair_id, verify_legacy
from select_dev import select, write_selection

S1=Path(__file__).resolve().parents[1]
WORKSPACE=S1.parents[2]

def cpu_fraction(before, after):
    if len(before)!=3 or len(after)!=3:raise ValueError('three CPU counters required')
    d=[b-a for a,b in zip(before,after)]
    total=d[1]+d[2]
    if any(x<0 for x in d) or total<=0 or d[0]>total:raise ValueError('invalid CPU counter interval')
    return 1-d[0]/total

def config_bytes(stdout):
    obj=json.loads(stdout)
    token='"config":'
    start=stdout.index(token)+len(token)
    while stdout[start].isspace():start+=1
    value,end=json.JSONDecoder().raw_decode(stdout[start:])
    if value!=obj['config'] or stdout[start+end:].strip()!='}':raise ValueError('exact final config object required')
    return (stdout[start:start+end]+'\n').encode('utf-8')

def dev_cells():
    return [(f'D{i:02}',seed,method) for i in range(1,11) for seed in (90001,90002,90003) for method in DEV_CANDIDATES]

def dump(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def bind(path):
    return {'path':str(Path(path).resolve()),'sha256':gate.sha(path)}

def log(message):print(time.strftime('%H:%M:%S'),message,flush=True)

def actual_process(command,directory,stem='process',order_index=None):
    directory=Path(directory)
    started=time.time_ns()
    try:
        r=subprocess.run([str(x) for x in command],capture_output=True)
        code=r.returncode;out=r.stdout;err=r.stderr;error=None
    except OSError as e:
        code=None;out=b'';err=str(e).encode('utf8');error=repr(e)
    ended=time.time_ns()
    directory.mkdir(parents=True,exist_ok=True)
    outpath=directory/('stdout.txt' if stem=='process' else stem+'.stdout.txt')
    errpath=directory/('stderr.txt' if stem=='process' else stem+'.stderr.txt')
    with outpath.open('xb') as f:f.write(out)
    with errpath.open('xb') as f:f.write(err)
    doc={'command':[str(x) for x in command],'started_ns':started,'ended_ns':ended,
         'exit_code':code,'order_index':order_index,'spawn_error':error}
    dump(directory/(stem+'.json'),doc)
    if code!=0:raise RuntimeError(f'actual child exit {code}: {command}; {err.decode("utf8",errors="replace")}')
    return out.decode('utf-8'),doc

class Quiet:
    """GetSystemTimes deltas include own preceding benchmark, as preregistered."""
    def __init__(self):self.previous=None
    @staticmethod
    def counters():
        values=[ctypes.c_ulonglong() for _ in range(3)]
        if not ctypes.windll.kernel32.GetSystemTimes(*(ctypes.byref(x) for x in values)):raise ctypes.WinError()
        return [v.value for v in values]
    def check(self,path,reset=False):
        started=time.time_ns();samples=[]
        if reset:self.previous=None
        initial=self.previous is None
        wait_started=time.monotonic()
        while True:
            if self.previous is None:
                a=self.counters();before=time.monotonic();time.sleep(2)
            else:
                before,a=self.previous
                remaining=.2-(time.monotonic()-before)
                if remaining>0:time.sleep(remaining)
            b=self.counters();now=time.monotonic();elapsed=now-before
            busy=cpu_fraction(a,b)
            samples.append({'seconds':elapsed,'busy_fraction':busy,'counter_delta':[y-x for x,y in zip(a,b)],
                            'unix_ns':time.time_ns(),'mode':'whole_machine_includes_own_benchmark_cpu'})
            self.previous=(now,b)
            if busy<=.1:
                doc={'status':'valid','initial':initial,'started_ns':started,'ended_ns':time.time_ns(),'samples':samples}
                dump(path,doc);return doc
            if time.monotonic()-wait_started>=300:
                dump(path,{'status':'ENVIRONMENT_BLOCKED','started_ns':started,'ended_ns':time.time_ns(),'samples':samples})
                raise RuntimeError('environment not quiet within 300 seconds; batch stopped')
            log(f'quiet guard waiting: busy={busy:.1%}')
            # Subsequent retries are two-second counter intervals.
            self.previous=None

class DevelopmentRun:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=False)
        self.batch=self.root.name;self.attempt='1';self.quiet=Quiet()
        self.assets={};self.asset_trust={};self.pair_trust={};self.pairs=[];self.aa_entries=[];self.aa_rows=[]
        self.completed=0;self.stage='preflight';self.raw=[];self.paired=[]
        self.protocol=gate.load(gate.PROTOCOL);self.protocol_sha=gate.sha(gate.PROTOCOL)
        env=self.protocol['environment'];self.pin=Path(env['pin_tool']);self.topology=Path(env['topology_tool'])
        self.binary=S1/'release/binaries/s1_native.exe';self.generator=S1/'src/workloads.hpp'
        self.configs={};self.inputs={}
    def receipt(self,name,files,**extra):
        path=self.root/'assets'/(name+'.json')
        doc={'schema':'S1.entry.asset.v1','asset':name,'test_fixture':False,'validated':True,
             'protocol_sha256':self.protocol_sha,'files':[bind(f) for f in files],**extra}
        dump(path,doc);self.assets[name]={'path':str(path)};self.asset_trust[name]={'sha256':gate.sha(path)}
        return path
    def preflight(self):
        git=lambda *a:subprocess.check_output(['git',*a],cwd=WORKSPACE).decode('utf8').strip()
        gate.require(not git('status','--porcelain'),'commit launcher and preserve a clean Git entry before running')
        git('rev-parse','s1-engineering-v1^{commit}')
        # Read archived approval and evidence; never rerun engineering suites.
        green=gate.load(S1/'S1_GREEN_记录.json');root=gate.load(S1/'S1_最终根核验_Git记录.json')
        gate.require(green['engineering_complete'] is True and root['status']=='COMPLETE_GREEN_AND_REVIEWS_APPROVED'
                     and root['outer_exit']==0 and root['tests']==77 and root['success_exits']==44,'archived engineering entry')
        frozen=gate.verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        self.source_sha=frozen['source_bundle_sha']
        manifest=gate.load(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        self.source_files={}
        for name,digest in manifest['source_sha'].items():
            normalized=name.replace('\\','/')
            if normalized.startswith('src/'):
                self.source_files['S1/'+normalized]=bind(S1/normalized)
        for name in manifest['frozen_dependencies']:self.source_files[name]=bind(S1.parents[1]/name)
        binaries=[]
        for name in ('s1_native.exe','s1_latency.exe','s1_resource.exe'):
            path=S1/'release/binaries'/name
            gate.require(gate.sha(path)==frozen['binary_sha'][name],'reviewed release binary differs')
            binaries.append({'name':name,**bind(path)})
        env=self.protocol['environment']
        gate.require(gate.sha(sys.executable)==env['pair_python_sha256'],'frozen Python differs')
        gate.require(gate.sha(env['compiler'])==env['compiler_sha256'],'frozen compiler differs')
        legacy=verify_legacy()
        topo,_=actual_process([str(self.topology),'--iters','1000'],self.root/'preflight','topology')
        rows=list(csv.DictReader(topo.split('#')[0].strip().splitlines()))
        gate.require(any(r['logical']=='3' and r['kind']=='P' and r['mask_hex']=='0x8' for r in rows),'required P core missing')
        for method in ['M_LIST',*DEV_CANDIDATES]:
            stdout,_=actual_process([str(self.pin),'0x8',str(self.binary),'describe','--method',method],self.root/'preflight',method)
            doc=json.loads(stdout)
            gate.require(doc['source_bundle_sha']==self.source_sha and doc['protocol_sha']==self.protocol_sha
                         and doc['binary_sha']==gate.sha(self.binary) and doc['process_mask']==8 and doc['logical_cpu']==3,'describe frozen identity/placement')
            path=self.root/'configs'/(method+'.json');path.parent.mkdir(exist_ok=True)
            data=config_bytes(stdout)
            gate.require(hashlib.sha256(data[:-1]).hexdigest()==doc['config_sha'],'exact C++ config bytes')
            with path.open('xb') as f:f.write(data)
            self.configs[method]={**bind(path),'logical_sha256':doc['config_sha']}
        self.frozen_R6=doc['config']['frozen_R6']
        self.receipt('frozen_binaries',[e['path'] for e in binaries],entries=binaries,source_bundle_sha=self.source_sha)
        self.receipt('protocol_and_sources',[gate.PROTOCOL,*[v['path'] for v in self.source_files.values()]],
                     source_bundle_sha=self.source_sha,frozen_R6=self.frozen_R6)
        self.frozen_files={name:bind(path) for name,path in [('binary',self.binary),('generator',self.generator),
                          ('protocol',gate.PROTOCOL),('pin',self.pin),('topology',self.topology)]}
        dump(self.root/'execution_manifest.json',{'schema':'S1.DEV.execution.v1','batch_id':self.batch,'profile':'dev',
             'git_commit':git('rev-parse','HEAD'),'engineering_tag':'s1-engineering-v1','S0_tag':'s0-freezable-v1',
             'R6_unchanged':True,'formal_experiments_authorized':False,'environment':env,'actual_platform':platform.platform(),
             'python':sys.executable,'legacy_rotation':legacy,'frozen_files':self.frozen_files,'source_files':self.source_files,
             'frozen_R6':self.frozen_R6,'planned_DEV_pairs':240,'planned_DEV_children':960,'planned_AA_children':160})
        log('preflight accepted: archived GREEN, frozen binaries/sources, Python/compiler, P core 3')
    def prepare(self):
        self.stage='input preparation';entries=[]
        cells=[('dev',f'D{i:02}',s) for i in range(1,11) for s in (90001,90002,90003)]
        cells += [('aa',c,92001) for c in ('D02','D06')]
        for profile,case,seed in cells:
            path=self.root/'inputs'/f'{profile}_{case}_{seed}'
            command=[str(self.binary),'prepare','--case',case,'--seed',str(seed),'--profile',profile,
                     '--protocol-sha',self.protocol_sha,'--output',str(path)]
            actual_process(command,self.root/'preparation',f'{profile}_{case}_{seed}')
            files={n:bind(path/f) for n,f in [('cache','cache.bin'),('expected','cache.expected.bin'),('meta','cache.meta.json')]}
            meta=gate.load(files['meta']['path']);cache=gate.cache_identity(files['cache']['path'],files['expected']['path'])
            gate._registered_cache(meta,cache)
            self.inputs[profile,case,seed]=files
            if profile=='dev':entries.append({'case_id':case,'seed':seed,'cache_path':files['cache']['path'],
                        'expected_path':files['expected']['path'],'metadata_path':files['meta']['path']})
        self.receipt('dev_trace_inventory',[v['path'] for (p,_,_),fs in self.inputs.items() if p=='dev' for v in fs.values()],entries=entries)
        log('prepared 30 registered DEV inputs + 2 AA inputs; full cache/reference identities verified')
    def run_pair(self,profile,case,seed,reference,candidate,pair_id,cell=None):
        files={**self.frozen_files,**self.inputs[profile,case,seed]}
        plans=command_plan(self.pin,self.binary,files['cache']['path'],files['cache']['sha256'],reference,candidate,
                           self.root/'children',self.batch,self.attempt,pair_id,cell=cell)
        pairroot=Path(plans[0]['command'][plans[0]['command'].index('--output')+1]).parent
        quietpath=pairroot/'quiet.json';self.quiet.check(quietpath)
        children=[];logical={}
        for i,p in enumerate(plans):
            command=p['command'];directory=Path(command[command.index('--output')+1])
            actual_process(command,directory,order_index=i);self.completed+=1
            gate.require(not (directory/'failure.json').exists(),'native failure sidecar')
            children.append({'path':str(directory),'files':{f.name:gate.sha(f) for f in directory.iterdir() if f.is_file()}})
            method=reference if p['role']=='A' else candidate
            gate.require(gate.load(directory/'config.json')==gate.load(self.configs[method]['path']),'executed config differs')
            logical[str(directory)]=gate.load(self.configs[method]['path'])
        lock=pairroot/'pair.lock.json'
        dump(lock,{'schema':'S1.pair.lock.v1','test_fixture':False,'mode':'native','profile':profile,
                   'batch_id':self.batch,'attempt_id':self.attempt,'pair_id':pair_id,'case_id':case,'seed':seed,
                   'reference':reference,'candidate':candidate,'source_bundle_sha':self.source_sha,
                   'files':{**files,'quiet':bind(quietpath)},'source_files':self.source_files,'children':children,'config_logical':logical})
        trust={'lock_sha256':gate.sha(lock),'protocol_sha256':self.protocol_sha,'source_bundle_sha':self.source_sha,
               **{name+'_sha256':b['sha256'] for name,b in self.frozen_files.items()},
               'config_sha256':{m:b['logical_sha256'] for m,b in self.configs.items()}}
        # Independent provenance file consumes preflight-frozen expectations,
        # actual process exits and newly sealed complete pair bytes.
        dumppath=pairroot/'pair.external_trust.json';dump(dumppath,trust)
        self.pair_trust[str(lock)]=gate.load(dumppath)
        out=gate.validate_pair(lock,trust=self.pair_trust[str(lock)])
        self.raw+=out['rows']
        self.paired.append({'profile':profile,'case_id':case,'seed':seed,'pair_id':pair_id,'reference':reference,
                            'candidate':candidate,**out['ratios'],'pair_path':str(lock)})
        return lock,out
    def aa(self,timepoint):
        self.stage='AA '+timepoint
        self.quiet.previous=None
        for method in ('M_LIST','M_EVENT_16'):
            for case in ('D02','D06'):
                for block in range(1,6):
                    pid=f'aa:{timepoint}:{method}:{case}:block{block}'
                    path,out=self.run_pair('aa',case,92001,method,method,pid)
                    self.aa_entries.append({'timepoint':timepoint,'method':method,'case_id':case,'block':block,
                                            'batch_id':self.batch,'pair_path':str(path)})
                    for row in out['rows']:
                        self.aa_rows.append({'timepoint':timepoint,'method':method,'case_id':case,'seed':92001,
                                 'block':block,'round':int(row['round']),'role':row['role'],'status':'valid',
                                 **{c:int(row[c+'_ns']) for c in ('build','online','total')}})
                log(f'AA {timepoint} {method} {case}: 5 complete blocks / 20 children')
    def environment_receipt(self):
        # A fresh actual environment check immediately before the start gate.
        q=self.quiet.check(self.root/'preflight'/'gate_quiet.json',reset=True)
        env={**q,'schema':'S1.environment.v1','test_fixture':False,'platform':'Windows','mask':8,'cpu':3,'group':0,
             'core_class':'P','quiet_api':'GetSystemTimes','initial_seconds':2,'min_subsequent_seconds':.2,
             'retry_seconds':2,'max_wait_seconds':300,'max_busy_fraction':.1,
             'topology_path':str(self.topology),'topology_sha256':self.frozen_files['topology']['sha256'],
             'pin_path':str(self.pin),'pin_sha256':self.frozen_files['pin']['sha256']}
        path=self.root/'assets/fresh_environment_receipt.json';dump(path,env)
        self.assets['fresh_environment_receipt']=str(path)
        self.asset_trust['fresh_environment_receipt']={'sha256':gate.sha(path)}
    def freeze_aa(self,complete=False):
        name='dev_aa_inventory';extras={'entries':self.aa_entries,'batch_id':self.batch,
                                      'environment_sha256':self.asset_trust['fresh_environment_receipt']['sha256']}
        if complete:
            before=self.assets[name]['path'];extras['before_inventory']=bind(before)
            extras['observed_floor']=analysis.aa_floor(self.aa_rows,'dev')
            path=self.root/'assets/dev_aa_inventory_complete.json'
            doc={**gate.load(before),**extras,'files':[bind(e['pair_path']) for e in self.aa_entries]}
            dump(path,doc);self.assets[name]={'path':str(path)};self.asset_trust[name]={'sha256':gate.sha(path)}
        else:self.receipt(name,[e['pair_path'] for e in self.aa_entries],**extras)
        self.asset_trust[name]['pair_trust']=dict(self.pair_trust)
    def start(self):
        self.stage='start gate';entries=[]
        dependencies=('frozen_binaries','protocol_and_sources','dev_trace_inventory','dev_aa_inventory','fresh_environment_receipt')
        bindings={n:bind(self.assets[n] if isinstance(self.assets[n],str) else self.assets[n]['path']) for n in dependencies}
        for case,seed,candidate in dev_cells():
            entries.append({'schema':'S1.start.pair.v1','status':'NOT_RUN','children':4,'batch_id':self.batch,
                  'profile':'dev','case_id':case,'seed':seed,'pair_id':candidate,'execution_pair_id':registered_pair_id(case,seed,candidate),
                  'reference':'M_LIST','candidate':candidate,'mode':'native','input':self.inputs['dev',case,seed],
                  'binary':self.frozen_files['binary'],'configs':{m:self.configs[m] for m in ('M_LIST',candidate)},
                  'source_bundle_sha':self.source_sha,'protocol_sha256':self.protocol_sha})
        self.receipt('start_manifest',[b['path'] for b in bindings.values()],bindings=bindings,status='NOT_RUN',
                     profile='dev',batch_id=self.batch,entries=entries)
        dump(self.root/'start_asset_trust.json',self.asset_trust)
        result=gate.readiness({'kernel':True,'driver':True,'analysis':True},self.assets,asset_trust=self.asset_trust,phase='start',scope='dev')
        dump(self.root/'DEV_START_GATE.json',result)
        gate.require(result['DEV_READY'] and not result['FINAL_READY'],'DEV start blocked: '+str(result['missing_dev_assets']))
        log('DEV_READY=true; starting frozen 240-pair matrix immediately')
    def matrix(self):
        self.stage='DEV matrix'
        for i,cell in enumerate(dev_cells(),1):
            case,seed,method=cell
            path,out=self.run_pair('dev',case,seed,'M_LIST',method,registered_pair_id(*cell),cell)
            self.pairs.append(str(path))
            if i%8==0:log(f'DEV complete {i}/240 pairs ({case}, seed {seed}); retained all results')
    def finish(self):
        self.stage='selection and completion gate';self.freeze_aa(True)
        dump(self.root/'pair_external_trust.json',self.pair_trust)
        selected=select(self.pairs,trust=self.pair_trust)
        selection=self.root/'dev_selection.json';write_selection(selection,selected)
        self.receipt('dev_selection',[selection],selection=bind(selection))
        self.asset_trust['dev_selection'].update(selection_sha256=gate.sha(selection),pair_trust=dict(self.pair_trust))
        dump(self.root/'complete_asset_trust.json',self.asset_trust)
        dump(self.root/'complete_assets.json',self.assets)
        result=gate.readiness({'kernel':True,'driver':True,'analysis':True},self.assets,asset_trust=self.asset_trust,phase='complete',scope='dev')
        dump(self.root/'DEV_COMPLETE_GATE.json',result)
        gate.require(result['DEV_READY'] and not result['FINAL_READY'],'DEV completion blocked: '+str(result['missing_dev_assets']))
        self.save_csv('raw_native_all.csv',self.raw)
        self.save_csv('paired_all.csv',self.paired)
        summaries=[]
        floor=analysis.aa_floor(self.aa_rows,'dev')
        for method in DEV_CANDIDATES:
            for component in ('build','online','total'):
                vals=[r[component] for r in self.paired if r['profile']=='dev' and r['candidate']==method]
                q25,q75=analysis.linear_quantile(vals,.25),analysis.linear_quantile(vals,.75)
                summaries.append({'method':method,'component':component,'n_inputs':len(vals),'median_ratio':analysis.linear_quantile(vals,.5),
                         'q25':q25,'q75':q75,'IQR':q75-q25,'wins':sum(x<1 for x in vals),'AA_log_floor':floor[component],
                         'outside_floor_fast':sum(math.log(x)<-floor[component] for x in vals),
                         'outside_floor_slow':sum(math.log(x)>floor[component] for x in vals),
                         'mean_log_total_objective':selected['scores'][method]})
        self.save_csv('dev_summary.csv',summaries)
        self.save_csv('dev_scores.csv',[{'method':m,'score':s,'total_geometric_mean_ratio':math.exp(s)} for m,s in selected['scores'].items()])
        dump(self.root/'completion.json',{'status':'DEV_COMPLETE','batch_id':self.batch,'DEV_pairs':240,'DEV_children':960,
                  'AA_children':160,'actual_timing_children':self.completed,'selected_theta':selected['selected_theta'],
                  'selected_h':selected['selected_h'],'AA_floor':floor,'FINAL_READY':False,'formal_children':0,
                  'all_negative_results_retained':True,'R6_unchanged':True,'ended_ns':time.time_ns()})
        log(f'DEV complete: theta={selected["selected_theta"]}, h={selected["selected_h"]}; final experiments not started')
    def save_csv(self,name,rows):
        if not rows:return
        with (self.root/name).open('x',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    def run(self):
        try:
            self.preflight();self.prepare();self.aa('before');self.environment_receipt();self.freeze_aa();self.start()
            self.matrix();self.aa('after');self.finish()
        except Exception as e:
            dump(self.root/'batch_blocker.json',{'status':'STOPPED_ACTUAL_BLOCKER','stage':self.stage,'error':str(e),
                 'traceback':traceback.format_exc(),'actual_timing_children':self.completed,'completed_DEV_pairs':len(self.pairs),
                 'formal_children':0,'failed_assets_retained':True,'timestamp_ns':time.time_ns()})
            self.save_csv('raw_partial.csv',self.raw);self.save_csv('paired_partial.csv',self.paired)
            log(f'STOPPED actual blocker in {self.stage}: {e}');raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    DevelopmentRun(args.output).run()

if __name__=='__main__':main()
