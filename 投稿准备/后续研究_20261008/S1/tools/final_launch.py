"""Execute the frozen S0 final native matrix with independent final inputs.

Reuses the reviewed AB/BA process adapter and production gates. No changes to
native code, workloads, statistical rules, or write-once DEV selection.
Git identifies versions; legacy integrity bindings remain gate inputs.
"""
from pathlib import Path
import argparse
import copy
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback

import analysis
import entry_gate as gate
from dev_launch import (DevelopmentRun, S1, WORKSPACE, actual_process, bind,
                        config_bytes, dump, log)
from pair_adapter import FORMAL_LABELS, registered_pair_id, verify_legacy

def formal_cells():
    return [(f'F{i:02}',seed,label) for i in range(1,8)
            for seed in range(91001,91011) for label in FORMAL_LABELS]

def formal_methods(theta, h):
    gate.require(theta in (8,16,32,64) and h in (128,512,2048,8192),'registered DEV thresholds required')
    return {'P01':('Original','M_LIST'),'P02':('M_LIST','M_OBSERVE_LIST'),
            'P03':('M_LIST','R6'),'P04':('M_OBSERVE_LIST','R6'),
            'P05':('Original','R6'),'P06':(f'M_EVENT_{theta}','R6'),
            'P07':(f'M_FIXED_{h}','R6'),'P08':('M_NO_IDLE','R6'),
            'DIA01':('M_EVENT_16','R6'),'DIA02':('M_FIXED_128','R6')}

def historical_assets(assets, trust):
    assets,trust=copy.deepcopy(assets),copy.deepcopy(trust)
    assets['dev_environment_receipt']=assets['fresh_environment_receipt']
    trust['dev_environment_receipt']=copy.deepcopy(trust['fresh_environment_receipt'])
    return assets,trust

