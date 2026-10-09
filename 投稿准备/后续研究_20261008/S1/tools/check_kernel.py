"""Correctness only. Immutable attempts, bounded subprocesses, explicit RED/GREEN.
No calibration, performance timings or mechanism matrix dispatch is provided.
"""
import argparse, datetime, hashlib, json, os, pathlib, re, shutil, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
OLD=ROOT.parent.parent/'adaptive_poolhbi'/'final'
COMPILER=OLD.parent/'final_tools'/'llvm-mingw-20260922-ucrt-x86_64'/'bin'/'clang++.exe'
ARMS=['List','ObserveList','Fixed','Event','NoIdle']
SEEDS=[94001,94002]
S0=ROOT.parent/'S0'
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def call(command,name,attempt,env):
    result={'command':list(map(str,command)),'timeout_seconds':55,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        p=subprocess.run(result['command'],cwd=ROOT,env=env,capture_output=True,timeout=55)
        result.update(exit_code=p.returncode,stdout=p.stdout.decode('utf8','replace'),stderr=p.stderr.decode('utf8','replace'))
    except subprocess.TimeoutExpired as e:
        result.update(exit_code=None,timeout=True,stdout=(e.stdout or b'').decode('utf8','replace'),stderr=(e.stderr or b'').decode('utf8','replace'))
    (attempt/(name+'.stdout.log')).write_text(result.pop('stdout'),encoding='utf8')
    (attempt/(name+'.stderr.log')).write_text(result.pop('stderr'),encoding='utf8')
    (attempt/(name+'.process.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True);ap.add_argument('--red',action='store_true')
    ap.add_argument('--modes',default='native,debug,owner,diagnostic,asan,ubsan');ap.add_argument('--no-random',action='store_true')
    args=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.tag): raise SystemExit('invalid tag')
    attempt=ROOT/'artifacts'/'kernel'/args.tag;attempt.mkdir(parents=True,exist_ok=False)
    snapshot=attempt/'source';snapshot.mkdir()
    paths=list((ROOT/'tests').glob('*.hpp'))+list((ROOT/'tests').glob('*.cpp'))+[pathlib.Path(__file__)]
    if not args.red: paths+=list((ROOT/'src').glob('*index.hpp'))+[ROOT/'tools'/'derive_kernel.py']
    hashes={}
    for p in paths:
        if p.exists():
            rel=p.relative_to(ROOT);target=snapshot/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);hashes[str(rel)]=sha(p)
    old_hashes={p.name:sha(p) for p in [OLD/'adaptive_poolhbi_final.hpp',OLD/'adaptive_types.hpp',OLD/'shared_allocator.hpp',OLD/'frozen_config.hpp']}
    asset_path=S0/'S0_资产清单.json'
    assets=json.loads(asset_path.read_text(encoding='utf8'))['bindings']
    anchored={name:next(x['expected_sha256'] for x in assets if pathlib.Path(x['path']).name==name) for name in old_hashes}
    compiler_anchor=next(x['expected_sha256'] for x in assets if pathlib.Path(x['path']).name=='clang++.exe')
    python_anchor=next(x['expected_sha256'] for x in assets if pathlib.Path(x['path']).name=='python.exe')
    manifest={'schema':'S1.kernel.correctness.v1','stage':'RED' if args.red else 'GREEN_CANDIDATE','tag':args.tag,
              'source_sha256':hashes,'frozen_source_sha256':old_hashes,'compiler':str(COMPILER),'compiler_sha256':sha(COMPILER),
              'python':sys.executable,'python_sha256':sha(sys.executable),'cases':[],'binaries':{},'performance_executed':False}
    manifest['S0_asset_manifest']={'path':str(asset_path),'sha256':sha(asset_path)}
    manifest['S0_anchored_frozen_sha256']=anchored
    manifest['toolchain_matches_S0']=sha(COMPILER)==compiler_anchor and sha(sys.executable)==python_anchor
    env=os.environ.copy();env['PATH']=str(COMPILER.parent)+os.pathsep+str(COMPILER.parent.parent/'x86_64-w64-mingw32'/'bin')+os.pathsep+env.get('PATH','')
    modes={
      'native':['-O3','-DNDEBUG'], 'debug':['-O1','-DINDEX_MEMORY','-DINDEX_FAILURE_TEST'],
      'owner':['-O2','-DNDEBUG','-DINDEX_MEMORY','-DADAPTIVE_ALLOC_TRACK'],
      'diagnostic':['-O2','-DNDEBUG','-DKERNEL_DIAGNOSTIC','-DS0_EVENT_TRACE'],
      'asan':['-O1','-g','-DNDEBUG','-fsanitize=address','-fno-omit-frame-pointer'],
      'ubsan':['-O1','-g','-DNDEBUG','-fsanitize=undefined','-fno-sanitize-recover=all']}
    for mode in args.modes.split(','):
        flags=modes[mode]+(['-DKERNEL_RED'] if args.red else [])
        binary=attempt/(mode+'.exe')
        command=[COMPILER,'-std=c++17','-Wall','-Wextra','-Werror',*flags,ROOT/'tests'/'test_kernel.cpp','-o',binary]
        compiled=call(command,mode+'_compile',attempt,env)
        if compiled['exit_code']!=0:
            manifest['cases'].append({'mode':mode,'id':'COMPILE','status':'FAIL','exit_code':compiled['exit_code']});continue
        manifest['binaries'][mode]={'path':str(binary),'sha256':sha(binary),'flags':flags}
        ids=['SX01','SX02','SX04','SX05','SX06','SX07','SX08','SX09','SX10','SX11','SX12']
        if mode=='debug': ids+=['SX13','SX14']
        if mode=='owner': ids+=['SX15']
        # Sanitizers exercise content/conversions/quotas; separate from owner/failure builds.
        for id in ids:
            result=call([binary,'--case',id],mode+'_'+id,attempt,env)
            out=(attempt/(mode+'_'+id+'.stdout.log')).read_text(encoding='utf8')
            status='PASS' if result['exit_code']==0 and id+' PASS' in out else 'SKIP' if ' SKIP ' in out else 'FAIL'
            manifest['cases'].append({'mode':mode,'id':id,'status':status,'exit_code':result['exit_code']})
            print(f'{mode} {id} {status}',flush=True)
        if mode in ('native','asan','ubsan') and not args.no_random:
            for arm in ARMS:
                for seed in SEEDS:
                    name=f'{mode}_SX03_{arm}_{seed}';result=call([binary,'--random',arm,str(seed)],name,attempt,env)
                    out=(attempt/(name+'.stdout.log')).read_text(encoding='utf8')
                    status='PASS' if result['exit_code']==0 and 'SX03 PASS' in out and f'seed={seed} operations=100000 mismatches=0' in out else 'FAIL'
                    manifest['cases'].append({'mode':mode,'id':'SX03','arm':arm,'seed':seed,'operations':100000,'status':status,'exit_code':result['exit_code']})
                    print(f'{name} {status}',flush=True)
        # Compiler's exact record layouts retained separately; never a source access hack.
        layout=call([COMPILER,'-std=c++17',*flags,'-Xclang','-fdump-record-layouts','-fsyntax-only',ROOT/'tests'/'test_kernel.cpp'],mode+'_record_layout',attempt,env)
        manifest.setdefault('record_layouts',{})[mode]=layout['exit_code']
    manifest['frozen_source_unchanged']=old_hashes=={name:sha(OLD/name) for name in old_hashes}
    manifest['source_unchanged_and_snapshot_equal']=all(sha(ROOT/rel)==value and sha(snapshot/rel)==value for rel,value in hashes.items())
    executed={x['id'] for x in manifest['cases'] if x['status']=='PASS'}
    manifest['not_run_ids']=[f'SX{i:02}' for i in range(1,16) if f'SX{i:02}' not in executed]
    failures=[x for x in manifest['cases'] if x['status']=='FAIL']
    full_modes=len(args.modes.split(','))==len(modes) and set(args.modes.split(','))==set(modes)
    required_random={(arm,seed) for arm in ARMS for seed in SEEDS}
    random_gate={mode:len([x for x in manifest['cases'] if x['mode']==mode and x['id']=='SX03' and x['status']=='PASS'])==10 and
        {(x.get('arm'),x.get('seed')) for x in manifest['cases'] if x['mode']==mode and x['id']=='SX03' and x['status']=='PASS'}==required_random for mode in ('native','asan','ubsan')}
    manifest['complete_gate']={'all_modes':full_modes,'all_ids':not manifest['not_run_ids'],
        **{f'{mode}_random_5x2x100000':ok for mode,ok in random_gate.items()},
        'no_skips':all(x['status']!='SKIP' for x in manifest['cases']),
        'all_layouts_zero':len(manifest.get('record_layouts',{}))==len(args.modes.split(',')) and all(v==0 for v in manifest.get('record_layouts',{}).values()),
        'frozen_source_unchanged':manifest['frozen_source_unchanged'],
        'frozen_source_matches_S0':old_hashes==anchored,'toolchain_matches_S0':manifest['toolchain_matches_S0'],
        'source_unchanged_and_snapshot_equal':manifest['source_unchanged_and_snapshot_equal']}
    if args.red:
        manifest['status']='RED_BEHAVIOR_CONFIRMED' if failures and all(x['id']!='COMPILE' for x in failures) and manifest['frozen_source_unchanged'] else 'FAILED'
    else:
        manifest['status']='FAILED' if failures else 'GREEN' if all(manifest['complete_gate'].values()) else 'PASS_PARTIAL_NOT_COMPLETE'
    (attempt/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(str(attempt/'manifest.json'),manifest['status'],flush=True)
    return 0 if manifest['status'] in ('RED_BEHAVIOR_CONFIRMED','GREEN','PASS_PARTIAL_NOT_COMPLETE') else 1
if __name__=='__main__': raise SystemExit(main())
