"""Whole-pair byte/identity validation and layered entry gates.

Production validation requires an externally frozen lock SHA; a self-reported
`valid` field is never authority. ENGINEERING_FIXTURE inputs require explicit
test_fixture=True and cannot satisfy a production entry gate.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import struct
import time
from analysis import positive, two_round_ratio
from pair_adapter import child_command, schedule

S1=Path(__file__).resolve().parents[1]
PROTOCOL=S1.parent/'S0'/'S0_preregistration.json'
DRIVER_SHA='41a90f465a2bd30d8d9e92515b1c32234a8f0c6399026b4b44714d6906195405'

def require(condition,message):
    if not condition:raise ValueError(message)

def sha(path):
    try:
        h=hashlib.sha256()
        with Path(path).open('rb') as f:
            for b in iter(lambda:f.read(1<<20),b''):h.update(b)
        return h.hexdigest()
    except OSError as e:raise ValueError(f'bound file unavailable: {path}') from e

def _object_pairs(pairs):
    out={}
    for k,v in pairs:
        require(k not in out,'duplicate JSON field');out[k]=v
    return out

def load(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=_object_pairs,
                          parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (OSError,json.JSONDecodeError) as e:raise ValueError('invalid/missing JSON') from e

def csv_rows(path):
    try:
        with Path(path).open(newline='',encoding='utf-8') as f:
            r=csv.DictReader(f);fields=r.fieldnames
            require(fields is not None and len(fields)==len(set(fields)),'CSV duplicate or missing columns')
            rows=list(r)
        require(all(None not in r and all(x is not None for x in r.values()) for r in rows),'CSV shape')
        return rows
    except (OSError,UnicodeError) as e:raise ValueError('missing/invalid CSV') from e

def _hash_records(rs):
    h=1469598103934665603
    for a,b in rs:
        h=((h^a)*1099511628211)&((1<<64)-1);h=((h^b)*1099511628211)&((1<<64)-1)
    return ((h^len(rs))*1099511628211)&((1<<64)-1)

def _mix(h,x):return ((h^x)*1099511628211)&((1<<64)-1)

def cache_identity(path,expected_path,test_fixture=False):
    data=Path(path).read_bytes()
    if data.startswith(b'{'):
        require(test_fixture,'fixture cache forbidden')
        obj=load(path);require(obj['schema']=='ENGINEERING_FIXTURE.cache.v1' and obj['origin'].startswith('ENGINEERING_FIXTURE'),'fixture origin')
        require(Path(expected_path).read_bytes()==b'ENGINEERING_FIXTURE expected','fixture expected identity')
        return obj
    # Frozen APHTRC01 binary layout; parse content identities rather than trusting
    # metadata booleans. The source generator remains bound separately.
    pos=0
    def raw(n):
        nonlocal pos
        require(0<=n<=len(data)-pos,'truncated cache');v=data[pos:pos+n];pos+=n;return v
    def u64():return struct.unpack('<Q',raw(8))[0]
    def text():
        n=u64();require(n<=4096,'cache text bound');return raw(n).decode('utf-8')
    def records():
        n=u64();require(n<=100000000 and n*16<=len(data)-pos,'cache records bound')
        return [struct.unpack('<QQ',raw(16)) for _ in range(n)]
    require(raw(8)==b'APHTRC01' and u64()==1,'cache schema')
    obj={'domain':{'stride':u64(),'span':u64()}}
    for k in ('data','month','workload','dataset_sha','protocol_sha'):obj[k]=text()
    for k in ('seed','N','U','days','source_rows','query_period','c','ordered'):obj[k]=u64()
    obj['ordered']=bool(obj['ordered']);obj['q']=0 if obj['query_period']>obj['U'] else obj['query_period']
    whole=[u64() for _ in range(10)];obj.update(trace_hash=whole[0],returned=whole[1],queries=whole[2])
    obj['initial']=records();obj['final']=records();count=u64();require(count==obj['U'],'cache U shape')
    query_steps=[];steps=[];qh=1469598103934665603;ordinal=0
    trace_hash=_mix(1469598103934665603,_hash_records(obj['initial']))
    for i in range(count):
        added=(u64(),u64());erased,lo,hi,expected_hash,expected_count,query=[u64() for _ in range(6)]
        require(query in (0,1),'cache query flag');ordinal+=2
        values=(erased,*added,query,lo,hi,expected_hash)
        for value in values:trace_hash=_mix(trace_hash,value)
        steps.append((values,expected_count))
        if query:
            ordinal+=1;query_steps.append((ordinal,expected_hash,expected_count))
            qh=((qh^expected_hash)*1099511628211)&((1<<64)-1)
    require(_mix(trace_hash,_hash_records(obj['final']))==obj['trace_hash'],'cache full trace identity')
    obj['query_hash']=qh;obj['API_calls']=2*obj['U']+obj['queries']
    phases=[];n=u64();require(1<=n<=16,'cache phase bound')
    previous_end=0
    for _ in range(n):
        name=text();p=[u64() for _ in range(10)]
        require(p[0]==previous_end and p[0]<p[1]<=obj['U'] and p[2]>0,'cache phase boundary/query schedule')
        requests=1469598103934665603;phase_qh=1469598103934665603;queries=returned=0
        for j in range(p[0],p[1]):
            values,count=steps[j]
            require(bool(values[3])==((j-p[0]+1)%p[2]==0),'cache phase query schedule')
            for value in values:requests=_mix(requests,value)
            if values[3]:queries+=1;returned+=count;phase_qh=_mix(phase_qh,values[-1])
        require((queries,returned,phase_qh,requests)==tuple(p[6:]),'cache phase full identity')
        previous_end=p[1]
        phases.append({'phase':name,'begin_unit':p[0],'end_unit':p[1],'q':0 if p[2]>obj['U'] else p[2],
                       'c':p[3],'shuffle_incoming':bool(p[4]),'random_every_delete':bool(p[5]),
                       'phase_query_count':p[6],'phase_returned':p[7]})
    require(previous_end==obj['U'],'cache phase coverage')
    payload_end=pos;stored=u64();require(pos==len(data),'cache trailing bytes')
    checksum=1469598103934665603
    for byte in data[:payload_end]:checksum=((checksum^byte)*1099511628211)&((1<<64)-1)
    require(checksum==stored,'cache payload checksum')
    require(len(obj['initial'])==obj['N']==len(obj['final']),'cache N shape')
    require(obj['initial']==sorted(obj['initial']) and obj['final']==sorted(obj['final']),'record ordering')
    require(len(query_steps)==obj['queries'] and sum(q[2] for q in query_steps)==obj['returned'],'query count identity')
    expected=Path(expected_path).read_bytes();require(expected[:8]==b'S0EXP001','expected schema');ep=8
    for api,h,c in query_steps:
        require(ep+16<=len(expected),'expected truncated');a,n=struct.unpack_from('<QQ',expected,ep);ep+=16
        require(a==api and n==c and ep+16*n<=len(expected),'expected API/count identity')
        rs=[struct.unpack_from('<QQ',expected,ep+j*16) for j in range(n)];ep+=16*n
        require(rs==sorted(rs) and _hash_records(rs)==h,'expected full record/hash identity')
    require(ep==len(expected),'expected trailing bytes')
    obj['phases']=phases
    return obj

def _record_sha(rs):
    return hashlib.sha256(b''.join(struct.pack('<QQ',*r) for r in rs)).hexdigest()

def _config_logical(path):
    data=Path(path).read_bytes()
    require(data.endswith(b'\n'),'config missing final newline')
    logical=data[:-2] if data.endswith(b'\r\n') else data[:-1]
    require(not logical.endswith((b'\r',b'\n')),'config extra final newline')
    return logical,hashlib.sha256(logical).hexdigest()

def validate_pair(path,*,test_fixture=False,trust=None):
    path=Path(path);m=load(path)
    require(m.get('schema')=='S1.pair.lock.v1','pair lock schema')
    fixture=m.get('test_fixture') is True
    require(m.get('mode') in ('native','latency','resource'),'registered measurement mode required')
    require(fixture==test_fixture,'fixture/production boundary')
    if fixture:require(m.get('origin','').startswith('ENGINEERING_FIXTURE'),'fixture origin absent')
    else:
        require(trust is not None and trust.get('lock_sha256')==sha(path),'external immutable pair lock required')
        require(trust.get('protocol_sha256')==sha(PROTOCOL),'registered protocol trust mismatch')
        require(m['source_bundle_sha']==trust.get('source_bundle_sha'),'source trust mismatch')
    files=m['files'];require(set(files)>={'cache','expected','meta','binary','generator','protocol','pin','topology'},'asset inventory')
    for name,binding in files.items():
        require(Path(binding['path']).is_absolute(),'asset path must be absolute')
        require(sha(binding['path'])==binding['sha256'],f'{name} byte binding')
        if not fixture and name in ('binary','pin','topology','generator','protocol'):
            require(trust.get(name+'_sha256')==binding['sha256'],f'{name} frozen trust mismatch')
    source_files=m['source_files'];require(source_files,'empty source bundle')
    source_text=''
    for name,binding in sorted(source_files.items()):
        require(sha(binding['path'])==binding['sha256'],'source file byte binding')
        source_text+=name+'\n'+binding['sha256']+'\n'
    require(hashlib.sha256(source_text.encode()).hexdigest()==m['source_bundle_sha'],'source bundle fingerprint')
    cache=cache_identity(files['cache']['path'],files['expected']['path'],test_fixture)
    meta=load(files['meta']['path']);require(meta['schema']=='S1.cache.v1','metadata schema')
    require(meta['case_id']==m['case_id'] and meta['seed']==m['seed'] and meta['profile']==m['profile'],'metadata input/profile identity')
    require(meta['engineering_only'] is fixture,'engineering metadata boundary')
    if not fixture:
        _registered_cache(meta,cache)
        frozen=verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        require(files['binary']['sha256']==frozen['binary_sha'][f"s1_{m['mode']}.exe"],'binary/mode frozen identity')
    for key in ('seed','N','U','queries','API_calls','domain','source_rows','month','days','ordered','q','c','dataset_sha','protocol_sha'):
        require(meta[key]==cache[key],f'cache/meta {key} identity')
    for key,asset in [('cache_sha','cache'),('expected_sha','expected'),('protocol_sha','protocol'),('generator_sha','generator')]:
        require(meta[key]==files[asset]['sha256'],f'meta {key} byte identity')
    require(meta['initial_sha']==_record_sha(cache['initial']) and meta['final_sha']==_record_sha(cache['final']),'initial/final content identity')
    require(meta['selection_input_identity']==f"{m['case_id']}:{m['seed']}:{files['cache']['sha256']}",'selection input identity')
    phases=cache['phases'];require(meta['phase_lengths']==[p['end_unit']-p['begin_unit'] for p in phases],'phase lengths identity')
    require(meta['phase_q']==[p.get('q',meta['q']) for p in phases] and meta['phase_c']==[p.get('c',meta['c']) for p in phases],'phase q/c identity')
    require(sum(p['phase_query_count'] for p in phases)==meta['queries'] and sum(p['phase_returned'] for p in phases)==cache['returned'],'phase query sums')
    children=m['children'];require(len(children)==4 and len({c['path'] for c in children})==4,'whole pair requires four distinct children')
    rows=[];previous_end=-1
    for i,(child,rotation) in enumerate(zip(children,schedule())):
        d=Path(child['path']);require(d.is_absolute() and not (d/'failure.json').exists(),'failure/invalid whole pair')
        required={'raw_native.csv','phase.csv','config.json','run_receipt.json','process.json','stdout.txt','stderr.txt'}
        if m['mode']!='native':required|={'conversion_events.csv','latency.csv','latency_summary.json'}
        if m['mode']=='resource':required.add('resource.csv')
        require(set(child['files'])>=required,'child sidecar inventory')
        for name,digest in child['files'].items():require(sha(d/name)==digest,f'{name} byte binding')
        raw=csv_rows(d/'raw_native.csv');require(len(raw)==1,'exactly one raw row required');row=raw[0]
        role=rotation['role'];rnd=rotation['round'];method=m['reference'] if role=='A' else m['candidate']
        identities={'batch_id':m['batch_id'],'attempt_id':m['attempt_id'],'pair_id':m['pair_id'],
                    'case_id':m['case_id'],'seed':str(m['seed']),'role':role,'round':str(rnd),'method':method,
                    'measurement_mode':m['mode'],'status':'valid','cache_sha':files['cache']['sha256'],
                    'dataset_sha':meta['dataset_sha'],'protocol_sha':files['protocol']['sha256'],
                    'binary_sha':files['binary']['sha256'],'source_bundle_sha':m['source_bundle_sha'],
                    'selected_theta':method[8:] if method.startswith('M_EVENT_') else 'NA',
                    'selected_h':method[8:] if method.startswith('M_FIXED_') else 'NA'}
        for key,value in identities.items():require(row.get(key)==value,f'raw {key} identity')
        for key in ('N','U','queries','API_calls','returned','query_hash'):
            require(row[key]==str(cache[key]),f'raw {key} content identity')
        for boundary in ('start','end'):
            for field,value in [('mask','8'),('cpu','3'),('group','0')]:require(row[f'placement_{boundary}_{field}']==value,'placement violation')
        for c in ('build','online','total','destroy','lifecycle'):positive(row[c+'_ns'])
        require(int(row['total_ns'])==int(row['build_ns'])+int(row['online_ns']),'total arithmetic')
        require(int(row['lifecycle_ns'])==int(row['total_ns'])+int(row['destroy_ns']),'lifecycle arithmetic')
        for key,limit in [('peak_tree_buckets',32),('final_tree_buckets',32),('cand_max',4096)]:
            if method!='Original':require(0<=int(row[key])<=limit,'budget violation')
        require(row['conversion_failures']==('NA' if method=='Original' else '0'),'conversion failure/unavailable identity')
        if m['mode']!='resource' or method=='Original':
            for account in ('pool','buckets','tree','manager'):
                for metric in ('current','peak','allocations','frees'):require(row[f'{account}_{metric}']=='NA','unavailable owner must be NA')
        else:
            for account in ('pool','buckets','tree','manager'):
                for metric in ('current','peak','allocations','frees'):require(int(row[f'{account}_{metric}'])>=0,'observable owner must be a nonnegative integer')
        if method in ('M_LIST','Original'):require(row['total_avoidable_work']=='NA','unavailable work must be NA')
        logical,config_sha=_config_logical(d/'config.json');require(row['config_sha']==config_sha,'logical config SHA')
        config=load(d/'config.json');require(config['schema']=='S1.method.v1' and config['method']==method and config['mode']==m['mode'],'config identity')
        credit='event' if method.startswith('M_EVENT_') else 'none' if method.startswith('M_FIXED_') else 'NA' if method in ('Original','M_LIST') else 'ns'
        require(config['credit_unit']==row['credit_unit']==credit,'credit unit identity')
        require(config==m['config_logical'][str(d)],'frozen method config identity')
        if not fixture:require(config_sha==trust['config_sha256'][method],'frozen config trust mismatch')
        process=load(d/'process.json');require(process['exit_code']==0 and process['order_index']==i,'process exit/order')
        require(previous_end<=process['started_ns']<process['ended_ns'],'serial process timing');previous_end=process['ended_ns']
        expected_command=child_command(files['pin']['path'],files['binary']['path'],files['cache']['path'],files['cache']['sha256'],method,d,m['batch_id'],m['attempt_id'],m['pair_id'],rnd,role)
        require(process['command']==expected_command,'process command exact identity')
        require((d/'stdout.txt').read_text(encoding='utf-8')==f"verified {m['mode']} {method} valid\n" and not (d/'stderr.txt').read_bytes(),'success stdout/stderr evidence')
        receipt=load(d/'run_receipt.json')
        receipt_expected={'schema':'S1.run.v1','status':'valid','engineering_only':False,'measurement_mode':m['mode'],
                          'cache_sha_before':files['cache']['sha256'],'cache_sha_after':files['cache']['sha256'],
                          'expected_sha_before':files['expected']['sha256'],'expected_sha_after':files['expected']['sha256'],
                          'metadata_sha':files['meta']['sha256'],'binary_sha':files['binary']['sha256'],
                          'source_bundle_sha':m['source_bundle_sha'],'config_sha':config_sha,'protocol_sha':files['protocol']['sha256'],
                          'phase_clock_native':'fixed_phase_boundaries_only','actual_affinity_mask_start':8,
                          'actual_affinity_mask_end':8,'actual_cpu_start':3,'actual_cpu_end':3,
                          'account_availability':'matched four accounts enabled' if m['mode']=='resource' and method!='Original' else 'NA'}
        for key,value in receipt_expected.items():require(receipt.get(key)==value,f'receipt {key} identity')
        phase_rows=csv_rows(d/'phase.csv');require(len(phase_rows)==len(phases),'phase rows complete')
        for p,expected_phase in zip(phase_rows,phases):
            for key in identities:require(p[key]==row[key],f'phase/raw {key} identity')
            for key in ('config_sha','N','U','queries','API_calls','returned','query_hash'):require(p[key]==row[key],'phase/raw content identity')
            for key in ('phase','begin_unit','end_unit','phase_query_count','phase_returned'):require(str(expected_phase[key])==p[key],'phase definition identity')
            positive(p['online_ns'])
        require(sum(int(p['online_ns']) for p in phase_rows)==int(row['online_ns']),'phase online sum')
        rows.append(row)
    ratios={component:two_round_ratio([(rows[0][component+'_ns'],rows[1][component+'_ns']),
                                      (rows[3][component+'_ns'],rows[2][component+'_ns'])]) for component in ('build','online','total')}
    return {'rows':rows,'ratios':ratios,'manifest_sha256':sha(path),'case_id':m['case_id'],'seed':m['seed'],
            'reference':m['reference'],'candidate':m['candidate'],'test_fixture':fixture,'profile':m['profile'],'mode':m['mode']}

def can_resume(path,**kwargs):
    try:validate_pair(path,**kwargs);return True
    except (ValueError,KeyError,TypeError,OSError):return False

def verify_environment(receipt,*,now_ns=None,max_age_seconds=300):
    r=load(receipt) if isinstance(receipt,(str,Path)) else receipt
    required={'schema':'S1.environment.v1','test_fixture':False,'platform':'Windows','mask':8,'cpu':3,'group':0,
              'core_class':'P','quiet_api':'GetSystemTimes','initial_seconds':2,'min_subsequent_seconds':.2,
              'retry_seconds':2,'max_wait_seconds':300,'max_busy_fraction':.1,'status':'valid'}
    for key,value in required.items():require(r.get(key)==value,'fresh real environment receipt missing/invalid')
    now_ns=time.time_ns() if now_ns is None else now_ns
    require(0<=now_ns-r['ended_ns'] and (max_age_seconds is None or now_ns-r['ended_ns']<=max_age_seconds*1e9),'environment receipt stale')
    require(r['started_ns']<r['ended_ns'] and r['samples'],'environment measurements missing')
    for sample in r['samples']:
        require(sample['seconds']>=.2 and 0<=sample['busy_fraction']<=1,'quiet sample invalid')
    require(r['samples'][0]['seconds']>=2 and r['samples'][-1]['busy_fraction']<=.1,'quiet guard failed')
    for name in ('topology','pin'):
        require(sha(r[name+'_path'])==r[name+'_sha256'],'environment tool byte mismatch')
    return r

def _file_binding(binding):
    require(isinstance(binding,dict) and Path(binding.get('path','')).is_absolute(),'absolute bound file required')
    require(sha(binding['path'])==binding.get('sha256'),'entry bound file bytes')
    return binding

def _context_binding(receipt,context,names,*,test_fixture):
    context=context or {}
    require(set(receipt.get('bindings',{}))==set(names),'complete cross-asset bindings required')
    for name in names:
        require(name in context,'validated dependency absent: '+name)
        frozen=context[name];bound=_file_binding(receipt['bindings'][name])
        require(Path(bound['path']).resolve()==Path(frozen['path']).resolve() and bound['sha256']==frozen['sha256'],'cross-asset frozen identity')
        require(load(bound['path'])==frozen['receipt'],'cross-asset receipt bytes')
        require(frozen['receipt'].get('test_fixture') is test_fixture,'cross-asset fixture boundary')
    return context

def _selected_identity(context,*,test_fixture):
    frozen=(context or {}).get('dev_selection',{})
    selected=frozen.get('verified')
    if test_fixture and selected is None:selected=frozen.get('receipt')
    require(isinstance(selected,dict) and selected.get('selected_theta') in (8,16,32,64)
            and selected.get('selected_h') in (128,512,2048,8192),'validated dev selection dependency required')
    return selected

def _native_config(entry,method,context,*,test_fixture):
    require(entry.get('mode')=='native' and entry.get('protocol_sha256')==sha(PROTOCOL),'native/protocol plan identity')
    source=context['protocol_and_sources']['receipt'];binaries=context['frozen_binaries']['receipt']
    require(entry.get('source_bundle_sha')==source['source_bundle_sha']==binaries['source_bundle_sha'],'plan source identity')
    binary=_file_binding(entry['binary'])
    native=[e for e in binaries['entries'] if e['name']=='s1_native.exe']
    require(len(native)==1,'one frozen native binary required')
    frozen=_file_binding(native[0])
    require(Path(binary['path']).resolve()==Path(frozen['path']).resolve() and binary['sha256']==frozen['sha256'],'plan frozen native binary')
    config=_file_binding(entry['config']);logical,digest=_config_logical(config['path']);obj=load(config['path'])
    credit='event' if method.startswith('M_EVENT_') else 'none' if method.startswith('M_FIXED_') else 'NA' if method in ('Original','M_LIST') else 'ns'
    require(obj=={'schema':'S1.method.v1','method':method,'mode':'native','credit_unit':credit,'frozen_R6':source['frozen_R6']},'plan full method/parameter config')
    require(config.get('logical_sha256')==digest,'plan config logical SHA')
    if not test_fixture and method.startswith(('M_EVENT_','M_FIXED_')) and 'dev_selection' in context:
        selected=_selected_identity(context,test_fixture=False)
        require(binary['sha256']==selected['native_binary_sha256'] and entry['source_bundle_sha']==selected['source_bundle_sha']
                and digest==selected['method_config_sha256'][method],'selected method binary/source/config identity')
    return config

def _inventory_identity(name,receipt,*,test_fixture=False,trust=None,context=None,phase='start'):
    require(phase in ('start','complete'),'entry gate phase must be start or complete')
    require(receipt.get('schema')=='S1.entry.asset.v1' and receipt.get('asset')==name,'entry asset schema/identity')
    require(receipt.get('test_fixture') is test_fixture,'entry fixture/production boundary')
    if test_fixture:require(receipt.get('origin','').startswith('ENGINEERING_FIXTURE'),'entry fixture origin')
    entries=receipt.get('entries',[])
    if name in ('dev_trace_inventory','formal_trace_inventory'):
        cases=[f'D{i:02}' for i in range(1,11)] if name=='dev_trace_inventory' else [f'F{i:02}' for i in range(1,8)]
        seeds=range(90001,90004) if name=='dev_trace_inventory' else range(91001,91011)
        expected={(c,s) for c in cases for s in seeds}
        keys=[(e['case_id'],e['seed']) for e in entries]
        require(len(keys)==len(expected) and set(keys)==expected,'trace inventory missing/duplicate/identity')
        for e in entries:
            cache=cache_identity(e['cache_path'],e['expected_path'],test_fixture);meta=load(e['metadata_path'])
            require(meta['case_id']==e['case_id'] and meta['seed']==e['seed'] and meta['engineering_only'] is test_fixture,'trace fixture/input identity')
            for k in ('N','U','queries','API_calls','seed','domain','dataset_sha','protocol_sha'):
                require(meta[k]==cache[k],'real trace cache/meta identity')
            require(meta['cache_sha']==sha(e['cache_path']) and meta['expected_sha']==sha(e['expected_path']),'real trace byte identity')
            require(meta['initial_sha']==_record_sha(cache['initial']) and meta['final_sha']==_record_sha(cache['final']),'real trace initial/final identity')
            if not test_fixture:_registered_cache(meta,cache)
    elif name in ('dev_aa_inventory','formal_aa_inventory'):
        scope='dev' if name=='dev_aa_inventory' else 'final'
        methods,cases=(('M_LIST','M_EVENT_16'),('D02','D06')) if scope=='dev' else (('Original','M_LIST','R6'),('F01','F03','F06'))
        timepoints=('before',) if phase=='start' else ('before','after')
        expected={(t,m,c,b) for t in timepoints for m in methods for c in cases for b in range(1,6)}
        keys=[(e['timepoint'],e['method'],e['case_id'],e['block']) for e in entries]
        require(len(keys)==len(expected) and set(keys)==expected,'AA inventory missing/duplicate/identity')
        require(bool(receipt.get('batch_id')) and isinstance(receipt.get('environment_sha256'),str)
                and len(receipt['environment_sha256'])==64,'AA batch/environment identity required')
        if context is not None:
            require(receipt['environment_sha256']==context.get('fresh_environment_receipt',{}).get('sha256'),'AA current environment identity')
        pair_ids=set();rows=[]
        for e in entries:
            binding=None if test_fixture else (trust or {}).get('pair_trust',{}).get(str(Path(e['pair_path']).resolve()))
            pair=validate_pair(e['pair_path'],test_fixture=test_fixture,trust=binding)
            require(pair['profile']=='aa' and pair['mode']=='native' and pair['seed']==92001 and pair['case_id']==e['case_id'],'AA pair input identity')
            require(pair['reference']==pair['candidate']==e['method'],'AA identical methods required')
            require(e.get('batch_id')==receipt['batch_id'] and all(r['batch_id']==receipt['batch_id'] for r in pair['rows']),'AA same batch required')
            pid=pair['rows'][0]['pair_id'];require(pid not in pair_ids,'AA blocks need independent pair IDs');pair_ids.add(pid)
            for r in pair['rows']:
                rows.append({'timepoint':e['timepoint'],'method':e['method'],'case_id':e['case_id'],'seed':92001,
                             'block':e['block'],'round':int(r['round']),'role':r['role'],'status':'valid',
                             **{c:int(r[c+'_ns']) for c in ('build','online','total')}})
        observed=None
        if phase=='complete':
            from analysis import aa_floor
            observed=aa_floor(rows,scope)
            require(receipt.get('observed_floor')==observed,'AA observed floor identity')
        return {'phase':phase,'observed_floor':observed,'rows':rows,'batch_id':receipt['batch_id']}
    elif name=='frozen_binaries':
        frozen=verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')
        require(receipt.get('source_bundle_sha')==frozen['source_bundle_sha'],'entry frozen source bundle')
        actual={e['name']:sha(e['path']) for e in entries}
        require(len(actual)==len(entries),'frozen binary identities must be unique')
        require(actual=={k:v for k,v in frozen['binary_sha'].items() if k.startswith('s1_')},'three frozen production binaries required')
    elif name=='protocol_and_sources':
        require(receipt.get('source_bundle_sha')==verify_driver(S1/'artifacts/driver/green_review_fixes_root_01/manifest.json')['source_bundle_sha'],'entry source bundle')
        frozen=load(S1/'artifacts/driver/green_review_fixes_root_01/native_cli/R6/config.json')['frozen_R6']
        require(receipt.get('frozen_R6')==frozen,'registered frozen parameters required')
    elif name=='dev_selection':
        from select_dev import verify_selection
        if 'selection' in receipt:
            bound=_file_binding(receipt['selection'])
            selection_trust={'sha256':(trust or {}).get('selection_sha256'),'pair_trust':(trust or {}).get('pair_trust')}
            if not test_fixture:require(bound['sha256']==selection_trust['sha256'],'external write-once selection freeze required')
            return verify_selection(bound['path'],test_fixture=test_fixture,trust=selection_trust)
        if test_fixture:return verify_selection(receipt,test_fixture=True)
        require(trust is not None and trust.get('path'),'externally frozen selection asset required')
        require(load(trust['path'])==receipt,'selection receipt/file identity')
        return verify_selection(trust['path'],trust=trust)
    elif name=='selected_configs':
        ctx=_context_binding(receipt,context,('dev_selection','frozen_binaries','protocol_and_sources'),test_fixture=test_fixture)
        selected=_selected_identity(ctx,test_fixture=test_fixture)
        theta,h=selected['selected_theta'],selected['selected_h'];methods={f'M_EVENT_{theta}',f'M_FIXED_{h}'}
        require(len(entries)==2 and {e.get('method') for e in entries}==methods,'two selected method configs required')
        for e in entries:
            method=e['method'];require(e.get('schema')=='S1.selected.config.v1','selected entry schema')
            require(e.get('selected_theta')==(theta if method.startswith('M_EVENT_') else None)
                    and e.get('selected_h')==(h if method.startswith('M_FIXED_') else None),'selected threshold mismatch')
            _native_config(e,method,ctx,test_fixture=test_fixture)
    elif name in ('start_manifest','final_start_manifest'):
        formal=name=='final_start_manifest';profile='final' if formal else 'dev'
        trace_name='formal_trace_inventory' if formal else 'dev_trace_inventory';aa_name='formal_aa_inventory' if formal else 'dev_aa_inventory'
        dependencies=('frozen_binaries','protocol_and_sources',trace_name,aa_name,'fresh_environment_receipt')+(('dev_selection','selected_configs') if formal else ())
        ctx=_context_binding(receipt,context,dependencies,test_fixture=test_fixture)
        require(receipt.get('status')=='NOT_RUN' and receipt.get('profile')==profile and bool(receipt.get('batch_id')),'unexecuted start batch/profile required')
        aa=ctx[aa_name]['receipt']
        require(aa['batch_id']==receipt['batch_id'] and aa['environment_sha256']==ctx['fresh_environment_receipt']['sha256'],'start AA batch/environment binding')
        traces={(e['case_id'],e['seed']):e for e in ctx[trace_name]['receipt']['entries']}
        inputs={(f'F{i:02}',s) for i in range(1,8) for s in range(91001,91011)} if formal else {(f'D{i:02}',s) for i in range(1,11) for s in range(90001,90004)}
        require(len(ctx[trace_name]['receipt']['entries'])==len(inputs) and set(traces)==inputs,'start complete input inventory')
        if formal:
            selected=_selected_identity(ctx,test_fixture=test_fixture)
            pairs={'P01':('Original','M_LIST'),'P02':('M_LIST','M_OBSERVE_LIST'),'P03':('M_LIST','R6'),'P04':('M_OBSERVE_LIST','R6'),
                   'P05':('Original','R6'),'P06':(f"M_EVENT_{selected['selected_theta']}",'R6'),'P07':(f"M_FIXED_{selected['selected_h']}",'R6'),
                   'P08':('M_NO_IDLE','R6'),'DIA01':('M_EVENT_16','R6'),'DIA02':('M_FIXED_128','R6')}
        else:
            from select_dev import CANDIDATES
            pairs={m:('M_LIST',m) for m in CANDIDATES}
        expected={(c,s,p) for c,s in inputs for p in pairs};keys=[(e.get('case_id'),e.get('seed'),e.get('pair_id')) for e in entries]
        require(len(keys)==len(expected) and set(keys)==expected,'start complete unique pair plan required')
        for e in entries:
            require(e.get('schema')=='S1.start.pair.v1' and e.get('status')=='NOT_RUN' and e.get('children')==4
                    and e.get('batch_id')==receipt['batch_id'] and e.get('profile')==profile,'start entry schema/batch/unexecuted status')
            reference,candidate=pairs[e['pair_id']]
            require((e.get('reference'),e.get('candidate'))==(reference,candidate),'start registered pair methods')
            trace=traces[e['case_id'],e['seed']]
            require(set(e.get('input',{}))=={'cache','expected','meta'},'start input files required')
            for name,key in (('cache','cache_path'),('expected','expected_path'),('meta','metadata_path')):
                binding=_file_binding(e['input'][name])
                require(Path(binding['path']).resolve()==Path(trace[key]).resolve() and binding['sha256']==sha(trace[key]),'start trace identity')
            require(set(e.get('configs',{}))=={reference,candidate},'start method configs required')
            for method,binding in e['configs'].items():_native_config({**e,'config':binding},method,ctx,test_fixture=test_fixture)
    else:raise ValueError('unknown entry asset')
    return receipt

def _registered_cache(meta,cache):
    protocol=load(PROTOCOL);case=meta['case_id'];seed=meta['seed'];profile=meta['profile']
    if profile=='dev':require(case.startswith('D') and seed in protocol['seeds']['dev'],'registered dev input')
    elif profile=='final':require(case.startswith('F') and seed in protocol['seeds']['final'],'registered final input')
    elif profile=='aa':require(case in ('D02','D06','F01','F03','F06') and seed==92001,'registered AA input')
    elif profile=='mechanism':require(case=='M01' and seed in protocol['seeds']['mechanism'],'registered mechanism input')
    else:raise ValueError('unregistered real profile')
    cases={c['id']:c for c in protocol['dev_cases']+protocol['final_cases']}
    if case=='M01':n,u=131072,131072
    else:
        require(case in cases,'unregistered real case');n,u=cases[case]['N'],cases[case]['U']
    require(cache['N']==n and cache['U']==u,'registered N/U required')
    if case=='F04':
        expected=[('sparse_before',0,87381,256,256,False),('shuffle',87381,174762,8,0,True),('sparse_after',174762,262144,256,256,False)]
        require(cache['q']==0 and cache['c']==0,'F04 aggregate q/c')
    elif case=='M01':
        lengths=[32768,16384,32768,16384,32768];names=['A_hot','idle1','B_hot','idle2','A_return'];expected=[];begin=0
        for name,length in zip(names,lengths):expected.append((name,begin,begin+length,0,0,False));begin+=length
        require(cache['q']==0 and cache['c']==0,'M01 aggregate q/c')
    else:
        spec=cases[case];pattern=spec.get('family',spec.get('name'))
        pattern={'low_work':'low','high_work':'high','synthetic_low_work':'low','synthetic_high_work':'high','synthetic_prefix':'prefix'}.get(pattern,pattern)
        expected=[(pattern,0,u,spec.get('q',0),spec.get('c',0),False)]
        require(cache['q']==spec.get('q',0) and cache['c']==spec.get('c',0) and cache['workload']==pattern,'registered workload/q/c')
    actual=[(p['phase'],p['begin_unit'],p['end_unit'],p['q'],p['c'],p['shuffle_incoming']) for p in cache['phases']]
    require(actual==expected and all(p['random_every_delete']==p['shuffle_incoming'] for p in cache['phases']),'registered phase definition')
    require(cache['protocol_sha']==sha(PROTOCOL),'registered real protocol')
    public=case in ('F01','F02','F03','F04')
    require(cache['days']==(31 if public else 0) and cache['ordered']==(case!='F04'),'registered days/ordered')
    require(cache['source_rows']==(2964617 if public else n),'registered source rows')
    require(cache['dataset_sha']==(protocol['dataset']['sha256'] if public else sha(PROTOCOL)),'registered dataset identity')
    require(cache['domain']==({'stride':2964618,'span':2678400} if public else {'stride':1<<40,'span':4096}),'registered domain identity')
    if public:require(sha(protocol['dataset']['path'])==protocol['dataset']['sha256'],'frozen public dataset bytes')

def _dev_completion_identity(context,*,test_fixture=False):
    """Keep historical dev completion and its AA floor separate from final AA."""
    selected=_selected_identity(context,test_fixture=test_fixture)
    aa=context.get('dev_aa_inventory',{}).get('verified',{})
    start=context.get('start_manifest',{}).get('receipt',{})
    require(aa.get('phase')=='complete' and aa.get('observed_floor') is not None,'dev after AA required before formal entry')
    require(start.get('batch_id')==aa.get('batch_id') and context['dev_aa_inventory']['receipt']['environment_sha256']==context['fresh_environment_receipt']['sha256'],'historical dev batch/environment identity')
    require(all(v['batch_id']==aa['batch_id'] for v in selected['identity_bindings'].values()),'selection/historical dev batch identity')
    traces=context['dev_trace_inventory']['receipt']['entries']
    actual={f"{e['case_id']}:{e['seed']}":sha(e['cache_path']) for e in traces}
    require(selected['input_cache_sha']==actual,'selection/historical dev input identity')
    return {'batch_id':aa['batch_id'],'observed_floor':aa['observed_floor']}

def verify_complete_aa(path,*,test_fixture=False,trust=None):
    """Production final interpretation consumes frozen full formal AA evidence."""
    context=None
    if not test_fixture:
        require(trust is not None and trust.get('sha256')==sha(path),'external complete AA inventory freeze required')
        environment=_file_binding(trust.get('environment',{}));r=verify_environment(environment['path'],max_age_seconds=None)
        context={'fresh_environment_receipt':{'sha256':environment['sha256'],'receipt':r}}
    receipt=load(path)
    if not test_fixture:require(receipt.get('validated') is True and receipt.get('protocol_sha256')==sha(PROTOCOL),'validated registered AA inventory required')
    out=_inventory_identity('formal_aa_inventory',receipt,test_fixture=test_fixture,trust=trust,context=context,phase='complete')
    return {**out,'manifest_sha256':sha(path)}

def readiness(correctness,assets,*,asset_trust=None,phase='start',scope='dev'):
    require(phase in ('start','complete'),'entry gate phase must be start or complete')
    require(scope in ('dev','final'),'entry gate scope must be dev or final')
    complete=all(correctness.get(k) is True for k in ('kernel','driver','analysis'))
    dev_required=['fresh_environment_receipt','frozen_binaries','protocol_and_sources','dev_trace_inventory','dev_aa_inventory','start_manifest']
    final_required=['dev_environment_receipt','dev_selection','selected_configs','formal_trace_inventory','formal_aa_inventory','final_start_manifest']
    missing_dev=[x for x in dev_required if not assets.get(x)]
    missing_final=[x for x in final_required if not assets.get(x)]
    environment=False
    context={}
    asset_trust=asset_trust or {}
    def environment_asset(name,fresh):
        path=assets.get(name);external=asset_trust.get(name)
        digest=external.get('sha256') if isinstance(external,dict) else external
        require(isinstance(path,(str,Path)) and sha(path)==digest,'environment external freeze required')
        r=verify_environment(path,max_age_seconds=300 if fresh else None)
        return {'path':str(path),'sha256':digest,'receipt':r}
    if assets.get('fresh_environment_receipt'):
        try:
            context['fresh_environment_receipt']=environment_asset('fresh_environment_receipt',phase=='start');environment=True
        except (ValueError,KeyError):
            if 'fresh_environment_receipt' not in missing_dev:missing_dev.append('fresh_environment_receipt')
    # A caller must independently freeze each validated inventory's bytes. Merely
    # passing {validated:true}, or a self-contained invented SHA, never opens a gate.
    historical_context={}
    if scope=='final' and assets.get('dev_environment_receipt'):
        try:
            historical_context['fresh_environment_receipt']=environment_asset('dev_environment_receipt',False)
            if 'dev_environment_receipt' in missing_final:missing_final.remove('dev_environment_receipt')
        except (ValueError,KeyError,TypeError):
            if 'dev_environment_receipt' not in missing_final:missing_final.append('dev_environment_receipt')
    inventories=dev_required[1:]+(final_required[1:] if scope=='final' else [])
    for name in inventories:
        valid=False
        if isinstance(assets.get(name),dict):
            a=assets[name]
            if a.get('path') and asset_trust.get(name):
                try:
                    external=asset_trust[name]
                    frozen={**external} if isinstance(external,dict) else {'sha256':external}
                    frozen['path']=a['path']
                    valid=sha(a['path'])==frozen.get('sha256')
                    receipt=load(a['path'])
                    valid=valid and receipt.get('validated') is True and receipt.get('test_fixture') is False
                    valid=valid and receipt.get('protocol_sha256')==sha(PROTOCOL)
                    for bound in receipt.get('files',[]):valid=valid and sha(bound['path'])==bound['sha256']
                    valid=valid and bool(receipt.get('files'))
                    if valid:
                        historical=scope=='final' and name in ('dev_trace_inventory','dev_aa_inventory','start_manifest')
                        current_context={**context,**historical_context} if historical else context
                        verified=_inventory_identity(name,receipt,trust=frozen,context=current_context,phase='complete' if historical else phase)
                        context[name]={'path':str(a['path']),'sha256':frozen['sha256'],'receipt':receipt,'verified':verified}
                        if historical:historical_context[name]=context[name]
                except (ValueError,KeyError,TypeError):valid=False
        if name in assets and not valid:
            target=missing_dev if name in dev_required else missing_final
            if name not in target:target.append(name)
    dev=complete and environment and not missing_dev
    dev_floor=None
    if scope=='final':
        try:
            dev_floor=_dev_completion_identity({**context,**historical_context})['observed_floor']
        except (ValueError,KeyError,TypeError):
            if 'dev_aa_inventory' not in missing_dev:missing_dev.append('dev_aa_inventory')
            dev=False
    selection=context.get('dev_selection',{}).get('verified',{}) if scope=='final' and dev and not missing_final else {}
    theta=selection.get('selected_theta') if isinstance(selection,dict) and not missing_final else None
    h=selection.get('selected_h') if isinstance(selection,dict) and not missing_final else None
    final=scope=='final' and dev and not missing_final and theta in (8,16,32,64) and h in (128,512,2048,8192)
    return {'code_correctness_complete':complete,'gate_phase':phase,'gate_scope':scope,'DEV_READY':dev,'FINAL_READY':final,
            'selected_theta':theta,'selected_h':h,'dev_aa_log_floor':dev_floor,
            'formal_aa_log_floor':context.get('formal_aa_inventory',{}).get('verified',{}).get('observed_floor'),
            'missing_dev_assets':missing_dev,'missing_final_assets':missing_final}

def driver_suites():
    native={'SX16','SX17','SX18','SX19','SX22','CACHE_NORMS',
            *[f'REGISTRY_D{i:02}' for i in range(1,11)],
            *[f'REGISTRY_F{i:02}' for i in (1,2,3,5,6,7)],'REGISTRY_M01'}
    observer={'SX16','SX17','SX18','SX22','SX24','CACHE_NORMS'}
    return {*(('native',x) for x in native),*(('latency',x) for x in observer),*(('resource',x) for x in observer)}

def verify_driver(path,expected_sha=DRIVER_SHA):
    path=Path(path);m=load(path);root=path.parent
    require(sha(path)==expected_sha,'driver freeze manifest SHA')
    require(m['schema']=='s1.driver.engineering.v1' and m['status']=='ENGINEERING_GREEN','driver engineering schema')
    coverage=m['coverage'];keys=[(x['mode'],x['id']) for x in coverage]
    require(len(keys)==35 and len(set(keys))==35 and set(keys)==driver_suites(),'actual 35 suite/mode set required')
    require(len(m['commands'])==78,'complete driver command set required')
    evidence=m['evidence_sha'];require(evidence,'driver byte evidence missing')
    for name,digest in evidence.items():require(sha(root/name)==digest,'driver evidence SHA mismatch')
    process_records=[load(root/name) for name in evidence if name.endswith('.process.json')]
    require(len(process_records)==78,'driver process receipts complete')
    for command in m['commands']:require(command in process_records,'manifest command missing process evidence')
    compiles=[x for x in process_records if '-o' in x['command'] and any('clang++' in a for a in x['command'])
              and not any(flag in x['command'] for flag in ('-###','-emit-llvm','-E','-S'))]
    require(len(compiles)==6,'six actual compile commands required')
    for x in compiles:require(x['exit_code']==0 and x.get('compiler_warnings')==[],'compile failure/warnings')
    for c in coverage:
        stem=f"{c['mode']}_{c['id']}";proc=load(root/(stem+'.process.json'))
        require(c['exit_code']==0 and proc['exit_code']==0 and c['command']==proc['command'],'suite process mismatch')
        stdout=(root/(stem+'.stdout.txt')).read_text(encoding='utf-8')
        require(f"PASS {c['id']} engineering correctness only" in stdout,'suite stdout PASS evidence missing')
        require(not (root/(stem+'.stderr.txt')).read_bytes(),'suite stderr unexpected')
    for name,digest in m['source_sha'].items():
        rel=Path(name);require(sha(S1/rel)==digest and sha(root/'source'/rel)==digest,'driver actual/snapshot source mismatch')
    for name,digest in m['artifact_source_sha'].items():require(sha(root/name)==digest,'artifact generated source mismatch')
    for name,digest in m['frozen_dependencies'].items():require(sha(S1.parents[1]/name)==digest,'frozen dependency mismatch')
    for name,digest in m['binary_sha'].items():require(sha(root/name)==digest,'driver binary mismatch')
    bundle_files=[]
    for name,digest in m['source_sha'].items():
        normalized=name.replace('\\','/')
        if normalized.startswith('src/'):bundle_files.append(('S1/'+normalized,digest))
    bundle_files+=list(m['frozen_dependencies'].items())
    text=''.join(n+'\n'+h+'\n' for n,h in sorted(bundle_files))
    require(hashlib.sha256(text.encode()).hexdigest()==m['source_bundle_sha'],'driver source bundle mismatch')
    require(m['formal_timing_or_selection_executed'] is False,'unexpected formal experiment evidence')
    return {'verified':True,'test_fixture':False,'manifest_sha256':sha(path),'suite_count':35,'command_count':78,
            'compiles':6,'compile_warnings':0,'mode_counts':{'native':23,'latency':6,'resource':6},
            'source_bundle_sha':m['source_bundle_sha'],'binary_sha':m['binary_sha'],'evidence_sha':evidence}

def verify_kernel(path,expected_sha=None):
    path=Path(path);m=load(path);root=path.parent
    if expected_sha is not None:require(sha(path)==expected_sha,'kernel freeze manifest SHA')
    require(m['status']=='GREEN' and m['schema']=='S1.kernel.correctness.v1','kernel engineering schema')
    cases=m['cases'];require(len(cases)==99,'kernel99case coverage required')
    modes={'native','debug','owner','diagnostic','asan','ubsan'}
    require({c['mode'] for c in cases}==modes,'kernel six modes required')
    random=[c for c in cases if c['id']=='SX03']
    required={(mode,arm,seed) for mode in ('native','asan','ubsan') for arm in ('List','ObserveList','Fixed','Event','NoIdle') for seed in (94001,94002)}
    require(len(random)==30 and {(c['mode'],c['arm'],c['seed']) for c in random}==required,'kernel random 5x2x3 required')
    seen=set();evidence={}
    for c in cases:
        key=(c['mode'],c['id'],c.get('arm'),c.get('seed'));require(key not in seen,'duplicate kernel case');seen.add(key)
        require(c['status']=='PASS' and c['exit_code']==0,'kernel failure')
        stem=f"{c['mode']}_{c['id']}"+(f"_{c['arm']}_{c['seed']}" if c['id']=='SX03' else '')
        proc=load(root/(stem+'.process.json'));require(proc['exit_code']==0,'kernel process failure')
        stdout=(root/(stem+'.stdout.log')).read_text(encoding='utf-8');stderr=(root/(stem+'.stderr.log')).read_bytes()
        require(not stderr and ('PASS' in stdout),'kernel stdout/stderr evidence')
        require(('--random' if c['id']=='SX03' else c['id']) in proc['command'],'kernel actual command identity')
        if c['id']=='SX03':
            require(c['operations']==100000 and 'operations=100000 mismatches=0' in stdout,'kernel random operations evidence')
            require(str(c['seed']) in proc['command'],'kernel random seed command')
        for suffix in ('.process.json','.stdout.log','.stderr.log'):evidence[stem+suffix]=sha(root/(stem+suffix))
    for name,digest in m['source_sha256'].items():require(sha(S1/name)==digest and sha(root/'source'/name)==digest,'kernel snapshot/current mismatch')
    for mode,b in m['binaries'].items():require(sha(root/(mode+'.exe'))==b['sha256'],'kernel binary mismatch')
    require(m['performance_executed'] is False,'kernel contains experiment')
    return {'verified':True,'test_fixture':False,'manifest_sha256':sha(path),'case_count':99,'random_cases':30,'evidence_sha':evidence}