class FinalRun(DevelopmentRun):
    def __init__(self,root,dev_root):
        super().__init__(root)
        self.dev_root=Path(dev_root).resolve()
        self.assets,self.asset_trust=historical_assets(
            gate.load(self.dev_root/'complete_assets.json'),gate.load(self.dev_root/'complete_asset_trust.json'))
        self.selection_path=self.dev_root/'dev_selection.json'
        self.selection=gate.load(self.selection_path)
        self.methods=formal_methods(self.selection['selected_theta'],self.selection['selected_h'])
        external=self.asset_trust['dev_selection']
        self.selection_trust={'sha256':external['selection_sha256'],'pair_trust':external['pair_trust']}

    def preflight(self):
        git=lambda *a:subprocess.check_output(['git',*a],cwd=WORKSPACE).decode('utf8').strip()
        gate.require(not git('status','--porcelain'),'commit launcher and preserve a clean Git entry before running')
        git('rev-parse','s1-dev-v1^{commit}')
        green=gate.load(S1/'S1_GREEN_记录.json');root=gate.load(S1/'S1_最终根核验_Git记录.json')
        gate.require(green['engineering_complete'] is True and root['status']=='COMPLETE_GREEN_AND_REVIEWS_APPROVED'
                     and root['outer_exit']==0 and root['tests']==77 and root['success_exits']==44,'archived engineering entry')
        dev=gate.load(self.dev_root/'DEV_COMPLETE_GATE.json')
        gate.require(dev['DEV_READY'] and not dev['FINAL_READY'],'complete production DEV evidence required')
        frozen=gate.verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        self.source_sha=frozen['source_bundle_sha']
        manifest=gate.load(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        self.source_files={}
        for name in manifest['source_sha']:
            normalized=name.replace('\\','/')
            if normalized.startswith('src/'):
                self.source_files['S1/'+normalized]=bind(S1/normalized)
        for name in manifest['frozen_dependencies']:self.source_files[name]=bind(S1.parents[1]/name)
        for name in ('s1_native.exe','s1_latency.exe','s1_resource.exe'):
            gate.require(gate.sha(S1/'release/binaries'/name)==frozen['binary_sha'][name],'reviewed release binary differs')
        env=self.protocol['environment']
        gate.require(gate.sha(sys.executable)==env['pair_python_sha256'],'frozen Python differs')
        gate.require(gate.sha(env['compiler'])==env['compiler_sha256'],'frozen compiler differs')
        gate.require(gate.sha(self.protocol['dataset']['path'])==self.protocol['dataset']['sha256'],'public dataset differs')
        gate.require(gate.sha(self.selection_path)==self.selection_trust['sha256'],'write-once DEV selection differs')
        legacy=verify_legacy()
        topo,_=actual_process([str(self.topology),'--iters','1000'],self.root/'preflight','topology')
        rows=list(csv.DictReader(topo.split('#')[0].strip().splitlines()))
        gate.require(any(r['logical']=='3' and r['kind']=='P' and r['mask_hex']=='0x8' for r in rows),'required P core missing')
        for method in sorted({m for pair in self.methods.values() for m in pair}):
            stdout,_=actual_process([str(self.pin),'0x8',str(self.binary),'describe','--method',method],self.root/'preflight',method)
            doc=json.loads(stdout)
            gate.require(doc['source_bundle_sha']==self.source_sha and doc['protocol_sha']==self.protocol_sha
                         and doc['binary_sha']==gate.sha(self.binary) and doc['process_mask']==8 and doc['logical_cpu']==3,'describe frozen identity/placement')
            path=self.root/'configs'/(method+'.json');path.parent.mkdir(exist_ok=True)
            data=config_bytes(stdout)
            gate.require(hashlib.sha256(data[:-1]).hexdigest()==doc['config_sha'],'exact C++ config bytes')
            with path.open('xb') as f:f.write(data)
            self.configs[method]={**bind(path),'logical_sha256':doc['config_sha']}
            if method in self.selection['method_config_sha256']:
                gate.require(doc['config_sha']==self.selection['method_config_sha256'][method],'DEV/formal config differs')
        self.frozen_R6=doc['config']['frozen_R6']
        self.frozen_files={name:bind(path) for name,path in [('binary',self.binary),('generator',self.generator),
                          ('protocol',gate.PROTOCOL),('pin',self.pin),('topology',self.topology)]}
        dump(self.root/'execution_manifest.json',{'schema':'S1.FINAL.execution.v1','batch_id':self.batch,'profile':'final',
             'git_commit':git('rev-parse','HEAD'),'DEV_tag':'s1-dev-v1','engineering_tag':'s1-engineering-v1','S0_tag':'s0-freezable-v1',
             'R6_unchanged':True,'environment':env,'actual_platform':platform.platform(),
             'python':sys.executable,'legacy_rotation':legacy,'frozen_files':self.frozen_files,'source_files':self.source_files,
             'frozen_R6':self.frozen_R6,'selected_theta':self.selection['selected_theta'],'selected_h':self.selection['selected_h'],
             'selection':bind(self.selection_path),'planned_formal_pairs':700,'planned_formal_children':2800,'planned_AA_children':360})
        bindings={n:bind(self.assets[n]['path']) for n in ('dev_selection','frozen_binaries','protocol_and_sources')}
        entries=[]
        for method in (f"M_EVENT_{self.selection['selected_theta']}",f"M_FIXED_{self.selection['selected_h']}"):
            entries.append({'schema':'S1.selected.config.v1','method':method,'mode':'native','protocol_sha256':self.protocol_sha,
                'source_bundle_sha':self.source_sha,'binary':self.frozen_files['binary'],'config':self.configs[method],
                'selected_theta':self.selection['selected_theta'] if method.startswith('M_EVENT_') else None,
                'selected_h':self.selection['selected_h'] if method.startswith('M_FIXED_') else None})
        self.receipt('selected_configs',[* [b['path'] for b in bindings.values()],* [e['config']['path'] for e in entries]],
                     bindings=bindings,entries=entries)
        log('preflight accepted: frozen production binaries, DEV selection, data, compiler/Python, P core 3')

    def prepare(self):
        self.stage='independent final input preparation';entries=[]
        cells=[('final',f'F{i:02}',s) for i in range(1,8) for s in range(91001,91011)]
        cells += [('aa',c,92001) for c in ('F01','F03','F06')]
        for i,(profile,case,seed) in enumerate(cells,1):
            path=self.root/'inputs'/f'{profile}_{case}_{seed}'
            command=[str(self.binary),'prepare','--case',case,'--seed',str(seed),'--profile',profile,
                     '--protocol-sha',self.protocol_sha,'--output',str(path)]
            log(f'prepare {i}/73: {profile} {case} {seed}')
            actual_process(command,self.root/'preparation',f'{profile}_{case}_{seed}')
            files={n:bind(path/f) for n,f in [('cache','cache.bin'),('expected','cache.expected.bin'),('meta','cache.meta.json')]}
            meta=gate.load(files['meta']['path']);cache=gate.cache_identity(files['cache']['path'],files['expected']['path'])
            gate._registered_cache(meta,cache)
            self.inputs[profile,case,seed]=files
            if profile=='final':entries.append({'case_id':case,'seed':seed,'cache_path':files['cache']['path'],
                        'expected_path':files['expected']['path'],'metadata_path':files['meta']['path']})
        self.receipt('formal_trace_inventory',[v['path'] for (p,_,_),fs in self.inputs.items() if p=='final' for v in fs.values()],entries=entries)
        log('prepared and fully verified 70 independent formal inputs + 3 AA inputs')

    def aa(self,timepoint):
        self.stage='formal AA '+timepoint;self.quiet.previous=None
        for method in ('Original','M_LIST','R6'):
            for case in ('F01','F03','F06'):
                for block in range(1,6):
                    path,out=self.run_pair('aa',case,92001,method,method,f'aa:{timepoint}:{method}:{case}:block{block}')
                    self.aa_entries.append({'timepoint':timepoint,'method':method,'case_id':case,'block':block,
                                           'batch_id':self.batch,'pair_path':str(path)})
                    for row in out['rows']:
                        self.aa_rows.append({'timepoint':timepoint,'method':method,'case_id':case,'seed':92001,
                             'block':block,'round':int(row['round']),'role':row['role'],'status':'valid',
                             **{c:int(row[c+'_ns']) for c in ('build','online','total')}})
                log(f'formal AA {timepoint} {method} {case}: 5 complete blocks / 20 children')

    def freeze_aa(self,complete=False):
        name='formal_aa_inventory';extras={'entries':list(self.aa_entries),'batch_id':self.batch,
                          'environment_sha256':self.asset_trust['fresh_environment_receipt']['sha256']}
        if complete:
            before=self.assets[name]['path'];extras['before_inventory']=bind(before)
            extras['observed_floor']=analysis.aa_floor(self.aa_rows,'final')
            path=self.root/'assets/formal_aa_inventory_complete.json'
            dump(path,{**gate.load(before),**extras,'files':[bind(e['pair_path']) for e in self.aa_entries]})
            self.assets[name]={'path':str(path)};self.asset_trust[name]={'sha256':gate.sha(path)}
        else:self.receipt(name,[e['pair_path'] for e in self.aa_entries],**extras)
        self.asset_trust[name]['pair_trust']=dict(self.pair_trust)

    def start(self):
        self.stage='formal start gate';entries=[]
        dependencies=('frozen_binaries','protocol_and_sources','formal_trace_inventory','formal_aa_inventory',
                      'fresh_environment_receipt','dev_selection','selected_configs')
        bindings={n:bind(self.assets[n] if isinstance(self.assets[n],str) else self.assets[n]['path']) for n in dependencies}
        for cell in formal_cells():
            case,seed,label=cell;reference,candidate=self.methods[label]
            entries.append({'schema':'S1.start.pair.v1','status':'NOT_RUN','children':4,'batch_id':self.batch,
                  'profile':'final','case_id':case,'seed':seed,'pair_id':label,'execution_pair_id':registered_pair_id(*cell),
                  'reference':reference,'candidate':candidate,'mode':'native','input':self.inputs['final',case,seed],
                  'binary':self.frozen_files['binary'],'configs':{m:self.configs[m] for m in (reference,candidate)},
                  'source_bundle_sha':self.source_sha,'protocol_sha256':self.protocol_sha})
        self.receipt('final_start_manifest',[b['path'] for b in bindings.values()],bindings=bindings,status='NOT_RUN',
                     profile='final',batch_id=self.batch,entries=entries)
        dump(self.root/'start_asset_trust.json',self.asset_trust);dump(self.root/'start_assets.json',self.assets)
        result=gate.readiness({'kernel':True,'driver':True,'analysis':True},self.assets,asset_trust=self.asset_trust,phase='start',scope='final')
        dump(self.root/'FINAL_START_GATE.json',result)
        gate.require(result['FINAL_READY'],'formal start blocked: '+str(result['missing_dev_assets']+result['missing_final_assets']))
        log('FINAL_READY=true; starting frozen independent 700-pair matrix immediately')

    def matrix(self):
        self.stage='formal matrix'
        for i,cell in enumerate(formal_cells(),1):
            case,seed,label=cell;reference,candidate=self.methods[label]
            path,out=self.run_pair('final',case,seed,reference,candidate,registered_pair_id(*cell),cell)
            self.pairs.append(path)
            log(f'formal {i}/700 {case}:{seed}:{label} complete; total ratio={out["ratios"]["total"]:.4f}; {self.completed} children')

    def finish(self):
        self.stage='formal completion gate';self.freeze_aa(complete=True)
        entries=[{'case_id':c,'seed':s,'pair_id':p,'execution_pair_id':registered_pair_id(c,s,p),'pair_path':str(path)}
                 for (c,s,p),path in zip(formal_cells(),self.pairs)]
        self.receipt('formal_matrix_inventory',self.pairs,entries=entries,status='COMPLETE',batch_id=self.batch,
                     selection=bind(self.selection_path))
        self.asset_trust['formal_matrix_inventory'].update(pair_trust=dict(self.pair_trust),selection_trust=self.selection_trust)
        dump(self.root/'pair_external_trust.json',self.pair_trust)
        dump(self.root/'complete_asset_trust.json',self.asset_trust);dump(self.root/'complete_assets.json',self.assets)
        # Frozen gate validates all 700 full pair archives, DEV selection and
        # both formal AA timepoints. Mathematical summaries consume that exact
        # fully validated matrix once; no arbitrary ratios or fixture authority.
        result=gate.readiness({'kernel':True,'driver':True,'analysis':True},self.assets,asset_trust=self.asset_trust,phase='complete',scope='final')
        dump(self.root/'FINAL_COMPLETE_GATE.json',result)
        gate.require(result['FINAL_READY'],'formal completion blocked: '+str(result['missing_dev_assets']+result['missing_final_assets']))
        self.save_csv('raw_native_all.csv',self.raw);self.save_csv('paired_all.csv',self.paired)
        self.save_csv('aa_all.csv',self.aa_rows)
        floor=analysis.aa_floor(self.aa_rows,'final')
        gate.require(result['formal_aa_log_floor']==floor,'complete-gate/summary AA identity')
        summaries=[]
        for case in (f'F{i:02}' for i in range(1,8)):
            for label in FORMAL_LABELS:
                rows=[r for r in self.paired if r['profile']=='final' and r['case_id']==case and r['pair_id'].endswith(':'+label)]
                gate.require(len(rows)==10 and {r['seed'] for r in rows}==set(range(91001,91011)),'summary registered ten-seed cell')
                gate.require(all((r['reference'],r['candidate'])==self.methods[label] for r in rows),'summary methods')
                for component in ('build','online','total'):
                    summaries.append({**analysis.summarize([r[component] for r in rows],label,case,component,floor[component]),
                                      'reference':self.methods[label][0],'candidate':self.methods[label][1]})
        self.save_csv('group_summary.csv',summaries)
        dump(self.root/'completion.json',{'status':'FINAL_NATIVE_COMPLETE','batch_id':self.batch,'formal_pairs':700,
              'formal_children':2800,'AA_children':360,'actual_timing_children':self.completed,
              'selected_theta':self.selection['selected_theta'],'selected_h':self.selection['selected_h'],
              'AA_floor':floor,'FINAL_READY':True,'all_negative_results_retained':True,'R6_unchanged':True,
              'summary_scope':'complete production gate, then frozen analysis.summarize for each exact registered cell',
              'separate_resource_latency_diagnostics_executed':False,'ended_ns':time.time_ns()})
        log('formal native matrix complete; all 700 pairs and 360 AA children retained; no retuning')

    def run(self):
        try:
            self.preflight();self.prepare();self.aa('before');self.environment_receipt();self.freeze_aa();self.start()
            self.matrix();self.aa('after');self.finish()
        except Exception as e:
            dump(self.root/'batch_blocker.json',{'status':'STOPPED_ACTUAL_BLOCKER','stage':self.stage,'error':str(e),
                 'traceback':traceback.format_exc(),'actual_timing_children':self.completed,'completed_formal_pairs':len(self.pairs),
                 'failed_assets_retained':True,'timestamp_ns':time.time_ns()})
            self.save_csv('raw_partial.csv',self.raw);self.save_csv('paired_partial.csv',self.paired)
            log(f'STOPPED actual blocker in {self.stage}: {e}');raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--dev-root',required=True)
    args=p.parse_args();FinalRun(args.output,args.dev_root).run()

if __name__=='__main__':main()
