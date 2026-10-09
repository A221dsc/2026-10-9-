"""Frozen S0 statistical rules. Standard library only; no benchmark execution."""
import math

COMPONENTS = ('build', 'online', 'total')

def positive(x):
    x = float(x)
    if not math.isfinite(x) or x <= 0:
        raise ValueError('finite positive observation required')
    return x

def two_round_ratio(values):
    values = list(values)
    if len(values) != 2:
        raise ValueError('exactly two rounds required')
    return math.exp(math.fsum(math.log(positive(c)) - math.log(positive(r)) for r,c in values)/2)

def _beta_fraction(a,b,x):
    # Modified Lentz continued fraction for incomplete beta; independently
    # checked by density integration in tests, including the Bonferroni tail.
    tiny=1e-300; c=1.; d=1-(a+b)*x/(a+1); d=1/max(abs(d),tiny)*(1 if d>=0 else -1); h=d
    for m in range(1,1001):
        m2=2*m
        for aa in [m*(b-m)*x/((a+m2-1)*(a+m2)),
                   -(a+m)*(a+b+m)*x/((a+m2)*(a+m2+1))]:
            d=1+aa*d; d=d if abs(d)>tiny else tiny
            c=1+aa/c; c=c if abs(c)>tiny else tiny
            d=1/d; delta=d*c; h*=delta
        if abs(delta-1)<2e-15:return h
    raise ValueError('incomplete beta failed to converge')

def _ibeta(a,b,x):
    if x<=0:return 0.
    if x>=1:return 1.
    bt=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    if x<(a+1)/(a+b+2):return bt*_beta_fraction(a,b,x)/a
    return 1-bt*_beta_fraction(b,a,1-x)/b

def student_t_cdf(x,df=9):
    if not isinstance(df,int) or df<=0 or not math.isfinite(x):raise ValueError('invalid t argument')
    if x==0:return .5
    tail=.5*_ibeta(df/2,.5,df/(df+x*x))
    return tail if x<0 else 1-tail

def student_t_quantile(p,df=9):
    if not 0<p<1 or not isinstance(df,int) or df<=0:raise ValueError('invalid t probability or df')
    if p==.5:return 0.
    if p<.5:return -student_t_quantile(1-p,df)
    lo,hi=0.,1.
    while student_t_cdf(hi,df)<p:
        hi*=2
        if not math.isfinite(hi):raise ValueError('unrepresentable t quantile')
    for _ in range(100):
        mid=(lo+hi)/2
        if student_t_cdf(mid,df)<p:lo=mid
        else:hi=mid
    return (lo+hi)/2

def confirmatory_family():
    return [(p,f'F{i:02}',c) for p in ('P03','P06','P07') for i in range(1,8) for c in ('online','total')]

def linear_quantile(values,q):
    values=sorted(values)
    if not values or not 0<=q<=1:raise ValueError('quantile arguments')
    n=(len(values)-1)*q; i=int(n); j=min(i+1,len(values)-1)
    return values[i]+(n-i)*(values[j]-values[i])

def classify(logs,lower,upper,floor):
    if len(logs)!=10 or not all(math.isfinite(x) for x in [*logs,lower,upper,floor]) or floor<0 or lower>upper:
        raise ValueError('invalid classification inputs')
    fast=-max(floor,-math.log(.95)); slow=max(floor,math.log(1.05))
    if all(x<fast for x in logs) and upper<fast:return 'strong_fast'
    if all(x>slow for x in logs) and lower>slow:return 'strong_slow'
    return 'unresolved'

def summarize(ratios,pair,case,component,aa_log_floor):
    ratios=list(ratios)
    if len(ratios)!=10 or component not in COMPONENTS:raise ValueError('ten paired inputs and registered component required')
    ratios=[positive(x) for x in ratios]; logs=[math.log(x) for x in ratios]
    mean=math.fsum(logs)/10; sd=math.sqrt(math.fsum((x-mean)**2 for x in logs)/9)
    family=42 if (pair,case,component) in confirmatory_family() else 1
    critical=student_t_quantile(1-.05/(2*family),9); half=critical*sd/math.sqrt(10)
    lower,upper=mean-half,mean+half
    q25,q75=linear_quantile(ratios,.25),linear_quantile(ratios,.75)
    return {'pair':pair,'case_id':case,'component':component,'n':10,'median':linear_quantile(ratios,.5),
            'q25':q25,'q75':q75,'iqr':q75-q25,'wins':sum(x<1 for x in ratios),
            'mean_log':mean,'sample_sd_log':sd,'geometric_mean':math.exp(mean),
            'family_size':family,'alpha':.05/family,'critical_t':critical,'ci_estimand':'geometric_mean',
            'log_ci_lower':lower,'log_ci_upper':upper,'ratio_ci_lower':math.exp(lower),'ratio_ci_upper':math.exp(upper),
            'aa_log_floor':aa_log_floor,'classification':classify(logs,lower,upper,aa_log_floor)}

