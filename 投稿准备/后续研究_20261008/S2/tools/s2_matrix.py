"""S2 registered execution matrix and independent raw-record acceptance.

Pure functions only: this module never executes a benchmark or tunes a policy.
"""
import math

METHODS = ('M_LIST', 'M_EVENT_16', 'R6', 'TLX')
LOADS = ('L01', 'L02', 'L03')
HORIZONS = (262144, 524288, 1048576)
SEEDS = tuple(range(100001, 100011))
REFERENCES = ('M_LIST', 'M_EVENT_16', 'TLX')

def native_cells():
    return [dict(case_id=load,seed=seed,U=units,reference=reference,candidate='R6',mode='native')
            for load in LOADS for seed in SEEDS for units in HORIZONS for reference in REFERENCES]

def pair_order():
    return [('AB','A'),('AB','B'),('BA','B'),('BA','A')]

def aa_cells(position):
    if position not in ('before','after'):
        raise ValueError('registered AA position required')
    return [dict(case_id=load,seed=101001,U=HORIZONS[-1],reference=method,candidate=method,position=position,block=block,mode='native')
            for method in ('M_LIST','R6','TLX') for load in LOADS for block in range(1,6)]

def resource_cells():
    return [dict(case_id=load,seed=seed,U=HORIZONS[-1],method=method,mode='resource')
            for load in LOADS for seed in SEEDS for method in METHODS]

def pair_ratio(pairs):
    pairs=list(pairs)
    if len(pairs)!=2:
        raise ValueError('exactly two complete AB/BA rounds required')
    logs=[]
    for reference,candidate in pairs:
        reference=float(reference);candidate=float(candidate)
        if not all(math.isfinite(x) and x>0 for x in (reference,candidate)):
            raise ValueError('positive finite actual time required')
        logs.append(math.log(candidate)-math.log(reference))
    return math.exp(math.fsum(logs)/2)

def _uint(row,key):
    value=str(row[key])
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError('canonical unsigned integer required: '+key)
    return int(value)

def validate_raw(expected,row):
    for key,value in expected.items():
        if key not in row or str(row[key])!=str(value):
            raise ValueError('actual identity mismatch: '+key)
    if row.get('method') not in METHODS or row.get('mode') not in ('native','resource'):
        raise ValueError('unregistered method/mode')
    if str(row.get('verified')).lower() not in ('true','1'):
        raise ValueError('complete content verification missing')
    build=_uint(row,'build_ns');online=_uint(row,'online_ns')
    if build<=0 or online<=0 or _uint(row,'total_ns')!=build+online:
        raise ValueError('invalid actual timing boundary')
    _uint(row,'destroy_ns')
    if row['mode']=='resource':
        if _uint(row,'owner_current_after_destroy') or _uint(row,'owner_live_after_destroy'):
            raise ValueError('owned allocations not released')
    elif row.get('owner_current_after_destroy')!='NA' or row.get('owner_live_after_destroy')!='NA':
        raise ValueError('native must not carry resource measurements')
    if row['method']!='TLX':
        scheduled=_uint(row,'scheduled_demotions');cleanup=_uint(row,'cleanup_demotions')
        if _uint(row,'total_demotions')!=scheduled+cleanup:
            raise ValueError('demotion accounting mismatch')
        peak=_uint(row,'peak_tree_buckets');final=_uint(row,'final_tree_buckets')
        if final>peak or peak>32:
            raise ValueError('TREE budget or peak invariant violation')
        promotions=_uint(row,'promotions')
        if final!=promotions-scheduled-cleanup or peak>promotions:
            raise ValueError('TREE lifecycle does not match completed conversions')
        if row['method']=='M_LIST' and (promotions or scheduled or cleanup or peak or final):
            raise ValueError('LIST control cannot change representation')
        if 'candidate_max' in row and _uint(row,'candidate_max')>4096:
            raise ValueError('candidate population exceeds directory')
    return True

def sealed_prefix(planned_ids,completed_ids):
    plans=list(planned_ids);completed=list(completed_ids)
    if len(set(plans))!=len(plans) or len(set(completed))!=len(completed):
        raise ValueError('duplicate execution identities')
    if len(completed)>len(plans) or completed!=plans[:len(completed)]:
        raise ValueError('only exact sealed continuous prefix may be reused')
    return len(completed)

def require_native_rank(rows):
    rows=list(rows)
    if not rows or any(row.get('mode')!='native' for row in rows):
        raise ValueError('resource/latency must not enter native time ranking')
    return True


def validate_execution(expected_command,receipt):
    if receipt.get('actual_exit_observed') is not True or type(receipt.get('exit_code')) is not int or receipt.get('exit_code') != 0:
        raise ValueError('actual successful exit must be observed')
    if list(receipt.get('command',[])) != [str(x) for x in expected_command]:
        raise ValueError('actual command identity mismatch')
    return True

