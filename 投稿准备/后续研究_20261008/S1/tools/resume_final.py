"""Resume a frozen final batch without repeating complete verified pairs.

The preregistration explicitly permits complete hash-matching pair recovery.
Old input, before-AA and start receipts stay immutable. A fresh resume quiet
receipt and per-pair guards precede new timing. No result-dependent selection.
"""
from pathlib import Path
import argparse
import copy
import csv
import subprocess
import sys
import time
import traceback
import entry_gate as gate
from dev_launch import S1, WORKSPACE, Quiet, actual_process, bind, dump, log
from final_launch import FinalRun, formal_cells, formal_methods
from pair_adapter import registered_pair_id

def sealed_prefix(cells, present):
    cells=list(cells);present=set(present)
    gate.require(present<=set(cells),'unregistered sealed recovery cell')
    count=0
    while count<len(cells) and cells[count] in present:count+=1
    gate.require(present==set(cells[:count]),'sealed recovery cells must be a chronological prefix')
    return count

class ResumedRun(FinalRun):
    def __init__(self,original,output):
        self.original=Path(original).resolve();self.root=Path(output).resolve()
        self.root.mkdir(parents=True,exist_ok=False)
        self.manifest=gate.load(self.original/'execution_manifest.json')
        self.batch=self.manifest['batch_id'];self.attempt='2';self.quiet=Quiet()
        self.assets=copy.deepcopy(gate.load(self.original/'start_assets.json'))
        self.asset_trust=copy.deepcopy(gate.load(self.original/'start_asset_trust.json'))
        self.pair_trust={};self.pairs=[];self.aa_entries=[];self.aa_rows=[];self.raw=[];self.paired=[]
        self.completed=0;self.stage='resume preflight';self.protocol=gate.load(gate.PROTOCOL)
        self.protocol_sha=gate.sha(gate.PROTOCOL);self.frozen_files=self.manifest['frozen_files']
        self.source_files=self.manifest['source_files'];self.frozen_R6=self.manifest['frozen_R6']
        self.source_sha=gate.load(self.assets['protocol_and_sources']['path'])['source_bundle_sha']
        self.pin=Path(self.frozen_files['pin']['path']);self.topology=Path(self.frozen_files['topology']['path'])
        self.binary=Path(self.frozen_files['binary']['path']);self.generator=Path(self.frozen_files['generator']['path'])
        self.selection_path=Path(self.manifest['selection']['path']);self.selection=gate.load(self.selection_path)
        self.methods=formal_methods(self.selection['selected_theta'],self.selection['selected_h'])
        external=self.asset_trust['dev_selection']
        self.selection_trust={'sha256':external['selection_sha256'],'pair_trust':external['pair_trust']}
        self.inputs={};self.configs={}
        self.plan=gate.load(self.assets['final_start_manifest']['path'])
        for e in self.plan['entries']:
            self.inputs['final',e['case_id'],e['seed']]=e['input']
            for method,binding in e['configs'].items():
                gate.require(self.configs.setdefault(method,binding)==binding,'recovery config identity')
        self.prefix=0;self.incomplete=[]

    def preflight(self):
        git=lambda *a:subprocess.check_output(['git',*a],cwd=WORKSPACE).decode('utf8').strip()
        gate.require(not git('status','--porcelain'),'commit recovery tools before resuming')
        entry=gate.load(self.original/'FINAL_START_GATE.json')
        gate.require(entry['FINAL_READY'] and not entry['missing_dev_assets'] and not entry['missing_final_assets'],'original production start gate required')
        gate.require(not (self.original/'completion.json').exists(),'completed original batch cannot be resumed')
        frozen=gate.verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        gate.require(frozen['source_bundle_sha']==self.source_sha and frozen['binary_sha']['s1_native.exe']==self.frozen_files['binary']['sha256'],'frozen recovery source/binary')
        for binding in [*self.frozen_files.values(),*self.source_files.values(),self.manifest['selection']]:gate._file_binding(binding)
        for name,external in self.asset_trust.items():
            value=self.assets[name];path=value if isinstance(value,str) else value['path']
            gate.require(gate.sha(path)==external['sha256'],'original recovery asset differs: '+name)
            doc=gate.load(path)
            for binding in doc.get('files',[]):gate._file_binding(binding)
        env=self.protocol['environment']
        gate.require(gate.sha(sys.executable)==env['pair_python_sha256'] and gate.sha(env['compiler'])==env['compiler_sha256'],'frozen runtime/compiler')
        gate.require(gate.sha(self.protocol['dataset']['path'])==self.protocol['dataset']['sha256'],'frozen data')
        for binding in self.configs.values():gate._file_binding(binding)
        stdout,_=actual_process([str(self.topology),'--iters','1000'],self.root/'preflight','topology')
        rows=list(csv.DictReader(stdout.split('#')[0].strip().splitlines()))
        gate.require(any(r['logical']=='3' and r['kind']=='P' and r['mask_hex']=='0x8' for r in rows),'required P core missing')
        self.resume_commit=git('rev-parse','HEAD')
        log('resume preflight accepted: original gate, exact frozen native source/data/configs/runtime; no engineering rerun')

    def restore_pair(self,path,cell=None):
        path=Path(path);external=path.parent/'pair.external_trust.json'
        gate.require(external.exists(),'unsealed recovery external trust')
        trust=gate.load(external)
        for name,binding in self.frozen_files.items():
            gate.require(trust[name+'_sha256']==binding['sha256'],'recovery frozen file trust')
        gate.require(trust['source_bundle_sha']==self.source_sha and trust['protocol_sha256']==self.protocol_sha,'recovery protocol/source trust')
        for method,binding in self.configs.items():gate.require(trust['config_sha256'][method]==binding['logical_sha256'],'recovery config trust')
        out=gate.validate_pair(path,trust=trust)
        gate.require(out['batch_id']==self.batch and out['mode']=='native','recovery production batch identity')
        if cell is not None:
            case,seed,label=cell
            gate.require((out['case_id'],out['seed'],out['pair_id'],out['reference'],out['candidate'])==
                         (case,seed,registered_pair_id(*cell),*self.methods[label]),'recovery registered methods/input')
            self.pairs.append(path)
        self.pair_trust[str(path.resolve())]=trust;self.raw+=out['rows'];self.completed+=4
        self.paired.append({'profile':out['profile'],'case_id':out['case_id'],'seed':out['seed'],
                'pair_id':out['pair_id'],'reference':out['reference'],'candidate':out['candidate'],
                **out['ratios'],'pair_path':str(path)})
        return out

    def restore(self):
        self.stage='complete sealed pair recovery';records=[]
        before=gate.load(self.assets['formal_aa_inventory']['path'])
        gate.require(len(before['entries'])==45,'original complete before AA required')
        for i,e in enumerate(before['entries'],1):
            out=self.restore_pair(e['pair_path'])
            gate._aa_pair_identity(out,e)
            self.aa_entries.append(e)
            lock=gate.load(e['pair_path'])
            self.inputs['aa',e['case_id'],92001]={k:lock['files'][k] for k in ('cache','expected','meta')}
            for row in out['rows']:
                self.aa_rows.append({'timepoint':'before','method':e['method'],'case_id':e['case_id'],'seed':92001,
                        'block':e['block'],'round':int(row['round']),'role':row['role'],'status':'valid',
                        **{c:int(row[c+'_ns']) for c in ('build','online','total')}})
            if i%5==0:log(f'restored and fully verified before AA {i}/45 blocks; no timing repeated')
        cells=formal_cells();present=set()
        for cell in cells:
            directory=self.original/'children'/registered_pair_id(*cell).replace(':','_')
            if (directory/'pair.lock.json').exists():present.add(cell)
            elif directory.exists():self.incomplete.append({'cell':list(cell),'directory':str(directory),'reason':'no sealed whole-pair lock; retained and excluded'})
        self.prefix=sealed_prefix(cells,present)
        gate.require(all(tuple(e['cell'])==cells[self.prefix] for e in self.incomplete),'only next interrupted pair can be incomplete')
        for i,cell in enumerate(cells[:self.prefix],1):
            path=self.original/'children'/registered_pair_id(*cell).replace(':','_')/'pair.lock.json'
            out=self.restore_pair(path,cell);records.append((cell,out))
            if i%10==0 or cell[0]=='F03':log(f'restored formal {i}/{self.prefix}: {registered_pair_id(*cell)}; full pair verified, not rerun')
        if records:gate.validate_batch(records,scope='final')
        dump(self.root/'recovery_receipt.json',{'schema':'S1.FINAL.recovery.v1','original_run':str(self.original),
             'original_execution_git_commit':self.manifest['git_commit'],'resume_git_commit':self.resume_commit,
             'batch_id':self.batch,'new_attempt_id':self.attempt,'reused_formal_pairs':self.prefix,
             'reused_before_AA_pairs':45,'reused_accepted_children':self.completed,'incomplete_pairs_retained':self.incomplete,
             'interruption_cause':'undetermined; original process has no final exit receipt',
             'selection_changed':False,'native_source_changed':False,'negative_results_discarded':False,'verified_ns':time.time_ns()})
        dump(self.root/'execution_manifest.json',{**self.manifest,'resume_git_commit':self.resume_commit,
             'original_run':str(self.original),'resume_attempt_id':self.attempt,'recovery_receipt':bind(self.root/'recovery_receipt.json')})

    def resume_environment(self):
        self.stage='fresh resume environment'
        q=self.quiet.check(self.root/'preflight/resume_quiet.json',reset=True)
        env={**q,'schema':'S1.environment.v1','test_fixture':False,'platform':'Windows','mask':8,'cpu':3,'group':0,
             'core_class':'P','quiet_api':'GetSystemTimes','initial_seconds':2,'min_subsequent_seconds':.2,
             'retry_seconds':2,'max_wait_seconds':300,'max_busy_fraction':.1,
             'topology_path':str(self.topology),'topology_sha256':self.frozen_files['topology']['sha256'],
             'pin_path':str(self.pin),'pin_sha256':self.frozen_files['pin']['sha256']}
        path=self.root/'resume_environment_receipt.json';dump(path,env);gate.verify_environment(path)
        # Keep the original before-AA/start cross bindings unchanged. This fresh
        # additional resume receipt validates the new environment separately.
        dump(self.root/'RESUME_START_GATE.json',{'status':'RESUME_READY','schema':'S1.FINAL.resume.gate.v1',
             'original_start_gate':bind(self.original/'FINAL_START_GATE.json'),'recovery_receipt':bind(self.root/'recovery_receipt.json'),
             'fresh_environment':bind(path),'prefix_pairs':self.prefix,'remaining_pairs':700-self.prefix,
             'parameters_unchanged':True,'native_source_unchanged':True})
        log(f'RESUME_READY: {self.prefix} complete formal pairs reused; {700-self.prefix} remaining; same frozen configuration')

    def matrix(self):
        self.stage='resumed formal matrix'
        for i,cell in enumerate(formal_cells()[self.prefix:],self.prefix+1):
            case,seed,label=cell;reference,candidate=self.methods[label]
            path,out=self.run_pair('final',case,seed,reference,candidate,registered_pair_id(*cell),cell)
            self.pairs.append(path)
            log(f'formal {i}/700 {registered_pair_id(*cell)} complete; total ratio={out["ratios"]["total"]:.4f}; {self.completed} accepted children')

    def run(self):
        try:
            self.preflight();self.restore();self.resume_environment();self.matrix();self.aa('after');self.finish()
        except Exception as e:
            dump(self.root/'batch_blocker.json',{'status':'STOPPED_ACTUAL_BLOCKER','stage':self.stage,'error':str(e),
                 'traceback':traceback.format_exc(),'accepted_children':self.completed,'complete_formal_pairs':len(self.pairs),
                 'failed_assets_retained':True,'timestamp_ns':time.time_ns()})
            self.save_csv('raw_partial.csv',self.raw);self.save_csv('paired_partial.csv',self.paired)
            log(f'STOPPED actual blocker in {self.stage}: {e}');raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--original',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();ResumedRun(a.original,a.output).run()

if __name__=='__main__':main()