def aa_floor(rows,scope):
    if scope=='dev':methods,cases=('M_LIST','M_EVENT_16'),('D02','D06')
    elif scope=='final':methods,cases=('Original','M_LIST','R6'),('F01','F03','F06')
    else:raise ValueError('AA scope must be dev or final')
    expected={(t,m,c,92001,b,r,role) for t in ('before','after') for m in methods for c in cases
              for b in range(1,6) for r in (1,2) for role in ('A','B')}
    found={}
    for row in rows:
        key=tuple(row[x] for x in ('timepoint','method','case_id','seed','block','round','role'))
        if key not in expected or key in found or row['status']!='valid':raise ValueError('AA missing/duplicate/invalid identity')
        for c in COMPONENTS:positive(row[c])
        found[key]=row
    if set(found)!=expected:raise ValueError('AA profile/block incomplete')
    out={c:0. for c in COMPONENTS}
    for t,m,c,seed,b in {(k[:5]) for k in expected}:
        for component in COMPONENTS:
            pairs=[(found[t,m,c,seed,b,r,'A'][component],found[t,m,c,seed,b,r,'B'][component]) for r in (1,2)]
            out[component]=max(out[component],abs(math.log(two_round_ratio(pairs))))
    out['interpretation']='finite_observed_envelope_not_confidence_bound'
    return out

def summarize_pairs(paths,pair,case,component,aa_log_floor=None,*,test_fixture=False,trust=None,selection=None,selection_trust=None,aa_inventory=None,aa_trust=None):
    """Aggregate exactly ten independently identified, validated final inputs."""
    from pathlib import Path
    from entry_gate import validate_pair, verify_complete_aa, _same_selection_binding, sha
    if not test_fixture and aa_inventory is None:raise ValueError('production final summary requires complete AA inventory')
    aa=None
    if aa_inventory is not None:
        aa=verify_complete_aa(aa_inventory,test_fixture=test_fixture,trust=aa_trust)
        if component not in COMPONENTS:raise ValueError('registered component required')
        floor=aa['observed_floor'][component]
        if aa_log_floor is not None and aa_log_floor!=floor:raise ValueError('AA floor mismatch')
        aa_log_floor=floor
    paths=list(paths)
    if len(paths)!=10 or len({str(Path(p).resolve()) for p in paths})!=10:raise ValueError('ten distinct pair locks required')
    methods={'P01':('Original','M_LIST'),'P02':('M_LIST','M_OBSERVE_LIST'),'P03':('M_LIST','R6'),
             'P04':('M_OBSERVE_LIST','R6'),'P05':('Original','R6'),'P08':('M_NO_IDLE','R6'),
             'DIA01':('M_EVENT_16','R6'),'DIA02':('M_FIXED_128','R6')}
    if pair in ('P06','P07'):
        from select_dev import verify_selection
        if aa is not None and aa.get('matrix') is not None:
            if not isinstance(selection,(str,Path)):raise ValueError('same frozen dev selection file required')
            _same_selection_binding(aa['matrix']['selection_binding'],{'path':str(selection),'sha256':sha(selection)})
        selected=verify_selection(selection,test_fixture=test_fixture,trust=selection_trust)
        threshold=selected['selected_theta' if pair=='P06' else 'selected_h']
        methods[pair]=(f'M_EVENT_{threshold}' if pair=='P06' else f'M_FIXED_{threshold}','R6')
    if pair not in methods or case not in {f'F{i:02}' for i in range(1,8)}:raise ValueError('unregistered final cell')
    by_seed={};locks={}
    for path in paths:
        out=validate_pair(path,test_fixture=test_fixture,trust=None if test_fixture else (trust or {}).get(str(Path(path).resolve())))
        if out['case_id']!=case or out['profile']!='final' or out['mode']!='native' or (out['reference'],out['candidate'])!=methods[pair] or out['seed'] in by_seed:
            raise ValueError('final input/pair identity duplicate or mismatch')
        if aa is not None and any(row['batch_id']!=aa['batch_id'] for row in out['rows']):raise ValueError('final pair/AA batch mismatch')
        if aa is not None and aa.get('matrix') is not None:
            matrix=aa['matrix'];p=str(Path(path).resolve());key=f'{case}:{out["seed"]}:{pair}'
            if matrix['matrix_cells'].get(key)!=p or matrix['pair_manifest_sha'].get(p)!=out['manifest_sha256']:
                raise ValueError('final cell absent from frozen complete formal matrix')
        by_seed[out['seed']]=out['ratios'][component];locks[str(Path(path).resolve())]=out['manifest_sha256']
    if set(by_seed)!=set(range(91001,91011)):raise ValueError('all ten registered final seeds required')
    return {**summarize([by_seed[s] for s in sorted(by_seed)],pair,case,component,aa_log_floor),
            'pair_manifest_sha':locks,'test_fixture':test_fixture,
            'aa_inventory_sha256':aa['manifest_sha256'] if aa else None}
