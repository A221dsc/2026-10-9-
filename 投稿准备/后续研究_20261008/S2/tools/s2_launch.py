"""Independent S2 execution, acceptance and capacity layer.

No command runs by default. Formal run requires an externally approved freeze
lock, clean committed sources and a sealed full engineering capacity receipt.
Interrupted/unsealed units are preserved and are never selectively rerun.
"""
from pathlib import Path
import argparse
import csv
import ctypes
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

import s2_matrix as matrix

S2 = Path(__file__).resolve().parents[1]
WORKSPACE = S2.parents[2]
PROTOCOL_SHA = '6a68de0ff20a438937251ca2a0aab1830824d0bdd2ef642985730c73d55ee181'
SOURCE_SHA = '8914c691dc39f0f425ade34d34789e2b1985a9434fe31d1300bccb79a641c81c'
SOURCE_BUNDLE_SHA = '6f2fbf85f6143b9516a1a4e7fe5318eaa1eafce5969ab8ec0efdbb022ac11c32'
IDENTITY_KEYS = ('case_id','profile','seed','N','U','horizon','cache_sha','source_sha','protocol_sha','source_bundle_sha','trace_hash','initial_sha','final_sha','queries','returned','query_hash','API_calls')
COUNTERS = ('promotions','scheduled_demotions','cleanup_demotions','total_demotions','peak_tree_buckets','final_tree_buckets','candidate_max','nodes_allocated')
ACCOUNTS = ('pool','buckets','tree','manager')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576), b''): h.update(block)
    return h.hexdigest()


def bind(path):
    path = Path(path).resolve(strict=True)
    return {'path':str(path),'sha256':sha(path)}


def verify_bindings(bindings):
    for binding in bindings:
        p = Path(binding['path'])
        if not p.is_absolute() or not p.is_file() or sha(p) != binding['sha256']:
            raise ValueError('binding missing or changed: ' + str(p))
    return True


def source_guard(path):
    verify_bindings([{'path':str(Path(path).resolve()),'sha256':SOURCE_SHA}])


def _unique(pairs):
    obj = {}
    for key,value in pairs:
        if key in obj: raise ValueError('duplicate JSON key: '+key)
        obj[key] = value
    return obj


def load_json(path):
    obj = json.loads(Path(path).read_text(encoding='utf8'),object_pairs_hook=_unique,
                     parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    def check(value,key='',csv_row=False):
        if key in ('trace_hash','query_hash','seed','N','U','horizon','queries','returned','API_calls','exit_code') and value is not None and type(value) is not int:
            if csv_row and type(value) is str and re.fullmatch(r'0|[1-9][0-9]*',value) and int(value)<=2**64-1:
                pass
            else:raise ValueError('integer JSON identity required: '+key)
        if isinstance(value,dict):
            for k,v in value.items(): check(v,k,csv_row or key=='row')
        elif isinstance(value,list):
            for v in value:check(v,csv_row=csv_row)
    check(obj)
    return obj


def dump(path,obj):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8',newline='\n') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n')


def log(message):
    print(time.strftime('%H:%M:%S'),message,flush=True)


