"""Read-only S2 analysis. Rebuild values from accepted original child exports.

The large archive/cache/binary hash audit is a separate integrity artifact; this
CLI binds COMPLETE and verifies every consumed original small file against it.
It never launches a benchmark, changes the registered family, or drops rows.
"""
from pathlib import Path
import argparse
import csv
import importlib.util
import math
import sys
from collections import Counter, defaultdict

import s2_launch as launch
import s2_matrix as matrix

S2=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('_s2_s1_math',S2.parent/'S1/tools/analysis.py')
_math=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_math)
positive=_math.positive
two_round_ratio=_math.two_round_ratio
linear_quantile=_math.linear_quantile
student_t_quantile=_math.student_t_quantile
COMPONENTS=('build','online','total')
FAMILY=54
CRITICAL=student_t_quantile(1-.05/(2*FAMILY),9)


def classify(logs,lower,upper,floor):
    if len(logs)!=10 or not all(math.isfinite(x) for x in [*logs,lower,upper,floor]) or floor<0 or lower>upper:
        raise ValueError('invalid classification inputs')
    d=max(floor,math.log(1.05))
    if all(x < -d for x in logs) and upper < -d:return 'strong_fast'
    if all(x > d for x in logs) and lower > d:return 'strong_slow'
    return 'unresolved'


def summarize(ratios,component,floor):
    if component not in COMPONENTS or len(ratios)!=10:raise ValueError('ten ratios and registered component required')
    ratios=[positive(v) for v in ratios];logs=[math.log(v) for v in ratios]
    mean=math.fsum(logs)/10;sd=math.sqrt(math.fsum((v-mean)**2 for v in logs)/9)
    primary=component in ('online','total')
    critical=CRITICAL if primary else student_t_quantile(.975,9)
    half=critical*sd/math.sqrt(10);lo,hi=mean-half,mean+half
    q25,q75=linear_quantile(ratios,.25),linear_quantile(ratios,.75)
    return dict(component=component,scope='primary' if primary else 'exploratory',n=10,
                median=linear_quantile(ratios,.5),q25=q25,q75=q75,iqr=q75-q25,wins=sum(v<1 for v in ratios),wins_denominator=10,
                mean_log=mean,sample_sd_log=sd,geometric_mean=math.exp(mean),family_size=FAMILY if primary else 1,
                alpha=.05/FAMILY if primary else .05,df=9,critical_t=critical,ci_estimand='geometric_mean',
                log_ci_lower=lo,log_ci_upper=hi,ratio_ci_lower=math.exp(lo),ratio_ci_upper=math.exp(hi),
                aa_log_floor=floor,decision_D=max(floor,math.log(1.05)),
                classification=classify(logs,lo,hi,floor) if primary else 'exploratory')


def summarize_seed_pairs(by_seed,component,floor):
    if set(by_seed)!=set(matrix.SEEDS):raise ValueError('exact ten registered seeds required')
    return summarize([by_seed[s] for s in matrix.SEEDS],component,floor)


def pair_rows(rows):
    rows=list(rows)
    if len(rows)!=4 or [(r['round'],r['role']) for r in rows]!=matrix.pair_order():
        raise ValueError('complete ordered AB A/B, BA B/A block required')
    first=rows[0]
    shared=(*launch.IDENTITY_KEYS,'pair_id','batch_id','profile','mode')
    if any(r['mode']!='native' or any(str(r[k])!=str(first[k]) for k in shared) for r in rows):
        raise ValueError('paired input/mode identity mismatch')
    if rows[0]['method']!=rows[3]['method'] or rows[1]['method']!=rows[2]['method']:
        raise ValueError('pair method roles changed between rounds')
    result={}
    for component in COMPONENTS:
        k=component+'_ns'
        result[component]=two_round_ratio([(rows[0][k],rows[1][k]),(rows[3][k],rows[2][k])])
    return result


def validate_matrix(rows):
    planned={c['child_id']:(u['kind'],c) for u in launch.formal_plan()['units'] for c in u['children']}
    found={}
    for row in rows:
        key=row['child_id']
        if key not in planned or key in found:raise ValueError('unknown/duplicate child identity')
        kind,child=planned[key]
        launch.equal_identity(dict(child,kind=kind),row)
        found[key]=row
    if set(found)!=set(planned):raise ValueError('incomplete registered matrix')
    return found


