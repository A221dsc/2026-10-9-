"""Rebuild the final same-layout report after production timing has completed.

Presentation only. Checks all aggregate rows against the archived pair data and
frozen mathematical summaries; neither runs benchmarks nor selects parameters.
"""
from pathlib import Path
import argparse
import csv
import json
import math
import os
import shutil
import sys
import analysis

S1=Path(__file__).resolve().parents[1]
LABELS=['DIA01','DIA02',*[f'P{i:02}' for i in range(1,9)]]
CASES={'F01':'顺序稀疏查询','F02':'顺序稀疏查询与内部撤销','F03':'顺序稠密查询',
       'F04':'稀疏→乱序→稀疏','F05':'单桶低定位工作量','F06':'单桶高定位工作量','F07':'单桶范围前缀定位'}
CN={'strong_fast':'可靠更快','strong_slow':'可靠更慢','unresolved':'无法可靠区分'}

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def rows(path):
    with Path(path).open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def require(ok,message):
    if not ok:raise ValueError(message)
def save(path,values):
    with Path(path).open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
def json_save(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

def verify(root):
    done=read(root/'completion.json');gate=read(root/'FINAL_COMPLETE_GATE.json')
    batch=read(root/'execution_manifest.json')['batch_id']
    require(done['status']=='FINAL_NATIVE_COMPLETE' and gate['FINAL_READY'] and
            done['actual_timing_children']==3160 and done['formal_pairs']==700,'complete production native evidence required')
    raw=rows(root/'raw_native_all.csv');paired=rows(root/'paired_all.csv');groups=rows(root/'group_summary.csv')
    require(len(raw)==3160 and len(paired)==790 and len(groups)==210,'complete raw/paired/group row counts')
    require(all(r['status']=='valid' and r['measurement_mode']=='native' and r['batch_id']==batch for r in raw),'production raw identity')
    keys=[(r['pair_id'],int(r['round']),r['role']) for r in raw]
    require(len(set(keys))==3160,'independent children')
    by_pair={}
    for r in raw:
        require(all((r[f'placement_{p}_mask'],r[f'placement_{p}_cpu'],r[f'placement_{p}_group'])==('8','3','0')
                    for p in ('start','end')),'actual fixed placement')
        require(int(r['total_ns'])==int(r['build_ns'])+int(r['online_ns']),'total accounting')
        by_pair.setdefault(r['pair_id'],{})[int(r['round']),r['role']]=r
    for p in paired:
        children=by_pair[p['pair_id']]
        require(set(children)=={(1,'A'),(1,'B'),(2,'A'),(2,'B')},'complete two-round block')
        require(all(r['case_id']==p['case_id'] and r['seed']==p['seed'] for r in children.values()),'paired input identity')
        require(all(children[r,'A']['method']==p['reference'] and children[r,'B']['method']==p['candidate'] for r in (1,2)), 'paired methods')
        for c in ('build','online','total'):
            value=analysis.two_round_ratio([(int(children[r,'A'][c+'_ns']),int(children[r,'B'][c+'_ns'])) for r in (1,2)])
            require(value==float(p[c]),'raw/paired arithmetic')
    require(done['AA_floor']==gate['formal_aa_log_floor'],'completion-gate noise identity')
    for g in groups:
        selected=[p for p in paired if p['profile']=='final' and p['case_id']==g['case_id'] and p['pair_id'].endswith(':'+g['pair'])]
        require(len(selected)==10 and {int(p['seed']) for p in selected}==set(range(91001,91011)),'ten independent final seeds')
        calc=analysis.summarize([float(p[g['component']]) for p in selected],g['pair'],g['case_id'],g['component'],done['AA_floor'][g['component']])
        for k,v in calc.items():
            if isinstance(v,(int,float)):require(float(g[k])==v,'group arithmetic: '+k)
            else:require(g[k]==v,'group identity: '+k)
    return done,raw,paired,groups

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);args=p.parse_args()
    root=Path(args.run).resolve();done,raw,paired,groups=verify(root)
    manifest=read(root/'execution_manifest.json');lookup={(g['pair'],g['case_id'],g['component']):g for g in groups}
    focus=[g for g in groups if g['pair'] in ('P03','P06','P07') and g['component'] in ('online','total')]
    conclusion=[]
    for pair,name in [('P03','同布局 LIST'),('P06','Event_16'),('P07','Fixed_2048')]:
        for c in ('online','total'):
            gs=[g for g in focus if g['pair']==pair and g['component']==c]
            counts={v:sum(g['classification']==v for g in gs) for v in CN}
            conclusion.append({'pair':pair,'reference':name,'component':c,**counts})
    save(root/'incremental_value_summary.csv',conclusion)
    # Deterministic counters are not independent observations across AB/BA or
    # repeated comparisons. Collapse identical case/seed/method values first.
    fields=('total_avoidable_work','promotions','scheduled_demotions','cleanup_demotions','total_demotions',
            'peak_tree_buckets','final_tree_buckets','cand_last','cand_max','nodes_allocated','conversion_failures')
    counters={}
    for r in raw:
        if r['pair_id'].startswith('aa:'):continue
        key=(r['case_id'],int(r['seed']),r['method']);values={k:r[k] for k in fields}
        if key in counters:require(counters[key]==values,'deterministic counter mismatch across repeated native children')
        else:counters[key]=values
    counter_rows=[{'case_id':c,'seed':s,'method':m,**v} for (c,s,m),v in sorted(counters.items())]
    save(root/'mechanism_counters_unique.csv',counter_rows)
    os.environ['MPLCONFIGDIR']=str(root/'plot_cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.fonttype']='none'
    fig,axes=plt.subplots(3,2,figsize=(13,12),layout='constrained')
    colors={'strong_fast':'#087f8c','strong_slow':'#b53c49','unresolved':'#758493'}
    for i,(pair,ref) in enumerate([('P03','M_LIST'),('P06','Event_16'),('P07','Fixed_2048')]):
        for j,c in enumerate(('online','total')):
            ax=axes[i,j];floor=done['AA_floor'][c]
            ax.axvspan(math.exp(-floor),math.exp(floor),color='#e8edf2',zorder=0)
            for y,case in enumerate(CASES):
                g=lookup[pair,case,c];v=float(g['geometric_mean']);lo=float(g['ratio_ci_lower']);hi=float(g['ratio_ci_upper'])
                ax.errorbar(v,y,xerr=[[v-lo],[hi-v]],fmt='o',color=colors[g['classification']],capsize=3)
            ax.axvline(1,color='#23395d',linestyle='--',linewidth=1)
            ax.set_xscale('log');ax.set_yticks(range(7),list(CASES));ax.invert_yaxis()
            ax.set_title(f'R6 / {ref}: {c}');ax.set_xlabel('Geometric mean paired ratio; lower is faster')
            ax.grid(axis='x',alpha=.18);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Independent FINAL inputs: 10 seeds per case\nIntervals: 42-comparison Bonferroni family; gray: observed A/A envelope',fontsize=13)
    fig.savefig(S1/'FINAL_增量价值.png',dpi=180);fig.savefig(S1/'FINAL_增量价值.svg');plt.close(fig)
    svg=S1/'FINAL_增量价值.svg';svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf8').splitlines())+'\n',encoding='utf8')
    lines=['# S1 独立正式输入：Adaptive R6 的同布局增量价值','',
           '正式原生计时矩阵已完成，700个配对格子与前后A/A均通过冻结生产完成闸门。以下结论区分可靠收益、可靠损失和无法可靠区分；没有按结果修改算法、成本表、门槛或负载。','',
           f'执行版本：Git `{manifest["git_commit"]}`；DEV冻结标签 `s1-dev-v1`；工程标签 `s1-engineering-v1`。事件门槛θ=16、固定门槛h=2048来自DEV一次性选择，正式输入采用独立种子91001–91010。','',
           '## 核心判断','',
           '|R6对照|指标|可靠更快/7|可靠更慢/7|无法可靠区分/7|',
           '|---|---|---:|---:|---:|']
    for r in conclusion:lines.append(f'|{r["reference"]}|{r["component"]}|{r["strong_fast"]}|{r["strong_slow"]}|{r["unresolved"]}|')
    lines+=['','判断标准是预注册的严格标准：每格10个log配对比值及log均值区间都要越过A/A包络与5%最小实际效应的较大门槛。仅中位数小于1或wins较多不足以宣称可靠加速。',
            '','工作量信号的增量价值由P06检验；固定大小门控由P07检验；P03检验转换控制器整体相对同布局LIST的效果。P06/P07与R6共用表示布局、节点池、预算、降级及冷却，差异限于预注册门控。','',
            f'![正式增量价值](<{S1/"FINAL_增量价值.png"}>)','']
    if manifest.get('resume_git_commit'):
        recovery=read(root/'recovery_receipt.json')
        lines+= [f'恢复执行版本：Git `{manifest["resume_git_commit"]}`。原进程缺少最终退出收据，中断原因未确定；按预注册恢复规则逐格全量验收并复用{recovery["reused_formal_pairs"]}个已封存正式格子及45个前置A/A块，没有根据性能选择复用或重跑。未完整封存的格子数为{len(recovery["incomplete_pairs_retained"])}，原记录均保留。恢复前另做新的实际安静环境验收，原起始及前置A/A绑定保持不可变。','']
    for pair,name in [('P03','R6 / 同布局 LIST'),('P06','R6 / Event_16'),('P07','R6 / Fixed_2048')]:
        lines += [f'## {name}','','|输入|指标|中位数|Q25–Q75|IQR|原始胜出/10|几何均值区间|裁决|',
                  '|---|---|---:|---:|---:|---:|---:|---|']
        for case,label in CASES.items():
            for c in ('online','total'):
                g=lookup[pair,case,c]
                lines.append(f'|{case} {label}|{c}|{float(g["median"]):.4f}|{float(g["q25"]):.4f}–{float(g["q75"]):.4f}|{float(g["iqr"]):.4f}|{g["wins"]}/10|{float(g["ratio_ci_lower"]):.4f}–{float(g["ratio_ci_upper"]):.4f}|{CN[g["classification"]]}|')
        lines+=['']
    lines += ['比值为R6/对照，小于1表示R6用时少；在线耗时包含插入、删除、范围查询、输出哈希及输出释放，并非单独的查询延迟。total=build+online，销毁耗时单列在原始CSV。IQR描述输入间离散程度，区间则估计配对比值的几何均值，不估计中位数。以上42个确认性比较采用Bonferroni校正；其余比较与build区间为探索性结果。','',
              '## 噪声、输入与完整性','','|分量|最大绝对log比值|有限观测比值包络|','|---|---:|---:|']
    for c in ('build','online','total'):
        v=done['AA_floor'][c];lines.append(f'|{c}|{v:.6f}|{math.exp(-v):.4f}–{math.exp(v):.4f}|')
    lines+=['','A/A采用Original、M_LIST、R6 × F01、F03、F06 × 种子92001，正式矩阵前后各5个两轮块，共90块、360个实际进程。包络是有限样本最大绝对log比值，不是置信界限；正式结论使用本批新包络，没有套用DEV地板。','',
            '- 70份正式输入，F01–F07 × 10个种子；每份输入10种独立配对，700格/2800个计时进程。DIA01即使与P06方法相同，也使用独立进程，未复用。',
            '- 固定逻辑P核3、mask0x8、group0；GetSystemTimes安静守卫；每格AB/BA两轮块几何平均。',
            '- F01–F04使用NYC Taxi 2024年1月真实时间键及合成操作；F05–F07为受控合成单桶8192记录，U=4096。公共时间键不等于真实业务查询轨迹。',
            '- 独立正式输入指未参与DEV门槛选择的新种子与轨迹；相同公开数据源中的窗口可能重叠，不能将70份输入称为70个独立数据来源。',
            '- F01–F04固定记录数窗口N=262144、U=262144；q=256、256、1及分阶段256/8/256。包含构建与一个窗口周转的维护，不是固定秒数TTL。',
            '- 保留全部3160个实际计时进程、失败尝试、原始时间、语义身份及配置；不剔除离群值、不因性能重跑、不扩种子、不重新调参。',
            '- 原生批次保留工作量、升降级、树桶、候选规模及节点计数。独立资源字节与逐API延迟矩阵尚未运行，不能用NA资源列或原生转换总时间推出内存和尾延迟结论。','',
            '## 其他归因比较与复现','',
            '完整210行汇总包含P01原始/同布局、P02观察开销、P04转换相对只观察、P05部署整体、P08普通空闲回收以及两个诊断门槛。重复计时中的确定性机制计数已按case/seed/method折叠，避免将重复进程当作独立样本。','',
            f'- [全部原始CSV](<{root/"raw_native_all.csv"}>)；[790个完整配对块](<{root/"paired_all.csv"}>)；[210行完整汇总](<{root/"group_summary.csv"}>)。',
            f'- [确定性机制计数](<{root/"mechanism_counters_unique.csv"}>)；[A/A原始记录](<{root/"aa_all.csv"}>)。',
            f'- [正式起始闸门](<{root/"FINAL_START_GATE.json"}>)；[正式完成闸门](<{root/"FINAL_COMPLETE_GATE.json"}>)；[执行环境与命令版本](<{root/"execution_manifest.json"}>)。',
            f'- 输入、所有侧车及实际命令保存在 `{root}`；不可覆盖归档。DEV选择沿用独立冻结文件，未重新写入。','',
            '计时复现：在相同Windows冻结依赖环境，使用登记的Python3.12运行 `tools/final_launch.py --output <new-absolute-directory> --dev-root <complete-frozen-DEV-directory>`。报告复现：全部计时完成后，用具备Matplotlib的现有Python运行 `tools/report_final.py --run <complete-final-directory>`。绘图不修改实验运行时。','']
    (S1/'FINAL_同布局增量价值报告.md').write_text('\n'.join(lines),encoding='utf8')
    for name in ('raw_native_all.csv','paired_all.csv','aa_all.csv','group_summary.csv','incremental_value_summary.csv','mechanism_counters_unique.csv'):
        shutil.copyfile(root/name,S1/('FINAL_'+name))
    json_save(root/'report_environment.json',{'scope':'post_timing_presentation','python':sys.executable,'version':sys.version,'matplotlib':matplotlib.__version__})
    json_save(S1/'FINAL_结果记录.json',{'schema':'S1.FINAL.result.git.v1','status':'FINAL_NATIVE_COMPLETE',
              'execution_git_commit':manifest['git_commit'],'result_git_tag':'s1-final-native-v1','run_directory':str(root),
              'resume_git_commit':manifest.get('resume_git_commit'),
              'production_start_gate':read(root/'FINAL_START_GATE.json'),'production_complete_gate':read(root/'FINAL_COMPLETE_GATE.json'),
              'counts':{'formal_pairs':700,'formal_children':2800,'AA_children':360},'selected_theta':16,'selected_h':2048,
              'R6_unchanged':True,'AA_floor':done['AA_floor'],'incremental_value':conclusion,
              'all_negative_results_retained':True,'resource_latency_diagnostics_complete':False})
    print(json.dumps({'status':'REPORT_REBUILT','raw_rows':len(raw),'paired_rows':len(paired),'group_rows':len(groups),'incremental_value':conclusion},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
