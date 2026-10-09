"""Static adapter for frozen legacy rotation. This module never starts children."""
from pathlib import Path
import ast
import hashlib

S1=Path(__file__).resolve().parents[1]
LEGACY=S1.parents[1]/'公开数据实验'/'bench_pinned_pair.py'
LEGACY_SHA='bd38435b1e5b51d71bafbe0b92a6280f8b9b6af27e4dbb87832b5fa51ca9dea7'
REGISTERED={'Original','M_LIST','M_OBSERVE_LIST','R6','M_NO_IDLE',*[f'M_EVENT_{x}' for x in (8,16,32,64)],*[f'M_FIXED_{x}' for x in (128,512,2048,8192)]}
DEV_CANDIDATES=[*[f'M_EVENT_{x}' for x in (8,16,32,64)],*[f'M_FIXED_{x}' for x in (128,512,2048,8192)]]
FORMAL_LABELS=['DIA01','DIA02',*[f'P{i:02}' for i in range(1,9)]]

def registered_pair_id(case_id,seed,cell_id):
    """Map an unchanged registered comparison to its lock/raw/CLI identity.

    The composite string is not a new statistical label or a directory name.
    """
    dev=case_id in {f'D{i:02}' for i in range(1,11)}
    formal=case_id in {f'F{i:02}' for i in range(1,8)}
    if not ((dev and seed in (90001,90002,90003) and cell_id in DEV_CANDIDATES)
            or (formal and seed in range(91001,91011) and cell_id in FORMAL_LABELS)):
        raise ValueError('registered execution cell required')
    return f'{case_id}:{seed}:{cell_id}'

def registered_order(cell,scope):
    case_id,seed,label=cell
    registered_pair_id(case_id,seed,label)
    if scope=='dev':return case_id,seed,DEV_CANDIDATES.index(label)
    if scope=='final':return case_id,seed,label
    raise ValueError('registered batch scope required')

def verify_legacy():
    sha=hashlib.sha256(LEGACY.read_bytes()).hexdigest()
    if sha!=LEGACY_SHA:raise ValueError('legacy runner changed')
    source=LEGACY.read_text(encoding='utf-8');tree=ast.parse(source)
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_once')
    cli={n.value for n in ast.walk(run) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('--')}
    if not {'--data','--month','--days','--initial','--units','--methods','--workloads','--out'}<=cli:raise ValueError('unexpected legacy CLI')
    if '[(round_index + i) % len(arms)' not in source and '(round_index + i) % len(arms)' not in source:
        raise ValueError('legacy rotation unavailable')
    return {'sha256':sha,'run_once_compatible_with_cache_cli':False,'legacy_cli':sorted(cli),
            'role_mapping':{'0':'A=REF','1':'B=CAND'},'rotation':'(round_index+i)%2'}

def schedule(rounds=2,aa=False,pair_id='pair'):
    if rounds!=(10 if aa else 2):raise ValueError('two pair rounds or ten AA rounds required')
    out=[]
    for old_round in range(rounds):
        block=old_round//2+1
        for position in range(2):
            arm=(old_round+position)%2
            out.append({'old_round_index':old_round,'old_arm':arm,'order_index':len(out),
                        'round':old_round%2+1,'role':'A' if arm==0 else 'B','block':block,
                        'block_pair_id':f'{pair_id}:block{block}' if aa else pair_id})
    return out

def child_command(pin,binary,cache,cache_sha,method,output,batch,attempt,pair_id,rnd,role):
    if method not in REGISTERED or rnd not in (1,2) or role not in ('A','B'):raise ValueError('unregistered child')
    for identity in (batch,attempt,pair_id):
        if not identity or any(x in identity for x in '\r\n'):raise ValueError('invalid identity')
    if len(cache_sha)!=64 or any(c not in '0123456789abcdef' for c in cache_sha):raise ValueError('invalid cache SHA')
    return [str(Path(pin).resolve()),'0x8',str(Path(binary).resolve()),'run','--cache',str(Path(cache).resolve()),
            '--cache-sha',cache_sha,'--method',method,'--output',str(Path(output).resolve()),
            '--batch-id',batch,'--attempt-id',attempt,'--pair-id',pair_id,'--round',str(rnd),'--role',role]

def command_plan(pin,binary,cache,cache_sha,reference,candidate,output,batch,attempt,pair_id,aa=False,*,cell=None):
    if cell is not None:
        expected=registered_pair_id(*cell)
        if aa or pair_id!=expected:raise ValueError('plan registered execution identity mismatch')
    out=[]
    for row in schedule(10 if aa else 2,aa,pair_id):
        d=Path(output)/row['block_pair_id'].replace(':','_')/f"r{row['round']}{row['role']}"
        if d.exists():raise ValueError('immutable child destination exists')
        method=reference if row['role']=='A' else candidate
        out.append({**row,'command':child_command(pin,binary,cache,cache_sha,method,d,batch,attempt,row['block_pair_id'],row['round'],row['role'])})
    return out
