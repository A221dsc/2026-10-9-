"""Immutable engineering build/evidence; never launches formal experiments."""
import argparse, csv, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time
S1=pathlib.Path(__file__).resolve().parents[1]
ROOT=S1.parents[1]
COMPILER=ROOT/'adaptive_poolhbi/final_tools/llvm-mingw-20260922-ucrt-x86_64/bin/clang++.exe'
PY_SHA='10d845f50a2af64e3500bb2fcb348b5bc98a75d8ddada63e45ba1da6a1fc79d1'
CC_SHA='20ba1856942744291a6aaaf9f2c94f6d0cd7cac5aa9557fce96471dc7ef25d6f'

def compiler_warning_lines(stderr):
 text=stderr.decode('utf-8',errors='replace') if isinstance(stderr,bytes) else stderr
 return [line for line in text.splitlines() if re.search(r'\bwarning:',line)]

def require_warning_free(stderr):
 warnings=compiler_warning_lines(stderr)
 if warnings:raise RuntimeError('compiler warning gate: '+' | '.join(warnings))
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True);ap.add_argument('--red',action='store_true');ap.add_argument('--suite',action='append');ap.add_argument('--build-only',action='store_true');ap.add_argument('--modes',default='native,latency,resource');ap.add_argument('--runtime-probe',action='store_true');args=ap.parse_args()
 if not args.tag.replace('_','').replace('-','').isalnum():raise ValueError('safe immutable tag required')
 out=S1/'artifacts/driver'/args.tag;out.mkdir(parents=True,exist_ok=False)
 files=[p for folder in ('src','tests','tools') for p in (S1/folder).glob('*') if p.is_file()]
 hashes={str(p.relative_to(S1)):sha(p) for p in files}
 for p in files:
  dest=out/'source'/p.relative_to(S1);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
 assert sha(COMPILER)==CC_SHA,'compiler anchor mismatch';assert sha(sys.executable)==PY_SHA,'Python anchor mismatch'
 env=os.environ.copy();env['PATH']=str(COMPILER.parent)+os.pathsep+str(COMPILER.parent.parent/'x86_64-w64-mingw32/bin')+os.pathsep+env.get('PATH','')
 cmds=[];compiled_modes=[];dependencies={}
 for name in ['final/adaptive_poolhbi_final.hpp','final/adaptive_types.hpp','final/shared_allocator.hpp','final/frozen_config.hpp','final_experiments/driver_core.hpp','final_experiments/trace_cache.hpp','final_experiments/legacy/generators.hpp','final_experiments/legacy/pool_index.hpp','final_experiments/legacy/public_index.hpp']:
  p=ROOT/'adaptive_poolhbi'/name;dependencies['adaptive_poolhbi/'+name]=sha(p)
 bundle={**{'S1/'+str(p.relative_to(S1)).replace('\\','/'):sha(p) for p in (S1/'src').glob('*') if p.is_file()},**dependencies}
 source_bundle_sha=hashlib.sha256(''.join(k+'\n'+bundle[k]+'\n' for k in sorted(bundle)).encode()).hexdigest()
 def run(name,cmd,expect=0):
  rec={'command':list(map(str,cmd)),'cwd':str(S1),'started_ns':time.time_ns(),'engineering_only':True}
  try:r=subprocess.run(rec['command'],cwd=S1,env=env,capture_output=True,timeout=55);rec.update(exit_code=r.returncode);(out/(name+'.stdout.txt')).write_bytes(r.stdout);(out/(name+'.stderr.txt')).write_bytes(r.stderr)
  except subprocess.TimeoutExpired as e:rec.update(exit_code='TIMEOUT55');(out/(name+'.stdout.txt')).write_bytes(e.stdout or b'');(out/(name+'.stderr.txt')).write_bytes(e.stderr or b'')
  is_compiler=pathlib.Path(cmd[0]).resolve()==COMPILER.resolve()
  if is_compiler:rec['compiler_warnings']=compiler_warning_lines((out/(name+'.stderr.txt')).read_bytes())
  rec['ended_ns']=time.time_ns();(out/(name+'.process.json')).write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8');cmds.append(rec);print(name,rec['exit_code'],flush=True)
  if rec['exit_code'] not in (expect if isinstance(expect,tuple) else (expect,)):raise RuntimeError(name+' unexpected exit '+str(rec['exit_code']))
  if is_compiler:require_warning_free((out/(name+'.stderr.txt')).read_bytes())
 flags=['-std=c++17','-O3','-DNDEBUG','-Wall','-Wextra','-Wno-unknown-pragmas','-Wno-misleading-indentation','-Wno-unused-function','-static']
 try:
  if args.runtime_probe:
   probe=out/'runtime_probe.cpp';probe.write_text('#include <filesystem>\n#include <cstdio>\n#include "'+str(S1/'src/owner_tracker.hpp').replace('\\','/')+'"\nint main(){ std::puts("before filesystem current_path");std::fflush(stdout);{ auto p=std::filesystem::current_path();std::puts("after filesystem current_path; before returned path destruction");std::fflush(stdout);}std::puts("after returned path destruction");}\n',encoding='utf-8')
   for variant in ['dynamic','static']:
    exe=out/(variant+'.exe');run(variant+'_compile',[COMPILER,*[f for f in flags if variant=='static' or f!='-static'],'-DADAPTIVE_ALLOC_TRACK',probe,'-o',exe])
    run(variant+'_imports',[COMPILER.parent/'llvm-objdump.exe','-p',exe]);run(variant+'_probe',[exe],(3221225477,3221226356) if variant=='dynamic' else 0)
   status='RUNTIME_BOUNDARY_PROBE_RECORDED';return
  modes=['red'] if args.red else args.modes.split(',')
  if not args.red and (not modes or any(m not in ('native','latency','resource') for m in modes)):raise ValueError('invalid modes')
  for mode in modes:
   macros=['-DDRIVER_RED'] if args.red else ([] if mode=='native' else ['-DS0_EVENT_TRACE']+(['-DINDEX_MEMORY','-DADAPTIVE_ALLOC_TRACK'] if mode=='resource' else []))
   exe=out/('test_'+mode+'.exe');run(mode+'_compile',[COMPILER,*flags,*macros,S1/'tests/test_driver.cpp','-o',exe])
   if not args.build_only:
    for suite in args.suite or (['SX16','SX17','SX18','SX19','SX22','SX24'] if args.red else ['SX16','SX17','SX18','SX19','SX22','CACHE_NORMS']+['REGISTRY_'+id for id in ['D01','D02','D03','D04','D05','D06','D07','D08','D09','D10','F01','F02','F03','F05','F06','F07','M01']] if mode=='native' else ['SX16','SX17','SX18','SX22','SX24','CACHE_NORMS']):
     run(mode+'_'+suite,[exe,suite,(out/(mode+'_cache')).relative_to(S1)],1 if args.red else 0)
   if args.red:
    for variant,suite in [('CLOCK','SX19'),('MACROS','SX19'),('EVENTS','SX24')]:
     binary=out/('red_'+variant+'.exe');run('red_'+variant+'_compile',[COMPILER,*flags,'-DDRIVER_RED','-DDRIVER_RED_'+variant,S1/'tests/test_driver.cpp','-o',binary]);run('red_'+variant+'_'+suite,[binary,suite],1)
   else:
    driver=out/('s1_'+mode+'.exe');bound='-DS1_SOURCE_BUNDLE_SHA="'+source_bundle_sha+'"';run(mode+'_driver_compile',[COMPILER,*flags,*macros,bound,'-municode',S1/'src/s1_driver.cpp','-o',driver])
    run(mode+'_macros',[COMPILER,*flags,*macros,bound,'-dM','-E',S1/'src/s1_driver.cpp'])
    macro_text=(out/(mode+'_macros.stdout.txt')).read_text(encoding='utf-8');macro_set=set(re.findall(r'^#define\s+(\w+)',macro_text,re.M));enabled=set() if mode=='native' else {'S0_EVENT_TRACE'} if mode=='latency' else {'S0_EVENT_TRACE','INDEX_MEMORY','ADAPTIVE_ALLOC_TRACK'}
    prohibited={'INDEX_FAILURE_TEST','ADAPTIVE_ABLATION','ALLOCATION_FAILURE_INJECTION','GLOBAL_ALLOCATION_TRACKING'}|({'INDEX_MEMORY','ADAPTIVE_ALLOC_TRACK','S0_EVENT_TRACE'}-enabled)
    assert enabled<=macro_set and not prohibited&macro_set,(mode,'actual macro contract')
    run(mode+'_frontend',[COMPILER,*flags,*macros,bound,'-municode','-###',S1/'src/s1_driver.cpp','-o',driver])
    run(mode+'_imports',[COMPILER.parent/'llvm-objdump.exe','-p',driver]);imports=re.findall(r'DLL Name:\s*(\S+)',(out/(mode+'_imports.stdout.txt')).read_text(encoding='utf-8',errors='replace'));dlls={}
    for name in imports:
     paths=[pathlib.Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/name,COMPILER.parent/name,COMPILER.parent.parent/'x86_64-w64-mingw32/bin'/name]
     found=next((p for p in paths if p.exists()),None);dlls[name]={'path':str(found) if found else None,'sha256':sha(found) if found else None,'binding':'actual import resolved' if found else 'Windows API-set host resolution; no separate DLL file'}
    compiled_modes.append({'mode':mode,'flags':flags,'macros':sorted(enabled),'imports':dlls})
    run(mode+'_describe',[driver,'describe','--method','M_LIST']);desc=json.loads((out/(mode+'_describe.stdout.txt')).read_text(encoding='utf-8'));assert desc['measurement_mode']==mode and desc['binary_sha']==sha(driver) and desc['source_bundle_sha']==source_bundle_sha and desc['native_work_available'] is False
    run(mode+'_bad_method',[driver,'describe','--method','M_EVENT_7'],2);run(mode+'_bad_parameter',[driver,'describe','--method','R6','--mask','0'],2)
    if not args.build_only:
     relative=driver.relative_to(S1);selfdir=(out/(mode+'_cli')).relative_to(S1);launcher=ROOT/'公开数据实验/pin_launch.exe';run(mode+'_pinned_cli',[launcher,'0x8',relative,'selftest','--output',selfdir])
     for method in ('M_LIST','R6','Original'):
      row=list(csv.DictReader((S1/selfdir/method/'raw_native.csv').open(encoding='utf-8')))[0];assert row['status']=='ENGINEERING_CORRECTNESS_ONLY' and row['placement_start_mask']==row['placement_end_mask']=='8' and row['placement_start_cpu']==row['placement_end_cpu']=='3' and row['binary_sha']==sha(driver) and row['source_bundle_sha']==source_bundle_sha
      assert int(row['total_ns'])==int(row['build_ns'])+int(row['online_ns']);assert int(row['lifecycle_ns'])==int(row['total_ns'])+int(row['destroy_ns']);assert row['total_avoidable_work']=='NA' if method=='M_LIST' else True
      for account in ('pool','buckets','tree','manager'):
       assert row[account+'_current']=='NA' if mode!='resource' or method=='Original' else int(row[account+'_current'])>0 if account in ('pool','buckets','manager') else True
      if mode!='native':
       samples=list(csv.DictReader((S1/selfdir/method/'latency.csv').open(encoding='utf-8')));assert len(samples)==48 and [int(s['API_ordinal']) for s in samples]==list(range(1,49));summary=json.loads((S1/selfdir/method/'latency_summary.json').read_text());assert summary['owner_current_after_destroy']==summary['owner_live_after_destroy']==('NA' if mode=='latency' else 0)
      if mode=='resource':
       resources=list(csv.DictReader((S1/selfdir/method/'resource.csv').open(encoding='utf-8')));assert resources and resources[-1]['snapshot_reason']=='phase|final' and resources[-1]['completed_unit']=='16' and resources[-1]['output_released']=='true' and int(resources[-1]['whole_peak'])>=int(resources[-1]['whole_current'])
     input_dir=S1/selfdir/'input';cache_sha=sha(input_dir/'cache.bin');run(mode+'_production_rejects_engineering',[driver,'run','--cache',(input_dir/'cache.bin').relative_to(S1),'--cache-sha',cache_sha,'--method','R6','--output',selfdir/'unsafe','--batch-id','test','--attempt-id','1','--pair-id','test','--round','1','--role','A'],2)
     run(mode+'_actual_cache_sha_reject',[driver,'run','--cache',(input_dir/'cache.bin').relative_to(S1),'--cache-sha','0'*64,'--method','R6','--output',selfdir/'badsha','--batch-id','test','--attempt-id','1','--pair-id','test','--round','1','--role','A'],2)
     assert 'actual SHA mismatch' in (out/(mode+'_actual_cache_sha_reject.stderr.txt')).read_text(encoding='utf-8')
     run(mode+'_prepare_testseed_reject',[driver,'prepare','--case','D01','--seed','94001','--profile','dev','--protocol-sha','bdb24556642d4137ab485befac9758b0abb04d933ebe5a3493b03d981cd9118a','--output',selfdir/'badseed'],2)
     run(mode+'_destination_reject',[launcher,'0x8',relative,'selftest','--output',selfdir],2)
     # wmain receives a real non-ASCII absolute destination through frozen ANSI
     # launcher using a DOS short executable path. This tests Unicode argv.
     import ctypes
     short=ctypes.create_unicode_buffer(32768);got=ctypes.windll.kernel32.GetShortPathNameW(str(driver),short,len(short));assert got
     unicode_dir=out/('中文绝对路径_'+mode);run(mode+'_unicode_pinned_cli',[launcher,'0x8',short.value,'selftest','--output',unicode_dir])
     assert (unicode_dir/'R6/run_receipt.json').exists()
     if mode=='native':
      run('native_llvm',[COMPILER,*flags,*macros,bound,'-S','-emit-llvm',S1/'src/s1_driver.cpp','-o',out/'native.ll'])
      body=(S1/'src/native_run.hpp').read_text(encoding='utf-8').split('template<class A>NativeResult native_body',1)[1].split('struct NativeCall',1)[0]
      ordered=['AUDIT_BUILD_BEGIN','AUDIT_INITIAL_VALUES','AUDIT_ONLINE_BEGIN','AUDIT_FINAL_VALUES_COUNTERS','AUDIT_DESTROY'];positions=[body.index(x) for x in ordered];assert positions==sorted(positions)
      loop=body.split('for(std::size_t unit=',1)[1].split('const auto end=Clock::now()',1)[0];assert 'Clock::' not in loop and 'hash_records(output)' in loop and 'output.size()!=st.expected_count' in loop and 'values()' not in loop
      assert body.count('Clock::now()')==6 and 'r.online_ns+=p.online_ns' in body and 'r.total_ns=r.build_ns+r.online_ns' in body and 'r.lifecycle_ns=r.total_ns+r.destroy_ns' in body
      llvm=(out/'native.ll').read_text(encoding='utf-8');symbols=re.findall(r'define[^\n]*@([^\n]+native_body[^\n]+)',llvm);assert len(symbols)>=13,(len(symbols),'compiled static specializations')
      assert body.count('A::construct(')==1
      audit={'native_body_sha':hashlib.sha256(body.encode()).hexdigest(),'clock_calls':6,'per_API_clocks':0,'constructor_calls':1,'boundary_markers':ordered,'index_values_outside_online':True,'hash_count_and_output_release_inside_online':True,'static_specializations':len(symbols),'source_dispatch':'native_dispatch compile-time StaticAdapter instantiations','llvm_sha':sha(out/'native.ll'),'flags':flags,'production_R6_type':'pbadaptive::Index direct frozen header'}
      (out/'native_boundary_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
  status='RED_ASSERTIONS_VERIFIED' if args.red else 'ENGINEERING_GREEN'
 finally:
  runtime_files={str(p):sha(p) for folder in [COMPILER.parent,COMPILER.parent.parent/'x86_64-w64-mingw32/bin'] for p in folder.glob('*') if p.is_file() and p.suffix.lower() in ('.dll','.cfg')}
  evidence={str(p.relative_to(out)).replace('\\','/'):sha(p) for p in out.rglob('*') if p.is_file() and 'source' not in p.relative_to(out).parts and p.name!='manifest.json'}
  coverage=[{'id':rec['command'][1],'mode':pathlib.Path(rec['command'][0]).stem.removeprefix('test_'),'exit_code':rec['exit_code'],'command':rec['command']} for rec in cmds if pathlib.Path(rec['command'][0]).stem.startswith('test_') and len(rec['command'])>=2]
  unchanged=all(sha(S1/k)==h and sha(out/'source'/k)==h for k,h in hashes.items())
  manifest={'schema':'s1.driver.engineering.v1','status':locals().get('status','FAILED_RETAINED'),'compiler_sha':sha(COMPILER),'python_sha':sha(sys.executable),'source_sha':hashes,'artifact_source_sha':{p.name:sha(p) for p in out.glob('*.cpp')},'frozen_dependencies':dependencies,'source_bundle_sha':source_bundle_sha,'mode_bindings':compiled_modes,'toolchain_runtime_files':runtime_files,'commands':cmds,'binary_sha':{p.name:sha(p) for p in out.glob('*.exe')},'coverage':coverage,'evidence_sha':evidence,'source_unchanged_and_snapshot_equal':unchanged,'formal_timing_or_selection_executed':False}
  if manifest['status']=='ENGINEERING_GREEN' and not unchanged:manifest['status']='FAILED_SOURCE_CHANGED_RETAINED'
  (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
