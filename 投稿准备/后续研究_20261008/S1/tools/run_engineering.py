"""Whitelisted S1 correctness/fixture evidence runner. Never runs a benchmark.

Each tag is immutable. Every subprocess has a 55-second timeout; stdout, stderr,
command, exit, timings, source snapshots and SHA256 are retained, including failures.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from entry_gate import sha, load, verify_driver, verify_kernel, readiness

S1=Path(__file__).resolve().parents[1]
NEW_FILES=[*[f'tools/{x}.py' for x in ('analysis','entry_gate','pair_adapter','select_dev','run_engineering')],
           *[f'tests/{x}.py' for x in ('test_analysis','red_analysis','analysis_fixture')]]
PYTHON_SHA='10d845f50a2af64e3500bb2fcb348b5bc98a75d8ddada63e45ba1da6a1fc79d1'

def arguments(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag',required=True);p.add_argument('--task',choices=['fixtures','red','entry'],default='fixtures')
    args=p.parse_args(argv)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',args.tag):raise ValueError('immutable tag must be a simple identifier')
    return args

def _save(path,obj):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def run(args):
    require_python=sha(sys.executable)
    if require_python!=PYTHON_SHA:raise ValueError('frozen Python required')
    out=S1/'artifacts'/'analysis'/args.tag;out.mkdir(parents=True,exist_ok=False)
    source={}
    for name in NEW_FILES:
        p=S1/name;q=out/'source'/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q);source[name]=sha(p)
    s0={str(p.relative_to(S1.parent)):sha(p) for p in [S1.parent/'S0'/x for x in
         ('S0_同布局比较合约_v1.md','S0_实验预注册_v1.md','S0_preregistration.json','S0_测试与指标覆盖矩阵.csv')]}
    commands=[];tests=0;good=True
    cases=['gm','decision','selection','sidecar'] if args.task=='red' else ['Statistics','Sidecar',*[f'Prepare{i}' for i in range(8)],'Selection','AdapterGate'] if args.task=='fixtures' else ['AdapterGate']
    for case in cases:
        command=[sys.executable,'-B',str(S1/'tests'/'test_analysis.py'),'--scratch-output',str(out/'scratch')]
        if case.startswith('Prepare'):
            command+=['--prepare-batch',case[7:],'--fixture-output',str(out/'dev_fixture')]
        else:
            command+=['--red' if args.task=='red' else '--case',case]
            if case=='Selection':command+=['--fixture-output',str(out/'dev_fixture')]
        process={'command':command,'cwd':str(S1),'started_ns':time.time_ns(),'timeout_seconds':55,'test_fixture':True}
        try:
            result=subprocess.run(command,cwd=S1,capture_output=True,timeout=55,env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})
            stdout,stderr=result.stdout,result.stderr;process['exit_code']=result.returncode
        except subprocess.TimeoutExpired as e:
            stdout=e.stdout or b'';stderr=(e.stderr or b'')+b'\nENGINEERING_TIMEOUT_55_SECONDS\n';process['exit_code']=124
        process['ended_ns']=time.time_ns();(out/(case+'.stdout.txt')).write_bytes(stdout);(out/(case+'.stderr.txt')).write_bytes(stderr)
        _save(out/(case+'.process.json'),process);commands.append(process)
        text=stderr.decode('utf-8',errors='replace');count=re.search(r'Ran (\d+) test',text);tests+=int(count.group(1)) if count else 0
        if args.task=='red':passed=process['exit_code']==1 and 'AssertionError' in text and 'FAIL:' in text and 'ImportError' not in text
        else:passed=process['exit_code']==0 and re.search(r'\nOK\s*$',text) is not None
        good=good and passed;print(f'{case}: exit={process["exit_code"]} expected_behavior={passed}',flush=True)
    actual_driver=actual_kernel=None
    if good and args.task!='red':
        actual_driver=verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        actual_kernel=verify_kernel(S1/'artifacts/kernel/green_coverage_fix_01/manifest.json')
        candidate={'schema':'S1.entry.candidate.v1','test_fixture':True,'origin':'ENGINEERING_STATIC_VALIDATION_ONLY',
                   'driver':actual_driver,'kernel':actual_kernel,
                   'status':readiness({'kernel':True,'driver':True,'analysis':args.task=='fixtures'},{}),
                   'experiments_executed':0,'fresh_environment_executed':False}
        _save(out/'entry_validation_fixture.json',candidate)
    for name,digest in source.items():
        if sha(S1/name)!=digest or sha(out/'source'/name)!=digest:good=False
    for name,digest in s0.items():
        if sha(S1.parent/name)!=digest:good=False
    evidence={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and 'source' not in p.relative_to(out).parts}
    manifest={'schema':'S1.analysis.engineering.v1','tag':args.tag,'task':args.task,
              'status':'EXPECTED_BEHAVIOR_RED' if good and args.task=='red' else 'ENGINEERING_GREEN' if good else 'ENGINEERING_FAILED',
              'test_fixture':True,'source_sha256':source,'s0_sha256':s0,'python_sha256':require_python,
              'commands':commands,'test_count':tests,'evidence_sha256':evidence,
              'source_snapshot_unchanged':good,'experiment_runs':0,'dev_calibration_runs':0,'aa_timing_runs':0,
              'formal_timing_runs':0,'mechanism_runs':0,'latency_matrix_runs':0,'resource_matrix_runs':0,
              'DEV_READY':False,'FINAL_READY':False,'selected_theta':None,'selected_h':None}
    _save(out/'manifest.json',manifest)
    print('manifest:',str(out/'manifest.json'),'sha256:',sha(out/'manifest.json'),flush=True)
    return 0 if good else 1

if __name__=='__main__':
    try:sys.exit(run(arguments()))
    except (ValueError,OSError,KeyError) as e:print('engineering rejected:',str(e),file=sys.stderr);sys.exit(2)