def actual_process(command,directory,cwd=None):
    """An exclusive ledger exists BEFORE execution; benchmark output is separate."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    command = [str(x) for x in command]
    started = time.time_ns()
    dump(directory/'START.json',{'status':'START','command':command,'started_ns':started,'cwd':str(Path(cwd or os.getcwd()).resolve())})
    log('START '+' '.join(command))
    error = None
    try:
        result = subprocess.run(command,capture_output=True,cwd=cwd)
        code,out,err = result.returncode,result.stdout,result.stderr
    except OSError as exc:
        code,out,err,error = None,b'',str(exc).encode('utf8'),repr(exc)
    ended = time.time_ns()
    for name,data in (('stdout.txt',out),('stderr.txt',err)):
        with (directory/name).open('xb') as f:f.write(data)
    doc = {'schema':'S2.process.v1','command':command,'cwd':str(Path(cwd or os.getcwd()).resolve()),
           'actual_exit_observed':type(code) is int,'exit_code':code,'started_ns':started,'ended_ns':ended,
           'elapsed_ns':ended-started,'spawn_error':error,'status':'COMPLETE' if code==0 else 'FAILURE',
           'stdout':bind(directory/'stdout.txt'),'stderr':bind(directory/'stderr.txt')}
    dump(directory/'process.json',doc)
    log(doc['status']+' exit='+str(code))
    if code != 0:raise RuntimeError('actual child failure saved: '+str(directory))
    return doc


def safe_tag(tag):
    if not isinstance(tag,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',tag) or tag in ('.','..'):
        raise ValueError('tag must be safe nonempty ASCII')
    return tag


def _pair(cell,kind,index):
    unit = kind+'_'+str(index).zfill(4)+'_'+cell['case_id']+'_'+str(cell['seed'])+'_h'+str(cell['U']//262144)+'_'+cell['reference']
    children=[]
    for order,(round_,role) in enumerate(matrix.pair_order()):
        children.append({'child_id':unit+'_'+str(order)+'_'+round_+role,'pair_id':unit,'round':round_,'role':role,
                         'method':cell['reference'] if role=='A' else cell['candidate'],'mode':'native',
                         'case_id':cell['case_id'],'seed':cell['seed'],'U':cell['U'],'horizon':cell['U']//262144,
                         'profile':'aa' if kind.startswith('aa') else 'final'})
    return {'unit_id':unit,'kind':kind,'children':children}


def formal_plan():
    units=[]
    for kind,cells in (('aa_before',matrix.aa_cells('before')),('formal_native',matrix.native_cells()),('aa_after',matrix.aa_cells('after'))):
        units.extend(_pair(cell,kind,i) for i,cell in enumerate(cells))
    for i,cell in enumerate(matrix.resource_cells()):
        unit='resource_'+str(i).zfill(4)+'_'+cell['case_id']+'_'+str(cell['seed'])+'_'+cell['method']
        child=dict(cell,child_id=unit,pair_id=unit,round='AB',role='A',horizon=4,profile='final')
        units.append({'unit_id':unit,'kind':'resource','children':[child]})
    return {'schema':'S2.plan.v1','engineering_only':False,'units':units,
            'counts':{'formal_native':1080,'aa_before':180,'aa_after':180,'resource':120,'children':1560,'prepare':33}}


def capacity_plan(scale,seed):
    if scale not in ('mini','full') or seed not in (102001,102002):raise ValueError('registered engineering scale/seed required')
    units=[];n=768 if scale=='mini' else 262144
    for mode in ('native','resource'):
        for method in matrix.METHODS:
            unit='capacity_'+mode+'_'+method
            child={'child_id':unit,'pair_id':unit,'round':'AB','role':'A','method':method,'mode':mode,
                   'case_id':'L03','seed':seed,'U':4*n,'horizon':4,'profile':'engineering'}
            units.append({'unit_id':unit,'kind':'capacity','children':[child]})
    return {'schema':'S2.plan.v1','engineering_only':True,'scale':scale,'seed':seed,'units':units,'counts':{'children':8,'prepare':1,'native':4,'resource':4}}


def resume_prefix(planned_ids,seals):
    length = matrix.sealed_prefix(planned_ids,[s['unit_id'] for s in seals])
    for seal in seals:verify_bindings(seal['files'])
    return length


def load_prefix(directory,planned_ids):
    directory = Path(directory)
    if not directory.exists():return []
    seals=[]
    for child in sorted(directory.iterdir()):
        if not child.is_dir() or not (child/'seal.json').is_file():raise ValueError('unsealed attempt prohibits selective rerun: '+str(child))
        seal=load_json(child/'seal.json')
        expected=str(len(seals)).zfill(6)+'_'+seal['unit_id']
        if child.name!=expected:raise ValueError('noncontinuous unit directory')
        seals.append(seal)
    resume_prefix(planned_ids,seals)
    if seals:
        root=directory.resolve().parent
        if not (root/'plan.json').is_file() or not (root/'lock.json').is_file():raise ValueError('original plan/lock required to recover sealed children')
        plan=load_json(root/'plan.json');lock=load_json(root/'lock.json')
        if [u['unit_id'] for u in plan['units']]!=list(planned_ids):raise ValueError('original recovery plan identity mismatch')
        for index,seal in enumerate(seals):
            unit=plan['units'][index]
            revalidate_unit(root,plan,unit,seal,lock,directory/(str(index).zfill(6)+'_'+unit['unit_id']))
    return seals


def prepare_command(root,plan,child,lock):
    root=Path(root).resolve();key=child['profile']+'_'+child['case_id']+'_'+str(child['seed'])
    cacheout=root/'caches'/key;ledger=root/'prepare'/key
    command=[short_executable(lock['binaries']['native']['path']),'prepare','--timestamps',lock['timestamps']['path'],
             '--source-sha',SOURCE_SHA,'--output',str(cacheout),'--seed',str(child['seed']),'--case',child['case_id'],'--profile',child['profile']]
    if plan['engineering_only']:command.extend(['--scale',plan['scale']])
    return command,cacheout,ledger


def revalidate_process(directory,command):
    directory=Path(directory);process=load_json(directory/'process.json')
    matrix.validate_execution(command,process)
    if process.get('schema')!='S2.process.v1' or process.get('status')!='COMPLETE':raise ValueError('original complete process receipt required')
    start=load_json(directory/'START.json')
    if start.get('status')!='START' or start.get('command')!=command or start.get('started_ns')!=process.get('started_ns') or start.get('cwd')!=process.get('cwd'):
        raise ValueError('actual START/process command binding mismatch')
    for key in ('stdout','stderr'):
        if process[key]!=bind(directory/(key+'.txt')):raise ValueError('actual process output binding mismatch: '+key)
    if type(process.get('ended_ns')) is not int or process['ended_ns']<process['started_ns'] or process.get('elapsed_ns')!=process['ended_ns']-process['started_ns']:
        raise ValueError('actual process clock receipt mismatch')
    return process


def revalidate_prepare(root,plan,child,lock):
    command,cacheout,ledger=prepare_command(root,plan,child,lock)
    saved=load_json(ledger/'seal.json');verify_bindings(saved['files'])
    process=revalidate_process(ledger,command)
    recomputed=accept_prepare(cacheout,child['profile'],child['case_id'],child['seed'],process,command,lock)
    if saved!=recomputed:raise ValueError('prepare seal disagrees with actual process/cache metadata')
    return recomputed,cacheout,ledger


def revalidate_unit(root,plan,unit,seal,lock,unitdir):
    """Recompute acceptance from original exports; seal rows are never authority."""
    equal_identity({'schema':'S2.unit.seal.v1','unit_id':unit['unit_id'],'kind':unit['kind']},seal)
    if [c.get('child_id') for c in seal['children']]!=[c['child_id'] for c in unit['children']]:raise ValueError('sealed child count/order differs from original plan')
    prepared,cacheout,prep_ledger=revalidate_prepare(root,plan,unit['children'][0],lock)
    required=[bind(prep_ledger/'seal.json'),*prepared['files']]
    for child,embedded in zip(unit['children'],seal['children']):
        cache=cacheout/('h'+str(child['horizon']))/'cache.bin'
        metadata=load_json(cache.with_name('cache.meta.json'))
        identity={key:metadata[key] for key in IDENTITY_KEYS}
        if identity!=prepared['identities'][str(child['horizon'])]:raise ValueError('actual cache metadata/prepare identity mismatch')
        equal_identity({k:child[k] for k in ('case_id','profile','seed','U','horizon')},identity)
        expected=dict(identity,**{k:child[k] for k in ('pair_id','round','role','mode','method')},batch_id=Path(root).name,binary_sha=lock['binaries'][child['mode']]['sha256'])
        out=unitdir/'outputs'/child['child_id'];ledger=unitdir/'processes'/child['child_id']
        command=command_run(lock['pin']['path'],lock['binaries'][child['mode']]['path'],cache,identity['cache_sha'],child,Path(root).name,out)
        process=revalidate_process(ledger,command)
        row=accept_child(out,expected,command,process)
        accepted=load_json(ledger/'accepted.json');verify_bindings(accepted['files'])
        if accepted!=embedded or accepted.get('expected')!=expected or accepted.get('row')!=row:
            raise ValueError('accepted.json/unit seal disagrees with original plan/process/raw/receipt')
        original_files={b['path']:b['sha256'] for b in accepted['files']}
        actual_files=[bind(p) for p in out.iterdir() if p.is_file()]+[bind(p) for p in ledger.iterdir() if p.is_file() and p.name!='accepted.json']
        if original_files!={b['path']:b['sha256'] for b in actual_files}:raise ValueError('sealed child file inventory differs from actual original exports')
        required.extend([*actual_files,bind(ledger/'accepted.json')])
    bindings={b['path']:b['sha256'] for b in seal['files']}
    if any(bindings.get(b['path'])!=b['sha256'] for b in required):raise ValueError('unit seal omits original child/prepare binding')
    return True


def verify_runtime(manifest,actual_python,expected_python,expected_count=781):
    actual=Path(actual_python).resolve();expected=Path(expected_python).resolve()
    if actual != expected:raise ValueError('private runtime impersonation: '+str(actual))
    files=manifest['files']
    if manifest['file_count']!=expected_count or len(files)!=expected_count:raise ValueError('runtime dependency count mismatch')
    paths=[str(Path(b['path']).resolve()) for b in files]
    if len(paths)!=len(set(paths)) or str(expected) not in paths:raise ValueError('runtime bindings incomplete or duplicate')
    verify_bindings(files)
    return len(files)


def _rows(path):
    with Path(path).open(encoding='utf8',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)):raise ValueError('duplicate CSV columns')
        rows=list(reader)
    if any(None in row or None in row.values() for row in rows):raise ValueError('ragged CSV')
    return rows


def uint(value):
    text=str(value)
    if not re.fullmatch(r'0|[1-9][0-9]*',text) or int(text)>2**64-1:raise ValueError('canonical uint64 required: '+text)
    return int(text)


def equal_identity(expected,actual):
    for key,value in expected.items():
        if key not in actual or str(actual[key])!=str(value):raise ValueError('identity mismatch: '+key)


def expected_phases(case,n,u):
    n=uint(n);u=uint(u)
    if case not in matrix.LOADS or u not in (n,2*n,4*n):raise ValueError('unregistered case/horizon')
    if case=='L03':
        third=4*n//3
        specs=[('sparse_before',0,third,256),('shuffle',third,2*third,8),('sparse_after',2*third,4*n,256)]
    else:specs=[(case,0,4*n,256)]
    return [(name,begin,min(end,u),(min(end,u)-begin)//q) for name,begin,end,q in specs if begin<u]


def accept_child(output,expected,command,process):
    """Validate actual exit, prepared identity, all exported hashes and invariants."""
    matrix.validate_execution(command,process)
    return accept_files(output,expected)


def accept_files(output,expected):
    """File acceptance also reused for external ENGINEERING capacity records."""
    output=Path(output);receipt=load_json(output/'receipt.json')
    if receipt.get('schema')!='S2.run.v1' or receipt.get('verified') is not True:raise ValueError('unverified child receipt')
    engineering=expected['profile']=='engineering'
    if receipt.get('engineering_only') is not engineering:raise ValueError('engineering identity mismatch')
    equal_identity(expected,receipt)
    for name,key in (('raw.csv','raw_sha'),('phases.csv','phases_sha')):
        if sha(output/name)!=receipt[key]:raise ValueError('child file hash mismatch: '+name)
    rows=_rows(output/'raw.csv')
    if len(rows)!=1:raise ValueError('exactly one raw row required')
    row=rows[0]
    if row.get('schema')!='S2.raw.v1':raise ValueError('raw schema mismatch')
    matrix.validate_raw(expected,row)
    for key,value in receipt.items():
        if key in row and key!='schema':
            wanted=str(value).lower() if type(value) is bool else str(value)
            if row[key]!=wanted:raise ValueError('raw/receipt disagreement: '+key)
    for key in ('seed','N','U','horizon','trace_hash','queries','returned','query_hash','API_calls','build_ns','online_ns','total_ns','destroy_ns'):
        uint(row[key])
    if uint(row['API_calls'])!=2*uint(row['U'])+uint(row['queries']):raise ValueError('API count mismatch')
    if uint(row['horizon'])*uint(row['N'])!=uint(row['U']):raise ValueError('horizon mismatch')
    for boundary in ('start','end'):
        equal_identity({'process_mask_'+boundary:8,'cpu_'+boundary:3,'group_'+boundary:0},row)
    phases=_rows(output/'phases.csv');specs=expected_phases(row['case_id'],row['N'],row['U'])
    if len(phases)!=len(specs):raise ValueError('phase count mismatch')
    for i,(phase,(name,begin,end,queries)) in enumerate(zip(phases,specs)):
        equal_identity({'phase':i,'name':name,'begin':begin,'end':end,'queries':queries},phase)
        for key in ('phase','begin','end','queries','returned','online_ns'):uint(phase[key])
        if uint(phase['online_ns'])<=0:raise ValueError('nonpositive phase clock')
    for key in ('queries','returned','online_ns'):
        if sum(uint(p[key]) for p in phases)!=uint(row[key]):raise ValueError('phase sum mismatch: '+key)
    for account in ACCOUNTS:
        current,peak=row[account+'_current'],row[account+'_peak']
        if row['mode']=='native' or row['method']=='TLX':
            if (current,peak)!=('NA','NA'):raise ValueError('unavailable accounts must be NA')
        elif uint(current)>uint(peak):raise ValueError('account current exceeds peak')
    if row['method']=='TLX':
        if any(row[key]!='NA' for key in COUNTERS):raise ValueError('TLX adaptive counters must be NA')
    else:
        for key in COUNTERS:uint(row[key])
        if uint(row['nodes_allocated'])!=uint(row['N']):raise ValueError('fixed live node allocation mismatch')
    if row['mode']=='resource':
        if sha(output/'snapshots.csv')!=receipt.get('snapshots_sha'):raise ValueError('snapshot file hash mismatch')
        snapshots=_rows(output/'snapshots.csv')
        ends={end for _,_,end,_ in specs}
        required=sorted(ends|{v for v in (uint(row['N']),2*uint(row['N']),4*uint(row['N'])) if v<=uint(row['U'])})
        if [uint(s['unit']) for s in snapshots]!=required:raise ValueError('resource checkpoints mismatch')
        previous={}
        for snap in snapshots:
            unit=uint(snap['unit'])
            if snap['phase_boundary']!=str(unit in ends).lower():raise ValueError('phase boundary snapshot mismatch')
            for group in ('whole',*ACCOUNTS):
                if group!='whole' and row['method']=='TLX':
                    if (snap[group+'_current'],snap[group+'_peak'])!=('NA','NA'):raise ValueError('TLX account snapshots must be NA')
                    continue
                current=uint(snap[group+'_current']);peak=uint(snap[group+'_peak'])
                if current>peak or peak<previous.get(group,0):raise ValueError('snapshot peak invariant')
                previous[group]=peak
            uint(snap['whole_live'])
            counter_row=dict(row,**{k:snap[k] for k in COUNTERS})
            matrix.validate_raw({},counter_row)
        last=snapshots[-1]
        for key in (*COUNTERS,*[a+'_'+suffix for a in ACCOUNTS for suffix in ('current','peak')]):
            if row[key]!=last[key]:raise ValueError('final snapshot disagrees with raw: '+key)
        if row['owner_peak']!=last['whole_peak']:raise ValueError('owner peak disagrees with snapshots')
    elif row['owner_peak']!='NA':raise ValueError('native owner peak must be NA')
    return row


def short_executable(path):
    path=Path(path).resolve(strict=True)
    if os.name!='nt':return str(path)
    buffer=ctypes.create_unicode_buffer(32768)
    length=ctypes.windll.kernel32.GetShortPathNameW(str(path),buffer,len(buffer))
    if not length or length>=len(buffer):raise ctypes.WinError()
    # The frozen CreateProcessA launcher needs the short executable name.
    # Chinese directory names are retained when representable in Windows ACP.
    buffer.value.encode('mbcs',errors='strict')
    return buffer.value


def command_run(pin,binary,cache,cache_sha,child,batch,output):
    command=[str(pin),'0x8',short_executable(binary),'run','--cache',str(cache),'--cache-sha',cache_sha,
             '--method',child['method'],'--output',str(output),'--batch-id',batch,'--pair-id',child['pair_id'],
             '--round',child['round'],'--role',child['role']]
    if child['profile']=='engineering':command.append('--engineering')
    return command


def validate_lock_shape(lock,formal=False):
    if lock.get('schema')!='S2.launch.lock.v1':raise ValueError('launch freeze schema required')
    required=('bindings','build_manifest','environment','binaries','timestamps','source_bundle_sha','protocol_sha','runtime_manifest','python','pin','topology')
    if any(key not in lock for key in required):raise ValueError('incomplete launch lock')
    registered={str(Path(b['path']).resolve()) for b in lock['bindings']}
    needed=[Path(__file__),S2/'tools/s2_matrix.py',S2/'s2_protocol.json',*(S2.parent/'S1/tools').glob('*.py')]
    if not {str(p.resolve()) for p in needed}.issubset(registered):raise ValueError('launcher or Quiet import dependency omitted from lock')
    if set(lock['binaries'])!={'native','resource'}:raise ValueError('both executable modes required')
    if formal:
        if lock.get('engineering_only') is not False or lock.get('formal_authorized') is not True:raise ValueError('formal authorization not present in external lock')
        for key in ('source_commit','freeze_tag','reviews','capacity','gate_evidence','protected_paths','parent_commit'):
            if not lock.get(key):raise ValueError('formal freeze field required: '+key)


def _git(args,root=WORKSPACE):
    r=subprocess.run(['git','-C',str(root),*args],capture_output=True)
    if r.returncode:raise ValueError('Git check failed: '+r.stderr.decode('utf8',errors='replace'))
    return r.stdout.decode('utf8').strip()


def validate_freeze_diff(changed,evidence_paths):
    """Later commits may register explicit evidence; frozen source remains exact."""
    allowed=set(evidence_paths)
    if any(Path(p).suffix not in ('.json','.md') for p in allowed):raise ValueError('only JSON/Markdown evidence can follow source freeze')
    if any(p not in allowed for p in changed):raise ValueError('non-evidence change after frozen source commit')


def engineering_lock(build_dir):
    """Candidate lock only; this command NEVER grants formal authorization."""
    build_dir=Path(build_dir).resolve();manifest_path=build_dir/'build_manifest.json'
    manifest=load_json(manifest_path)
    env_path=S2/'S2_初始环境登记.json';env=load_json(env_path)
    bindings=[bind(manifest_path),bind(env_path),bind(S2/'s2_protocol.json'),bind(__file__),bind(S2/'tools/s2_matrix.py')]
    bindings.extend(manifest['inputs'])
    for value in env.values():
        if isinstance(value,dict) and 'path' in value and 'sha256' in value:bindings.append(value)
    runtime=load_json(env['private_runtime']['path'])
    bindings.extend(runtime['files'])
    # Import-time S1 dependencies are frozen too; only Quiet is invoked.
    bindings.extend(bind(p) for p in sorted((S2.parent/'S1/tools').glob('*.py')))
    binaries={mode:bind(build_dir/('s2_driver_'+mode+'.exe')) for mode in ('native','resource')}
    bindings.extend(binaries.values())
    timestamps=bind(S2/'artifacts/data/NASA_JUL95_20261013_01/timestamps.bin');bindings.append(timestamps)
    unique={b['path']:b for b in bindings}
    return {'schema':'S2.launch.lock.v1','engineering_only':True,'formal_authorized':False,
            'bindings':list(unique.values()),'build_manifest':bind(manifest_path),'environment':bind(env_path),
            'binaries':binaries,'timestamps':timestamps,'source_bundle_sha':manifest['source_bundle_sha'],
            'protocol_sha':PROTOCOL_SHA,'runtime_manifest':env['private_runtime'],'python':env['python'],
            'pin':env['pin_launch'],'topology':env['core_topology']}


def verify_lock(lock,formal=False):
    validate_lock_shape(lock,formal)
    verify_bindings(lock['bindings'])
    for key in ('build_manifest','environment','timestamps','runtime_manifest','python','pin','topology'):verify_bindings([lock[key]])
    verify_bindings(lock['binaries'].values())
    if lock['protocol_sha']!=PROTOCOL_SHA or lock['source_bundle_sha']!=SOURCE_BUNDLE_SHA:raise ValueError('registered protocol/source bundle changed')
    source_guard(lock['timestamps']['path'])
    verify_runtime(load_json(lock['runtime_manifest']['path']),sys.executable,lock['python']['path'])
    manifest=load_json(lock['build_manifest']['path']);verify_bindings(manifest['inputs'])
    if manifest['source_bundle_sha']!=lock['source_bundle_sha']:raise ValueError('build bundle identity mismatch')
    bundle=hashlib.sha256(''.join(b['path']+'\n'+b['sha256']+'\n' for b in sorted(manifest['inputs'],key=lambda b:b['path'])).encode('utf8')).hexdigest()
    if bundle!=lock['source_bundle_sha']:raise ValueError('actual source bundle does not match frozen build')
    for record in manifest['commands']:
        if type(record.get('exit_code')) is not int or record['exit_code']!=0:raise ValueError('build command unsuccessful')
        if 'test' in record:
            if type(record['test'].get('exit_code')) is not int or record['test']['exit_code']!=0:raise ValueError('C++ tests unsuccessful')
        if record.get('compiler_warnings'):raise ValueError('unreviewed compiler warnings')
    if formal:
        if _git(['status','--porcelain']):raise ValueError('dirty Git blocks formal execution')
        if _git(['rev-parse',lock['freeze_tag']+'^{commit}'])!=lock['source_commit']:raise ValueError('freeze tag mismatch')
        _git(['merge-base','--is-ancestor',lock['source_commit'],'HEAD'])
        changed=_git(['-c','core.quotepath=false','diff','--name-only',lock['source_commit'],'HEAD']).splitlines()
        validate_freeze_diff(changed,lock.get('evidence_paths',[]))
        if _git(['diff','--name-only',lock['parent_commit'],'HEAD','--',*lock['protected_paths']]):raise ValueError('frozen parent paths changed')
        verify_bindings(lock['reviews']);verify_bindings(lock['gate_evidence']);verify_bindings([lock['capacity']])
        for binding in lock['reviews']:
            review=load_json(binding['path'])
            if review.get('decision')!='Approved':raise ValueError('external engineering review not Approved')
        # Concrete gate evidence must bind actual process records, macro/IR audit
        # and the independent closure. Candidate build JSON cannot authorize it.
        gate_names={entry['kind'] for entry in lock['gate_evidence']}
        if not {'build_actual_exits','macro_ir_audit','cli_tests','independent_closure'}.issubset(gate_names):raise ValueError('engineering gate evidence incomplete')
        for entry in lock['gate_evidence']:
            evidence=load_json(entry['path'])
            if evidence.get('approved_for_formal') is not True:raise ValueError('unapproved engineering gate evidence: '+entry['kind'])
            verify_bindings(evidence.get('files',[]))
        verify_capacity(lock['capacity']['path'],lock)
    return True


def parse_topology(text):
    rows=list(csv.DictReader(line for line in text.splitlines() if not line.startswith('#')))
    matches=[r for r in rows if r.get('logical')=='3']
    if len(matches)!=1:raise ValueError('unique logical P3 topology required')
    core=matches[0]
    if core.get('kind')!='P' or uint(core.get('efficiency_class'))<1 or int(core.get('mask_hex'),16)!=8:raise ValueError('P3 topology/affinity mismatch')
    return core


def command_plan(lock,plan,root):
    root=Path(root).resolve();prepare={};runs=[]
    for index,unit in enumerate(plan['units']):
        unitdir=root/'units'/(str(index).zfill(6)+'_'+unit['unit_id'])
        for c in unit['children']:
            key=c['profile']+'_'+c['case_id']+'_'+str(c['seed']);cacheout=root/'caches'/key
            if key not in prepare:
                argv=[lock['binaries']['native']['path'],'prepare','--timestamps',lock['timestamps']['path'],'--source-sha',SOURCE_SHA,
                      '--output',str(cacheout),'--seed',str(c['seed']),'--case',c['case_id'],'--profile',c['profile']]
                if plan['engineering_only']:argv.extend(['--scale',plan['scale']])
                prepare[key]={'argv':argv,'ledger':str(root/'prepare'/key),'output':str(cacheout)}
            out=unitdir/'outputs'/c['child_id']
            argv=[lock['pin']['path'],'0x8',lock['binaries'][c['mode']]['path'],'run','--cache',str(cacheout/('h'+str(c['horizon']))/'cache.bin'),
                  '--cache-sha','<bound-from-actual-prepare>','--method',c['method'],'--output',str(out),'--batch-id',root.name,
                  '--pair-id',c['pair_id'],'--round',c['round'],'--role',c['role']]
            if plan['engineering_only']:argv.append('--engineering')
            runs.append({'argv':argv,'ledger':str(unitdir/'processes'/c['child_id']),'output':str(out),'child_id':c['child_id']})
    return {'schema':'S2.command.plan.v1','prepare':list(prepare.values()),'run':runs,'counts':plan['counts'],
            'templates_only':True,'executable_short_path_resolved_at_spawn':True}


def verify_capacity(path,lock):
    """Consume real externally recorded capacity; never treat it as formal runs."""
    path=Path(path);doc=load_json(path)
    if doc.get('schema')!='S2.capacity.v1' or doc.get('status')!='PASS' or doc.get('engineering_only') is not True:
        raise ValueError('real engineering capacity receipt required')
    equal_identity({'N':262144,'U':1048576,'case_id':'L03','actual_runs':8,'formal_runs':0,'source_bundle_sha':lock.get('source_bundle_sha')},doc)
    if doc.get('seed') not in (102001,102002) or len(doc.get('runs',[]))!=8:raise ValueError('capacity registered runs missing')
    expected_pairs={(mode,method) for mode in ('native','resource') for method in matrix.METHODS}
    if {(r['mode'],r['method']) for r in doc['runs']}!=expected_pairs:raise ValueError('capacity method coverage missing')
    root=path.parent;cache=root/'input/h4/cache.bin';meta=load_json(cache.with_name('cache.meta.json'))
    equal_identity({'profile':'engineering','seed':doc['seed'],'case_id':'L03','N':262144,'U':1048576,'cache_sha':sha(cache),'source_sha':SOURCE_SHA,'protocol_sha':PROTOCOL_SHA,'source_bundle_sha':lock['source_bundle_sha']},meta)
    prep=load_json(root/'PREPARE_FULL.execution.json')
    if prep.get('status')!='PROCESS_EXITED' or type(prep.get('exit_code')) is not int or prep['exit_code']!=0 or not prep.get('started_utc') or not prep.get('ended_utc'):raise ValueError('capacity prepare actual process missing')
    for run in doc['runs']:
        mode,method=run['mode'],run['method'];name=mode+'_'+method
        record=load_json(root/(name+'.execution.json'))
        if record.get('status')!='PROCESS_EXITED' or type(record.get('exit_code')) is not int or record['exit_code']!=0 or not record.get('started_utc') or not record.get('ended_utc'):raise ValueError('capacity actual engineering process missing')
        argv=record.get('command_argv',[])
        if not argv or '--engineering' not in argv:raise ValueError('capacity command not engineering')
        output=Path(argv[argv.index('--output')+1])
        if output.resolve()!=(root/'runs'/name).resolve():raise ValueError('capacity output identity mismatch')
        for option,wanted in (('--cache',str(cache)),('--cache-sha',meta['cache_sha']),('--method',method),('--batch-id',root.name),('--pair-id',name),('--round','AB'),('--role','A')):
            if argv[argv.index(option)+1]!=wanted:raise ValueError('capacity command identity mismatch: '+option)
        if Path(argv[0]).resolve()!=Path(lock['pin']['path']).resolve() or Path(argv[2]).resolve()!=Path(lock['binaries'][mode]['path']).resolve():raise ValueError('capacity executable identity mismatch')
        if not Path(record['stdout_path']).is_file() or not Path(record['stderr_path']).is_file():raise ValueError('capacity stdout/stderr missing')
        expected={k:meta[k] for k in IDENTITY_KEYS}
        expected.update(batch_id=root.name,pair_id=name,round='AB',role='A',mode=mode,method=method,binary_sha=lock['binaries'][mode]['sha256'])
        accept_files(output,expected)
        if run.get('performance_sample') is not False or run.get('verification')!='PASS' or type(run.get('actual_exit_code')) is not int or run['actual_exit_code']!=0:raise ValueError('capacity summary disagreement')
    return True


def preflight(lock,directory,formal=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    return _preflight_created(lock,directory,formal)


def _preflight_created(lock,directory,formal=False):
    """Caller owns this fresh directory before entering any failure handler."""
    dump(directory/'START.json',{'status':'START','formal':formal,'started_ns':time.time_ns(),'expected_processes':3})
    dump(directory/'command_plan.json',{'commands':[[lock['topology']['path'],'--iters','1000000'],
            *[[lock['pin']['path'],'0x8',b['path'],'describe'] for b in lock['binaries'].values()]],
            'executable_short_path_resolved_at_spawn':True})
    verify_lock(lock,formal)
    topology=actual_process([lock['topology']['path'],'--iters','1000000'],directory/'topology')
    parse_topology(Path(topology['stdout']['path']).read_text(encoding='utf8'))
    descriptions={}
    for mode,binary in lock['binaries'].items():
        receipt=actual_process([lock['pin']['path'],'0x8',short_executable(binary['path']),'describe'],directory/('describe_'+mode))
        description=load_json(receipt['stdout']['path'])
        equal_identity({'mode':mode,'protocol_sha':PROTOCOL_SHA,'source_sha':SOURCE_SHA,'binary_sha':binary['sha256'],'source_bundle_sha':lock['source_bundle_sha']},description)
        if description.get('methods')!=list(matrix.METHODS):raise ValueError('described method registry mismatch')
        descriptions[mode]=description
    verify_lock(lock,formal)
    dump(directory/'COMPLETE.json',{'status':'COMPLETE','formal':formal,'descriptions':descriptions,'runtime_dependencies':781,
                                   'execution_commit':_git(['rev-parse','HEAD']) if formal else None,'source_commit':lock.get('source_commit'),
                                   'files':[bind(p) for p in directory.rglob('*') if p.is_file()]})
    return descriptions


def quiet_class():
    tools=S2.parent/'S1/tools';sys.path.insert(0,str(tools))
    try:return importlib.import_module('dev_launch').Quiet
    finally:sys.path.remove(str(tools))


def accept_prepare(directory,profile,case,seed,process,command,lock):
    matrix.validate_execution(command,process)
    description=load_json(process['stdout']['path'])
    if description.get('schema')!='S2.prepare.v1' or description.get('prefixes')!=[1,2,4]:raise ValueError('prepare successful output missing')
    directory=Path(directory);longest=sha(directory/'h4/cache.bin')
    if description.get('longest_cache_sha')!=longest:raise ValueError('prepare stdout/cache mismatch')
    identities={};bindings=[]
    for horizon in (1,2,4):
        cache=directory/('h'+str(horizon))/'cache.bin';metadata=cache.with_name('cache.meta.json');meta=load_json(metadata)
        equal_identity({'schema':'S2.cache.v1','profile':profile,'case_id':case,'seed':seed,'source_sha':SOURCE_SHA,'protocol_sha':PROTOCOL_SHA,
                        'source_bundle_sha':lock['source_bundle_sha'],'cache_sha':sha(cache),'longest_cache_sha':longest,'horizon':horizon},meta)
        if meta['N'] not in (768,262144) or meta['U']!=meta['N']*horizon or meta['Umax']!=4*meta['N']:raise ValueError('prepare dimensional mismatch')
        if meta['engineering_only'] is not (profile=='engineering'):raise ValueError('prepare engineering flag mismatch')
        if profile!='engineering' and meta['N']!=262144:raise ValueError('formal N mismatch')
        for key in ('seed','N','U','Umax','horizon','trace_hash','query_hash','queries','returned','API_calls'):uint(meta[key])
        if meta['API_calls']!=2*meta['U']+meta['queries']:raise ValueError('prepare API mismatch')
        if sum(p[3] for p in expected_phases(case,meta['N'],meta['U']))!=meta['queries']:raise ValueError('prepare query cadence mismatch')
        identities[str(horizon)]={key:meta[key] for key in IDENTITY_KEYS}
        bindings.extend([bind(cache),bind(metadata)])
    if len({identities[str(h)]['initial_sha'] for h in (1,2,4)})!=1:raise ValueError('prefix initial state mismatch')
    return {'schema':'S2.prepare.seal.v1','profile':profile,'case_id':case,'seed':seed,'identities':identities,
            'files':bindings+[bind(Path(process['stdout']['path']).parent/'process.json'),process['stdout'],process['stderr']]}


def execute_plan(lock,plan,root,formal=False,resume=False):
    """Only complete pair seals can advance the continuous execution prefix."""
    root=Path(root).resolve();batch=safe_tag(root.name)
    if resume:
        saved=load_json(root/'plan.json')
        if saved!=plan or load_json(root/'lock.json')!=lock:raise ValueError('resume execution identity mismatch')
        if (root/'COMPLETE.json').exists():raise ValueError('completed batch immutable')
    else:
        root.mkdir(parents=True,exist_ok=False);dump(root/'plan.json',plan);dump(root/'lock.json',lock)
        dump(root/'command_plan.json',command_plan(lock,plan,root))
    attempts=root/'attempts';attempts.mkdir(exist_ok=True)
    attempt=attempts/str(len(list(attempts.iterdir()))+1).zfill(3);attempt.mkdir()
    dump(attempt/'START.json',{'status':'START','counts':plan['counts'],'formal':formal,'started_ns':time.time_ns()})
    accepted=[]
    try:
        preflight(lock,attempt/'preflight',formal)
        seals=load_prefix(root/'units',[u['unit_id'] for u in plan['units']])
        quiet=quiet_class()()
        for index,unit in enumerate(plan['units']):
            if index<len(seals):continue
            unitdir=root/'units'/(str(index).zfill(6)+'_'+unit['unit_id']);unitdir.mkdir(parents=True,exist_ok=False)
            c=unit['children'][0];cachekey=c['profile']+'_'+c['case_id']+'_'+str(c['seed'])
            cacheout=root/'caches'/cachekey;prep_ledger=root/'prepare'/cachekey
            if (prep_ledger/'seal.json').is_file():
                prepared,cacheout,prep_ledger=revalidate_prepare(root,plan,c,lock)
            else:
                if cacheout.exists() or prep_ledger.exists():raise ValueError('unsealed preparation prohibits rerun')
                cmd,cacheout,prep_ledger=prepare_command(root,plan,c,lock)
                proc=actual_process(cmd,prep_ledger)
                prepared=accept_prepare(cacheout,c['profile'],c['case_id'],c['seed'],proc,cmd,lock)
                dump(prep_ledger/'seal.json',prepared)
            quiet.check(unitdir/'quiet.json')
            child_seals=[]
            for child in unit['children']:
                log('PROGRESS unit='+str(index+1)+'/'+str(len(plan['units']))+' child='+child['child_id'])
                verify_lock(lock,False);verify_bindings(prepared['files'])
                identity=prepared['identities'][str(child['horizon'])]
                equal_identity({k:child[k] for k in ('case_id','profile','seed','U','horizon')},identity)
                cache=cacheout/('h'+str(child['horizon']))/'cache.bin'
                expected=dict(identity,**{k:child[k] for k in ('pair_id','round','role','mode','method')},batch_id=batch,binary_sha=lock['binaries'][child['mode']]['sha256'])
                out=unitdir/'outputs'/child['child_id'];ledger=unitdir/'processes'/child['child_id']
                cmd=command_run(lock['pin']['path'],lock['binaries'][child['mode']]['path'],cache,identity['cache_sha'],child,batch,out)
                proc=actual_process(cmd,ledger)
                row=accept_child(out,expected,cmd,proc)
                verify_bindings(prepared['files']);verify_lock(lock,False)
                child_seal={'child_id':child['child_id'],'expected':expected,'row':row,
                            'files':[bind(p) for p in out.iterdir() if p.is_file()]+[bind(p) for p in ledger.iterdir() if p.is_file()]}
                dump(ledger/'accepted.json',child_seal);child_seals.append(child_seal);accepted.append(row)
            unitfiles=[bind(unitdir/'quiet.json'),bind(prep_ledger/'seal.json'),*prepared['files']]
            for child_seal in child_seals:unitfiles.extend(child_seal['files'])
            unitfiles.extend(bind(p) for p in (unitdir/'processes').rglob('accepted.json'))
            dump(unitdir/'seal.json',{'schema':'S2.unit.seal.v1','unit_id':unit['unit_id'],'kind':unit['kind'],
                                     'children':child_seals,'files':unitfiles,'completed_ns':time.time_ns()})
        verify_lock(lock,formal)
        finalseals=load_prefix(root/'units',[u['unit_id'] for u in plan['units']])
        rows=[child['row'] for seal in finalseals for child in seal['children']]
        if len(rows)!=plan['counts']['children']:raise ValueError('actual accepted child count mismatch')
        files=[bind(p) for p in root.rglob('*') if p.is_file()]
        elapsed=sum(load_json(p)['elapsed_ns'] for p in root.rglob('process.json'))
        disk=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        report={'schema':'S2.launch.complete.v1','status':'COMPLETE','engineering_only':plan['engineering_only'],
                'scale':plan.get('scale'),'seed':plan.get('seed'),'counts':plan['counts'],'accepted_children':len(rows),
                'files':files,'child_wall_ns':elapsed,'archive_bytes':disk,'free_disk_bytes':shutil.disk_usage(root).free,
                'capacity_excluded_from_effect_samples':plan['engineering_only'],'completed_ns':time.time_ns()}
        if plan['engineering_only']:
            report['throughput_updates_per_second']={r['mode']+'_'+r['method']:uint(r['U'])*1e9/uint(r['online_ns']) for r in rows}
            child_processes=[load_json(p) for p in (root/'units').rglob('process.json')]
            prep_processes=[load_json(p) for p in (root/'prepare').rglob('process.json')]
            report['conservative_formal_wall_seconds']=max(p['elapsed_ns'] for p in child_processes)*1560/1e9+max(p['elapsed_ns'] for p in prep_processes)*33/1e9+480*2
            report['projected_cache_bytes']=33*sum(p.stat().st_size for p in (root/'caches').rglob('*') if p.is_file())
            report['capacity_estimate_only']=True
        dump(root/'COMPLETE.json',report);dump(attempt/'COMPLETE.json',{'status':'COMPLETE','report':bind(root/'COMPLETE.json')})
        log('COMPLETE accepted_children='+str(len(rows)))
        return report
    except Exception as exc:
        dump(attempt/'FAILURE.json',{'status':'FAILURE','error':repr(exc),'ended_ns':time.time_ns(),'accepted_this_attempt':len(accepted),
                                   'selective_rerun_allowed':False})
        log('FAILURE '+repr(exc));raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('plan','preflight','capacity','run','engineer-lock'))
    parser.add_argument('--tag',required=True)
    parser.add_argument('--lock',type=Path)
    parser.add_argument('--engineering',action='store_true')
    parser.add_argument('--scale',choices=('mini','full'),default='mini')
    parser.add_argument('--seed',type=int,default=102001)
    parser.add_argument('--build-dir',type=Path,default=S2/'artifacts/engineering/build_v7')
    parser.add_argument('--resume',type=Path)
    args=parser.parse_args(argv);safe_tag(args.tag)
    root=S2/'artifacts/launch'/args.tag
    if args.command=='engineer-lock':
        root.mkdir(parents=True,exist_ok=False);dump(root/'START.json',{'status':'START','command':'engineer-lock','started_ns':time.time_ns()})
        try:
            lock=engineering_lock(args.build_dir);verify_lock(lock,False);dump(root/'lock.json',lock)
            dump(root/'COMPLETE.json',{'status':'COMPLETE','engineering_only':True,'formal_authorized':False,'lock':bind(root/'lock.json')})
        except Exception as exc:
            dump(root/'FAILURE.json',{'status':'FAILURE','error':repr(exc)});raise
        log('COMPLETE engineering candidate lock only');return 0
    if args.command=='plan':
        root.mkdir(parents=True,exist_ok=False)
        dump(root/'START.json',{'status':'START','command':'plan','started_ns':time.time_ns()})
        plan=capacity_plan(args.scale,args.seed) if args.engineering else formal_plan()
        dump(root/'plan.json',plan)
        if args.lock:dump(root/'command_plan.json',command_plan(load_json(args.lock),plan,root))
        dump(root/'COMPLETE.json',{'status':'COMPLETE','execution':False,'expected_counts':plan['counts'],'plan':bind(root/'plan.json')})
        log('COMPLETE plan only');return 0
    if not args.lock:parser.error('--lock required; no implicit formal approval')
    lock=load_json(args.lock)
    if args.command=='preflight':
        # Claim the archive outside the handler. A duplicate/racing tag cannot
        # cause a FAILURE write into an archive owned by an earlier invocation.
        root.mkdir(parents=True,exist_ok=False)
        try:_preflight_created(lock,root,formal=not args.engineering)
        except Exception as exc:
            dump(root/'FAILURE.json',{'status':'FAILURE','error':repr(exc),'ended_ns':time.time_ns()})
            raise
    elif args.command=='capacity':
        if args.resume:parser.error('engineering capacity attempts must use a fresh tag')
        execute_plan(lock,capacity_plan(args.scale,args.seed),root,formal=False)
    elif args.command=='run':
        if args.engineering:parser.error('run is formal; use capacity for engineering')
        if args.resume and args.resume.resolve()!=root.resolve():parser.error('resume path must match tag archive')
        execute_plan(lock,formal_plan(),root,formal=True,resume=bool(args.resume))
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        log('FAILURE '+repr(exc));sys.exit(1)
