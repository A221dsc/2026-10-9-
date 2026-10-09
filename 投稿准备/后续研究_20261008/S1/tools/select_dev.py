"""Write-once dev selector. Input files are verified whole pairs, never raw alone."""
from pathlib import Path
import json
import math
from entry_gate import validate_pair, sha, load

CANDIDATES=[*[f'M_EVENT_{x}' for x in (8,16,32,64)],*[f'M_FIXED_{x}' for x in (128,512,2048,8192)]]
INPUTS={(f'D{i:02}',s) for i in range(1,11) for s in (90001,90002,90003)}
FAMILIES={'endpoint':('D01','D02'),'low_work':('D03','D04'),'high_work':('D05','D06'),
          'prefix':('D07','D08'),'competition':('D09','D10')}

def choose_score(scores):
    scores=list(scores)
    if not scores or not all(math.isfinite(score) for _,score in scores):raise ValueError('invalid candidate score')
    # Tuple ordering applies the smaller threshold only when float scores equal.
    return min(scores,key=lambda x:(x[1],x[0]))[0]

def select(paths,*,test_fixture=False,trust=None):
    paths=list(paths)
    if len(paths)!=240 or len({str(Path(p).resolve()) for p in paths})!=240:raise ValueError('240 distinct complete dev pairs required')
    cells={};hashes={};input_hashes={};identities={};common={};configs={}
    for p in paths:
        binding=None if test_fixture else (trust or {}).get(str(Path(p).resolve()))
        out=validate_pair(p,test_fixture=test_fixture,trust=binding)
        key=(out['case_id'],out['seed'],out['candidate'])
        if key in cells or key[:2] not in INPUTS or key[2] not in CANDIDATES or out['reference']!='M_LIST' or out['profile']!='dev' or out['mode']!='native':raise ValueError('dev identity missing/duplicate/unregistered')
        cache=out['rows'][0]['cache_sha'];previous=input_hashes.setdefault(key[:2],cache)
        if previous!=cache:raise ValueError('candidates do not share identical input bytes')
        cells[key]=math.log(out['ratios']['total']);hashes[str(Path(p).resolve())]=out['manifest_sha256']
        lock=load(p)
        for name,value in {'native_binary_sha256':lock['files']['binary']['sha256'],
                           'protocol_sha256':lock['files']['protocol']['sha256'],'source_bundle_sha':lock['source_bundle_sha']}.items():
            if common.setdefault(name,value)!=value:raise ValueError('dev candidates must share frozen binary/protocol/source')
        for row in out['rows']:
            if configs.setdefault(row['method'],row['config_sha'])!=row['config_sha']:raise ValueError('dev method config varies between inputs')
        identities[str(Path(p).resolve())]={'batch_id':lock['batch_id'],'source_bundle_sha':lock['source_bundle_sha'],
            'files':lock['files'],'source_files':lock['source_files'],
            'child_files':{c['path']:c['files'] for c in lock['children']},'config_logical':lock['config_logical']}
    if set(cells)!={(c,s,m) for c,s in INPUTS for m in CANDIDATES}:raise ValueError('complete 30 x 8 dev matrix required')
    scores={m:math.fsum(cells[c,s,m] for c,s in sorted(INPUTS))/30 for m in CANDIDATES}
    theta=choose_score([(int(m[8:]),scores[m]) for m in CANDIDATES if m.startswith('M_EVENT_')])
    h=choose_score([(int(m[8:]),scores[m]) for m in CANDIDATES if m.startswith('M_FIXED_')])
    return {'schema':'S1.dev_selection.v1','test_fixture':test_fixture,
            'origin':'ENGINEERING_FIXTURE: NOT_EXPERIMENT_RESULTS' if test_fixture else 'registered complete dev pairs',
            'objective':'equal_weight_mean_log_two_round_total_ratio','inputs':30,'children':960,
            'scores':scores,'family_input_counts':{name:6 for name in FAMILIES},'selected_theta':theta,'selected_h':h,
            'pair_manifest_sha':hashes,'input_cache_sha':{f'{c}:{s}':v for (c,s),v in sorted(input_hashes.items())},
            'identity_bindings':identities,
            **common,'method_config_sha256':configs,
            'selection_rule':'exact_float_tie_then_smaller_threshold','write_once':True}

def verify_selection(record,*,test_fixture=False,trust=None):
    """Recompute the one frozen selection from fully validated pair evidence.

    Production callers supply an externally frozen record SHA and per-pair
    trust separately from the record. A dict is accepted only for explicit
    engineering schema tests; it can never authorize a production selection.
    """
    if isinstance(record,(str,Path)):
        if not test_fixture:
            if not trust or trust.get('sha256')!=sha(record):raise ValueError('external immutable selection required')
        record=load(record)
    elif not test_fixture:raise ValueError('production selection requires externally frozen file')
    if not isinstance(record,dict) or record.get('test_fixture') is not test_fixture:raise ValueError('selection fixture/production boundary')
    if record.get('schema') not in ('S1.dev_selection.v1','S1.entry.asset.v1'):raise ValueError('selection schema')
    if record.get('schema')=='S1.entry.asset.v1' and record.get('asset')!='dev_selection':raise ValueError('selection asset identity')
    for key,value in {'inputs':30,'children':960,'objective':'equal_weight_mean_log_two_round_total_ratio',
                      'selection_rule':'exact_float_tie_then_smaller_threshold','write_once':True}.items():
        if record.get(key)!=value:raise ValueError('selection registered rule missing/mismatch')
    bindings=record.get('pair_manifest_sha',{})
    if len(bindings)!=240 or not record.get('identity_bindings') or set(record.get('scores',{}))!=set(CANDIDATES):raise ValueError('complete selection bindings required')
    actual=select(bindings,test_fixture=test_fixture,trust=None if test_fixture else (trust or {}).get('pair_trust'))
    for key in ('inputs','children','objective','scores','family_input_counts','selected_theta','selected_h',
                'pair_manifest_sha','input_cache_sha','identity_bindings','native_binary_sha256','protocol_sha256',
                'source_bundle_sha','method_config_sha256','selection_rule','write_once'):
        if record.get(key)!=actual[key]:raise ValueError('saved selection score/threshold/binding mismatch: '+key)
    return actual

def write_selection(path,result):
    path=Path(path)
    if result.get('test_fixture') and not path.name.endswith('_fixture.json'):raise ValueError('fixture output must use *_fixture.json')
    if not result.get('test_fixture') and path.name!='dev_selection.json':raise ValueError('production selection name required')
    try:
        with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    except FileExistsError as e:raise ValueError('write-once selection exists') from e