def analyze_native(rows):
    found=validate_matrix(rows);paired=[];blocks=[]
    for unit in launch.formal_plan()['units']:
        if unit['kind']=='resource':continue
        group=[found[c['child_id']] for c in unit['children']]
        ratios=pair_rows(group);first=group[0]
        identity={k:first[k] for k in ('case_id','seed','horizon','U','pair_id')}
        identity.update(reference=group[0]['method'],candidate=group[1]['method'])
        if unit['kind']=='formal_native':
            for component,value in ratios.items():paired.append(dict(identity,component=component,ratio=value,log_ratio=math.log(value)))
        else:
            blocks.append(dict(identity,position=unit['kind'].removeprefix('aa_'),**{c+'_ratio':v for c,v in ratios.items()},**{c+'_log_ratio':math.log(v) for c,v in ratios.items()}))
    if len(blocks)!=90 or Counter(r['position'] for r in blocks)!=dict(before=45,after=45):raise ValueError('all 90 AA blocks required')
    floor={'blocks':90,'before_blocks':45,'after_blocks':45,'interpretation':'finite_observed_envelope_not_confidence_bound','components':{}}
    for c in COMPONENTS:
        e=max(abs(r[c+'_log_ratio']) for r in blocks)
        floor['components'][c]={'E':e,'D':max(e,math.log(1.05)),'minimum_effect_log':math.log(1.05)}
    groups=defaultdict(dict)
    for r in paired:
        key=tuple(r[k] for k in ('case_id','horizon','reference','component'))
        seed=int(r['seed'])
        if seed in groups[key]:raise ValueError('duplicate seed in summary')
        groups[key][seed]=r['ratio']
    summary=[]
    for (case,horizon,reference,c),seeds in sorted(groups.items()):
        summary.append(dict(case_id=case,horizon=horizon,reference=reference,candidate='R6',**summarize_seed_pairs(seeds,c,floor['components'][c]['E'])))
    if len(paired)!=810 or len(summary)!=81 or sum(s['scope']=='primary' for s in summary)!=54:raise ValueError('registered analysis dimensions changed')
    return dict(paired=paired,summary=summary,aa_blocks=blocks,floor=floor)


def resource_values(raw,last):
    values={k:int(last[k]) for k in ('whole_current','whole_peak','whole_live')}
    for a in launch.ACCOUNTS:
        for suffix in ('current','peak'):
            k=a+'_'+suffix;values[k]='NA' if raw[k]=='NA' else int(raw[k])
    values['persistent_current']='NA' if raw['method']=='TLX' else sum(values[a+'_current'] for a in launch.ACCOUNTS)
    return values


def resource_summary(rows):
    groups=defaultdict(list)
    metrics=('whole_current','whole_peak','whole_live','persistent_current',*[a+'_'+s for a in launch.ACCOUNTS for s in ('current','peak')],*launch.COUNTERS,'owner_current_after_destroy','owner_live_after_destroy')
    for row in rows:groups[row['case_id'],row['method']].append(row)
    if set(groups)!={(c,m) for c in matrix.LOADS for m in matrix.METHODS}:raise ValueError('resource cell matrix incomplete')
    out=[]
    for (case,method),group in sorted(groups.items()):
        if len(group)!=10 or {int(r['seed']) for r in group}!=set(matrix.SEEDS):raise ValueError('resource seed set incomplete')
        row=dict(case_id=case,method=method,horizon=4,n=10,scope='exploratory',mode='resource')
        for metric in metrics:
            values=[r[metric] for r in group]
            if any(v=='NA' for v in values):
                if not all(v=='NA' for v in values):raise ValueError('partially unavailable metric')
                for stat in ('median','q25','q75','min','max'):row[metric+'_'+stat]='NA'
            else:
                values=[int(v) for v in values]
                for stat,q in (('median',.5),('q25',.25),('q75',.75)):row[metric+'_'+stat]=linear_quantile(values,q)
                row[metric+'_min']=min(values);row[metric+'_max']=max(values)
        out.append(row)
    return out


RESOURCE_PAIR_METRICS=('whole_current','whole_peak','persistent_current',*launch.COUNTERS)


def pair_resources(rows):
    expected={(c,s,m) for c in matrix.LOADS for s in matrix.SEEDS for m in matrix.METHODS}
    found={}
    for row in rows:
        key=(row['case_id'],int(row['seed']),row['method'])
        if key in found or key not in expected or row['mode']!='resource':raise ValueError('invalid resource pair identity')
        found[key]=row
    if set(found)!=expected:raise ValueError('resource pairs require full seed/method matrix')
    out=[]
    for case in matrix.LOADS:
        for seed in matrix.SEEDS:
            candidate=found[case,seed,'R6']
            for method in matrix.REFERENCES:
                reference=found[case,seed,method]
                record=dict(case_id=case,seed=seed,horizon=4,candidate='R6',reference=method,mode='resource',scope='exploratory')
                for metric in RESOURCE_PAIR_METRICS:
                    a,b=reference[metric],candidate[metric]
                    record[metric+'_reference']=a;record[metric+'_candidate']=b
                    record[metric+'_ratio']='NA' if a=='NA' or b=='NA' or int(a)==0 else int(b)/int(a)
                out.append(record)
    return out


