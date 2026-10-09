"""Preconstructed ENGINEERING_FIXTURE bytes, not traces or experiment results.

Times, hashes and content are invented solely for deterministic validator tests.
No benchmark subprocess is ever started here.
"""
from pathlib import Path
import csv
import hashlib
import json

ORIGIN = 'ENGINEERING_FIXTURE: predetermined sidecars; NOT_EXPERIMENT_RESULTS'
METHODS = ['M_EVENT_8', 'M_EVENT_16', 'M_EVENT_32', 'M_EVENT_64',
           'M_FIXED_128', 'M_FIXED_512', 'M_FIXED_2048', 'M_FIXED_8192']

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def write_csv(path, rows):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def pair(root, case='D01', seed=90001, candidate='M_EVENT_8', total=200, online=100,
         pair_id=None, profile='dev', reference='M_LIST'):
    root = Path(root); root.mkdir(parents=True)
    identity = pair_id or f'{case}:{seed}:{candidate}'
    assets = root / 'assets'; assets.mkdir()
    for name, content in [('protocol.json', b'ENGINEERING_FIXTURE protocol'),
                          ('binary.exe', b'ENGINEERING_FIXTURE never executable'),
                          ('generator.hpp', b'ENGINEERING_FIXTURE generator'),
                          ('source.hpp', b'ENGINEERING_FIXTURE source'),
                          ('pin.exe', b'ENGINEERING_FIXTURE pin'),
                          ('topology.exe', b'ENGINEERING_FIXTURE topology')]:
        (assets / name).write_bytes(content)
    protocol = sha(assets/'protocol.json'); generator = sha(assets/'generator.hpp')
    source_files = {'S1/src/source.hpp': {'path': str(assets/'source.hpp'), 'sha256': sha(assets/'source.hpp')}}
    bundle = hashlib.sha256(('S1/src/source.hpp\n' + sha(assets/'source.hpp') + '\n').encode()).hexdigest()
    initial = [[10, 1], [20, 2]]; final = [[10, 1], [20, 2]]
    record_bytes = lambda rs: b''.join(int(x).to_bytes(8,'little') for r in rs for x in r)
    cache_obj = {'schema':'ENGINEERING_FIXTURE.cache.v1', 'origin':ORIGIN, 'case_id':case, 'seed':seed,
                 'N':2, 'U':2, 'queries':1, 'API_calls':5, 'returned':1, 'query_hash':123,
                 'initial':initial, 'final':final, 'dataset_sha':protocol, 'protocol_sha':protocol,
                 'domain':{'stride':1000,'span':4096}, 'source_rows':2, 'month':'synthetic',
                 'days':0, 'ordered':True, 'q':2,'c':0,
                 'phases':[{'phase':'fixture','begin_unit':0,'end_unit':2,'phase_query_count':1,'phase_returned':1}]}
    write_json(assets/'cache.bin', cache_obj)
    (assets/'cache.expected.bin').write_bytes(b'ENGINEERING_FIXTURE expected')
    cache_sha = sha(assets/'cache.bin'); expected_sha = sha(assets/'cache.expected.bin')
    meta = {'schema':'S1.cache.v1','case_id':case,'profile':profile,'engineering_only':True,
            'seed':seed,'N':2,'U':2,'domain':cache_obj['domain'],'phase_lengths':[2],
            'q':2,'c':0,'phase_q':[2],'phase_c':[0],'API_calls':5,'queries':1,
            'source_rows':2,'month':'synthetic','days':0,'ordered':True,
            'dataset_sha':protocol,'protocol_sha':protocol,'generator_sha':generator,
            'cache_sha':cache_sha,'expected_sha':expected_sha,
            'initial_sha':hashlib.sha256(record_bytes(initial)).hexdigest(),
            'final_sha':hashlib.sha256(record_bytes(final)).hexdigest(),
            'selection_input_identity':f'{case}:{seed}:{cache_sha}'}
    write_json(assets/'cache.meta.json',meta)
    files = {name:{'path':str(assets/file),'sha256':sha(assets/file)} for name,file in
             [('cache','cache.bin'),('expected','cache.expected.bin'),('meta','cache.meta.json'),
              ('protocol','protocol.json'),('binary','binary.exe'),('generator','generator.hpp'),
              ('pin','pin.exe'),('topology','topology.exe')]}
    children=[]
    for rnd,role in [(1,'A'),(1,'B'),(2,'B'),(2,'A')]:
        method=reference if role=='A' else candidate
        credit='event' if method.startswith('M_EVENT_') else 'none' if method.startswith('M_FIXED_') else 'NA' if method in ('M_LIST','Original') else 'ns'
        d=root/f'r{rnd}{role}'; d.mkdir()
        config_text=json.dumps({'schema':'S1.method.v1','method':method,'mode':'native',
                                'credit_unit':credit,'frozen_R6':{'fixture':ORIGIN}},separators=(',',':'))
        (d/'config.json').write_bytes((config_text+'\n').encode())
        config_sha=hashlib.sha256(config_text.encode()).hexdigest()
        bn,on=(100,100) if role=='A' else (total-online,online)
        row={'batch_id':'ENGINEERING_FIXTURE','attempt_id':'fixture-1','case_id':case,'seed':str(seed),
             'pair_id':identity,'round':str(rnd),'role':role,'method':method,
             'selected_theta':method[8:] if method.startswith('M_EVENT_') else 'NA',
             'selected_h':method[8:] if method.startswith('M_FIXED_') else 'NA',
             'measurement_mode':'native','cache_sha':cache_sha,'dataset_sha':protocol,
             'protocol_sha':protocol,'source_bundle_sha':bundle,'binary_sha':files['binary']['sha256'],
             'config_sha':config_sha,'N':'2','U':'2','queries':'1','API_calls':'5','returned':'1',
             'query_hash':'123','status':'valid','build_ns':str(bn),'online_ns':str(on),
             'total_ns':str(bn+on),'destroy_ns':'10','lifecycle_ns':str(bn+on+10),
             'peak_tree_buckets':'NA' if method=='Original' else '0','final_tree_buckets':'0',
             'cand_max':'NA' if method=='Original' else '0','conversion_failures':'NA' if method=='Original' else '0',
             'credit_unit':credit,'total_avoidable_work':'NA' if method in ('M_LIST','Original') else '5'}
        for end in ['start','end']:
            for key,value in [('mask','8'),('cpu','3'),('group','0')]: row[f'placement_{end}_{key}']=value
        for account in ['pool','buckets','tree','manager']:
            for metric in ['current','peak','allocations','frees']: row[f'{account}_{metric}']='NA'
        write_csv(d/'raw_native.csv',[row])
        phase={**row,**cache_obj['phases'][0],'online_ns':str(on)}; write_csv(d/'phase.csv',[phase])
        receipt={'schema':'S1.run.v1','status':'valid','engineering_only':False,'measurement_mode':'native',
                 'cache_sha_before':cache_sha,'cache_sha_after':cache_sha,'expected_sha_before':expected_sha,
                 'expected_sha_after':expected_sha,'metadata_sha':files['meta']['sha256'],
                 'binary_sha':files['binary']['sha256'],'source_bundle_sha':bundle,'config_sha':config_sha,
                 'protocol_sha':protocol,'phase_clock_native':'fixed_phase_boundaries_only',
                 'actual_affinity_mask_start':8,'actual_affinity_mask_end':8,
                 'actual_cpu_start':3,'actual_cpu_end':3,'account_availability':'NA'}
        write_json(d/'run_receipt.json',receipt)
        command=[files['pin']['path'],'0x8',files['binary']['path'],'run','--cache',files['cache']['path'],
                 '--cache-sha',cache_sha,'--method',method,'--output',str(d),'--batch-id','ENGINEERING_FIXTURE',
                 '--attempt-id','fixture-1','--pair-id',identity,'--round',str(rnd),'--role',role]
        write_json(d/'process.json',{'command':command,'exit_code':0,'order_index':len(children),
                                    'started_ns':len(children)*10+1,'ended_ns':len(children)*10+2})
        (d/'stdout.txt').write_text(f'verified native {method} valid\n',encoding='utf-8')
        (d/'stderr.txt').write_bytes(b'')
        children.append({'path':str(d),'files':{name:sha(d/name) for name in
                         ['raw_native.csv','phase.csv','config.json','run_receipt.json','process.json','stdout.txt','stderr.txt']}})
    manifest={'schema':'S1.pair.lock.v1','test_fixture':True,'origin':ORIGIN,'profile':profile,
              'batch_id':'ENGINEERING_FIXTURE','attempt_id':'fixture-1','pair_id':identity,
              'case_id':case,'seed':seed,'reference':reference,'candidate':candidate,'mode':'native',
              'files':files,'source_files':source_files,'source_bundle_sha':bundle,'children':children,
              'config_logical':{c['path']:json.loads((Path(c['path'])/'config.json').read_text()) for c in children}}
    write_json(root/'pair_fixture.json',manifest)
    return root/'pair_fixture.json'

def rebind_child(manifest, index, filename):
    m=json.loads(Path(manifest).read_text()); c=m['children'][index]
    c['files'][filename]=sha(Path(c['path'])/filename); write_json(manifest,m)

def rebind_asset(manifest, name):
    m=json.loads(Path(manifest).read_text()); m['files'][name]['sha256']=sha(m['files'][name]['path']); write_json(manifest,m)