def claim_output(path):
    path=Path(path).resolve();path.mkdir(parents=True,exist_ok=False);return path


def write_csv(path,rows):
    if not rows:raise ValueError('empty output table')
    fields=list(rows[0])
    if any(set(r)!=set(fields) for r in rows):raise ValueError('heterogeneous output columns')
    with Path(path).open('x',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def read_archive(complete_path):
    complete_path=Path(complete_path).resolve(strict=True);root=complete_path.parent
    complete=launch.load_json(complete_path);plan=launch.formal_plan()
    if complete.get('schema')!='S2.launch.complete.v1' or complete.get('status')!='COMPLETE' or complete.get('engineering_only') is not False or complete.get('accepted_children')!=1560 or complete.get('counts')!=plan['counts']:
        raise ValueError('complete registered formal launch required')
    inventory={str(Path(b['path']).resolve()):b['sha256'] for b in complete['files']}
    if len(inventory)!=len(complete['files']):raise ValueError('duplicate COMPLETE file binding')
    consumed={str(complete_path):launch.sha(complete_path)}
    def consume(path):
        path=Path(path).resolve(strict=True);key=str(path)
        if key not in consumed:
            digest=launch.sha(path)
            if inventory.get(key)!=digest:raise ValueError('consumed original file missing/changed in COMPLETE: '+key)
            consumed[key]=digest
        return path
    def read(path):return launch.load_json(consume(path))
    if read(root/'plan.json')!=plan:raise ValueError('original plan differs from registered formal matrix')
    command_plan=read(root/'command_plan.json');lock=read(root/'lock.json')
    if lock['protocol_sha']!=launch.PROTOCOL_SHA or lock['source_bundle_sha']!=launch.SOURCE_BUNDLE_SHA:raise ValueError('frozen protocol/source bundle mismatch')
    if launch.sha(S2/'s2_protocol.json')!=launch.PROTOCOL_SHA:raise ValueError('analysis protocol file changed')
    expected_dirs=[str(i).zfill(6)+'_'+u['unit_id'] for i,u in enumerate(plan['units'])]
    if sorted(p.name for p in (root/'units').iterdir())!=expected_dirs:raise ValueError('unit archive contains incomplete/extra directories')
    rows=[];phases={'native':[],'resource':[]};snapshots=[];resources=[];prepare_seen={}
    for index,unit in enumerate(plan['units']):
        unitdir=root/'units'/expected_dirs[index];seal=read(unitdir/'seal.json')
        launch.equal_identity({'schema':'S2.unit.seal.v1','unit_id':unit['unit_id'],'kind':unit['kind']},seal)
        if [c['child_id'] for c in seal['children']]!=[c['child_id'] for c in unit['children']]:raise ValueError('unit sealed child identities differ')
        for child,embedded in zip(unit['children'],seal['children']):
            key=child['profile']+'_'+child['case_id']+'_'+str(child['seed'])
            if key not in prepare_seen:
                prep=read(root/'prepare'/key/'seal.json')
                prep_command,cacheout,ledger=launch.prepare_command(root,plan,child,lock)
                for name in ('process.json','START.json','stdout.txt','stderr.txt'):consume(ledger/name)
                launch.revalidate_process(ledger,prep_command)
                prepare_seen[key]=prep
            cache=root/'caches'/key/('h'+str(child['horizon']))/'cache.bin'
            metadata=read(cache.with_name('cache.meta.json'))
            identity={k:metadata[k] for k in launch.IDENTITY_KEYS}
            if identity!=prepare_seen[key]['identities'][str(child['horizon'])]:raise ValueError('prepare/cache metadata identity mismatch')
            launch.equal_identity({k:child[k] for k in ('case_id','profile','seed','U','horizon')},identity)
            expected=dict(identity,**{k:child[k] for k in ('pair_id','round','role','mode','method')},batch_id=root.name,binary_sha=lock['binaries'][child['mode']]['sha256'])
            output=unitdir/'outputs'/child['child_id'];ledger=unitdir/'processes'/child['child_id']
            command=launch.command_run(lock['pin']['path'],lock['binaries'][child['mode']]['path'],cache,identity['cache_sha'],child,root.name,output)
            for name in ('process.json','START.json','stdout.txt','stderr.txt'):consume(ledger/name)
            launch.revalidate_process(ledger,command)
            accepted=read(ledger/'accepted.json')
            for path in output.iterdir():
                if not path.is_file():raise ValueError('unexpected child output directory')
                consume(path)
            raw=launch.accept_files(output,expected)  # Exactly once per child.
            if accepted!=embedded or accepted['expected']!=expected or accepted['row']!=raw:raise ValueError('original accepted/seal/raw mismatch')
            actual=[launch.bind(p) for p in output.iterdir()]+[launch.bind(p) for p in ledger.iterdir() if p.name!='accepted.json']
            if {b['path']:b['sha256'] for b in accepted['files']}!={b['path']:b['sha256'] for b in actual}:raise ValueError('accepted file inventory mismatch')
            bindings={b['path']:b['sha256'] for b in seal['files']}
            for b in [*actual,launch.bind(ledger/'accepted.json')]:
                if bindings.get(b['path'])!=b['sha256']:raise ValueError('unit seal omits consumed original child file')
            row=dict(child_id=child['child_id'],kind=unit['kind'],**raw)
            rows.append(row)
            provenance={k:row[k] for k in ('child_id','kind','case_id','seed','horizon','pair_id','round','role','method','mode')}
            provenance.update(raw_path=str(output/'raw.csv'),raw_sha256=consumed[str((output/'raw.csv').resolve())])
            for phase in launch._rows(output/'phases.csv'):phases[child['mode']].append(dict(provenance,**phase))
            if child['mode']=='resource':
                ss=launch._rows(output/'snapshots.csv')
                snapshots.extend(dict(provenance,**s) for s in ss)
                resources.append(dict(row,**resource_values(raw,ss[-1])))
        if (index+1)%90==0:print('accepted original units',index+1,'/',len(plan['units']),flush=True)
    if len(prepare_seen)!=33:raise ValueError('33 distinct prepare inputs required')
    # The frozen command plan is itself hashed above. Actual reconstructed commands
    # are checked against their START/process receipts, including short paths.
    if command_plan['counts']!=plan['counts'] or len(command_plan['run'])!=1560:raise ValueError('original command matrix incomplete')
    return dict(rows=rows,phases=phases,snapshots=snapshots,resources=resources,consumed=consumed,complete=complete)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complete',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    output=claim_output(args.output)
    launch.dump(output/'START.json',dict(schema='S2.report.start.v1',input_complete=launch.bind(args.complete),command=[sys.executable,*sys.argv]))
    try:
        archive=read_archive(args.complete);analysis=analyze_native(archive['rows'])
        native=[r for r in archive['rows'] if r['kind']=='formal_native'];aa=[r for r in archive['rows'] if r['kind'].startswith('aa_')]
        tables={'native_raw.csv':native,'paired_ratios.csv':analysis['paired'],'native_summary.csv':analysis['summary'],'aa_raw.csv':aa,'aa_blocks.csv':analysis['aa_blocks'],
                'resource_raw.csv':archive['resources'],'resource_paired.csv':pair_resources(archive['resources']),'resource_summary.csv':resource_summary(archive['resources']),'resource_snapshots.csv':archive['snapshots'],
                'native_phases.csv':[r for r in archive['phases']['native'] if r['kind']=='formal_native'],
                'aa_phases.csv':[r for r in archive['phases']['native'] if r['kind'].startswith('aa_')],'resource_phases.csv':archive['phases']['resource']}
        for name,rows in tables.items():write_csv(output/name,rows)
        launch.dump(output/'aa_floor.json',analysis['floor'])
        launch.dump(output/'input_bindings.json',{'input_complete':launch.bind(args.complete),'files':[dict(path=p,sha256=s) for p,s in sorted(archive['consumed'].items())],
                    'scope':'consumed original unit seals, prepare/process/command receipts, cache metadata and raw exports; independent full archive audit required for large caches/binaries/source dependencies'})
        summary=analysis['summary'];counts={name:len(rows) for name,rows in tables.items()}
        classifications=dict(Counter(s['classification'] for s in summary if s['scope']=='primary'))
        manifest=dict(schema='S2.report.complete.v1',status='COMPLETE',input_complete=launch.bind(args.complete),
                      tool=launch.bind(Path(__file__)),math_dependency=launch.bind(S2.parent/'S1/tools/analysis.py'),protocol=launch.bind(S2/'s2_protocol.json'),
                      counts=counts,primary_comparisons=54,critical_t=CRITICAL,classification_counts=classifications,
                      requested_byte_accounting=True,account_peaks_additive=False,resource_native_joint_trajectory=False,CPU_or_latency_measured=False,
                      all_original_rows_preserved=True,files=[launch.bind(p) for p in sorted(output.iterdir()) if p.is_file()])
        launch.dump(output/'COMPLETE.json',manifest)
        print('COMPLETE',counts,classifications,flush=True)
        return 0
    except Exception as exc:
        launch.dump(output/'FAILURE.json',dict(status='FAILURE',error=repr(exc)))
        raise


if __name__=='__main__':sys.exit(main())
