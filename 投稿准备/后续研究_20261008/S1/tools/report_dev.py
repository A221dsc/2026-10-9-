"""Regenerate DEV documentation and figures from a completed production run.

This is a presentation script, not a new experiment or selection rule.
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

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def rows(path):
    with Path(path).open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);args=p.parse_args()
    root=Path(args.run).resolve()
    done=read(root/'completion.json');gate=read(root/'DEV_COMPLETE_GATE.json')
    if done['status']!='DEV_COMPLETE' or not gate['DEV_READY'] or gate['FINAL_READY']:
        raise ValueError('complete production DEV gate required for report')
    selected=read(root/'dev_selection.json');manifest=read(root/'execution_manifest.json')
    if selected['test_fixture'] or done['actual_timing_children']!=1120:raise ValueError('real complete DEV evidence required')
    paired=[r for r in rows(root/'paired_all.csv') if r['profile']=='dev']
    summaries=rows(root/'dev_summary.csv');scores=rows(root/'dev_scores.csv')
    by_method={r['method']:r for r in summaries if r['component']=='total'}
    cases=[]
    for case in sorted({r['case_id'] for r in paired}):
        for method in selected['scores']:
            group=[r for r in paired if r['case_id']==case and r['candidate']==method]
            for component in ('build','online','total'):
                vals=[float(r[component]) for r in group]
                q25,q75=analysis.linear_quantile(vals,.25),analysis.linear_quantile(vals,.75)
                cases.append({'case_id':case,'method':method,'component':component,'n':len(vals),
                              'median_ratio':analysis.linear_quantile(vals,.5),'q25':q25,'q75':q75,
                              'IQR':q75-q25,'wins':sum(x<1 for x in vals),
                              'geometric_mean_ratio':math.exp(math.fsum(math.log(x) for x in vals)/len(vals))})
    with (root/'dev_by_case.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(cases[0]));w.writeheader();w.writerows(cases)
    selected_methods={f'M_EVENT_{selected["selected_theta"]}',f'M_FIXED_{selected["selected_h"]}'}
    os.environ['MPLCONFIGDIR']=str(root/'plot_cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    matplotlib.rcParams['svg.fonttype']='none'
    report_environment={'scope':'post_experiment_presentation_only','python':sys.executable,
                        'python_version':sys.version,'matplotlib':matplotlib.__version__,
                        'experiment_runtime_unchanged':True}
    (root/'report_environment.json').write_text(json.dumps(report_environment,indent=2)+'\n',encoding='utf8')
    methods=list(selected['scores']);values=[math.exp(selected['scores'][m]) for m in methods]
    colors=['#087f8c' if m in selected_methods else '#94a6b8' for m in methods]
    fig,ax=plt.subplots(figsize=(10,5.8),layout='constrained')
    floor=done['AA_floor']['total'];low,high=math.exp(-floor),math.exp(floor)
    ax.axvspan(low,high,color='#e8edf2',zorder=0)
    ax.barh(methods,values,color=colors,height=.62,zorder=2)
    for i,v in enumerate(values):
        ax.text(v-.018,i,f'{v:.4f}',va='center',ha='right',fontsize=10,
                color='white' if methods[i] in selected_methods else '#172b4d')
    ax.axvline(1,color='#23395d',linestyle='--',linewidth=1.2)
    ax.invert_yaxis();ax.set_xlim(0,max(high*1.07,max(values)*1.12))
    ax.set_xlabel('Geometric mean total-time ratio (candidate / M_LIST); lower is faster')
    ax.set_title('DEV selection: 30 equally weighted registered inputs',pad=12)
    ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False)
    ax.legend(handles=[Patch(color='#087f8c',label='Selected within family'),
                       Patch(color='#e8edf2',label='Observed A/A envelope (not a confidence interval)')],
              loc='lower left',bbox_to_anchor=(0,-.27),frameon=False,fontsize=9)
    fig.savefig(S1/'DEV_候选总时间.svg');fig.savefig(S1/'DEV_候选总时间.png',dpi=180);plt.close(fig)
    lines=['# S1 DEV 实验报告', '',
           f'本轮 DEV 已完整完成并通过生产入口及完成闸门。事件门槛 θ={selected["selected_theta"]}，固定大小门槛 h={selected["selected_h"]}，按预注册规则一次性选定。尚未运行同布局正式矩阵，不能据此宣称 Adaptive R6 优于简单门控。', '',
           f'执行版本：Git `{manifest["git_commit"]}`；冻结工程标签 `s1-engineering-v1`，冻结规范标签 `s0-freezable-v1`。本批归档：[{root.name}](<{root}>)。', '',
           '## 执行范围与完整性', '',
           '- 30 份 DEV 输入：D01–D10 × 种子90001–90003；8个候选臂，各与M_LIST独立配对，共240格、960个计时子进程。',
           '- 前后 A/A：M_LIST、M_EVENT_16 × D02、D06 × 独立种子92001，各5个两轮块，共160个计时子进程。',
           '- 两轮AB/BA、固定逻辑P核3（mask 0x8）、串行运行；GetSystemTimes守卫保持10%阈值、2秒首样本、繁忙2秒重试和300秒等待上限。',
           '- 完整语义、配置、侧车、进程退出码及前后A/A包围主矩阵的时序均由冻结闸门验证。R6实现、参数和成本表没有改动；未运行机制、正式、延迟或资源实验。',
           '- 没有删掉慢格子、筛除离群值、按结果重跑或修改门槛候选；完整原始数据保留。', '',
           '## 一次性选择', '',
           '每个输入以两轮total时间比值的几何平均得到一个配对值；30份输入等权平均其log比值。分别在Event和Fixed家族选择最小分数；仅浮点分数完全相等时选择更小门槛。目标包含build+online，destroy另行保留。', '',
           '|候选|平均log(total比值)|total几何平均比值|配对中位数|Q25–Q75|IQR|原始胜出/30|选择|',
           '|---|---:|---:|---:|---:|---:|---:|---|']
    for method,score in selected['scores'].items():
        s=by_method[method]
        lines.append(f'|{method}|{score:.6f}|{math.exp(score):.4f}|{float(s["median_ratio"]):.4f}|{float(s["q25"]):.4f}–{float(s["q75"]):.4f}|{float(s["IQR"]):.4f}|{s["wins"]}/30|'+('选定|' if method in selected_methods else '—|'))
    lines+=['', '比值为候选/M_LIST，小于1表示该配对候选耗时更少。IQR描述不同输入间离散程度，不是置信区间；原始胜出次数也未扣除噪声，不能视作显著性。表中的跨负载平均用于预注册的门槛选择，不说明每个场景都更快。', '',
            'Event_16的total配对中位数为1.0500，原始胜出12/30；Fixed_2048中位数为1.0128，原始胜出同为12/30。两个选定臂均没有在多数开发输入上获得总时间优势，平均log目标的改善主要来自少数大桶高工作量格子。', '',
            f'![DEV候选总时间](<{S1/"DEV_候选总时间.png"}>)', '',
            '## 开发输入的适用差异', '',
            '每格为三个DEV种子的配对比值中位数。这里展示开发集中的异质性，不作正式泛化检验；完整八臂逐场景结果在CSV中保留。', '',
            '|输入|场景|Event_16 online|Event_16 total|Fixed_2048 online|Fixed_2048 total|',
            '|---|---|---:|---:|---:|---:|']
    labels=['端点，单桶256','端点，单桶4096','低工作量，单桶256','低工作量，单桶4096',
            '高工作量，单桶256','高工作量，单桶4096','范围前缀定位，单桶256',
            '范围前缀定位，单桶4096','预算竞争，64桶×256','预算竞争，64桶×1024']
    lookup={(r['case_id'],r['method'],r['component']):r for r in cases}
    for i,label in enumerate(labels,1):
        case=f'D{i:02}'
        values=[lookup[case,m,c]['median_ratio'] for m in ('M_EVENT_16','M_FIXED_2048') for c in ('online','total')]
        lines.append(f'|{case}|{label}|'+ '|'.join(f'{v:.4f}' for v in values)+'|')
    lines+=['', 'D06和D08的大幅改善说明，大桶且内部定位／范围起点扫描工作较多时，表示转换值得进一步验证；D04的低工作量和D02的固定门槛端点负结果则说明，单凭桶大并不足以保证获益。这些结果来自简单门控对照，尚不能证明成本代理比它们更有价值。', '',
            '## 前后 A/A 噪声', '',
            '下表为40个完整两轮块中，前后所有配置的最大绝对log比值。它是有限样本中观察到的包络，不是统计置信界限。', '',
            '|分量|最大绝对log比值|比值包络 exp(±floor)|', '|---|---:|---:|']
    for component in ('build','online','total'):
        v=done['AA_floor'][component]
        lines.append(f'|{component}|{v:.6f}|{math.exp(-v):.4f}–{math.exp(v):.4f}|')
    lines+=['', '落在对应包络内的墙钟差异报告为“无法可靠区分”。DEV门槛仍严格按既定数值目标选择，不因噪声重新校准、另选输入或改动算法。噪声较大或候选分数接近时，选定门槛只是本轮冻结控制配置，不意味着证明它在总体上最优。', '',
            '## 数据与复现', '',
            f'- [一次性选择记录](<{root/"dev_selection.json"}>)',
            f'- [完整原始CSV（1120个计时子进程）](<{root/"raw_native_all.csv"}>)',
            f'- [配对CSV（240个DEV格子和40个A/A块）](<{root/"paired_all.csv"}>)',
            f'- [DEV分量汇总](<{root/"dev_summary.csv"}>)；[逐场景汇总](<{root/"dev_by_case.csv"}>)',
            f'- [执行环境与Git版本](<{root/"execution_manifest.json"}>)；[起始闸门](<{root/"DEV_START_GATE.json"}>)；[完成闸门](<{root/"DEV_COMPLETE_GATE.json"}>)',
            f'- 所有子进程侧车及实际命令在 `{root/"children"}`；输入生成命令在 `{root/"preparation"}`。', '',
            '复现计时使用同一Git版本及冻结Python 3.12运行时，从新的空输出目录运行 `tools/dev_launch.py --output <new-absolute-directory>`；运行完毕后，用具备Matplotlib的Python运行 `tools/report_dev.py --run <absolute-run-directory>` 重建本报告和图。旧输出目录不可覆盖。文件完整性字段继续供冻结闸门验收，源码和二进制版本使用Git定位。', '',
            f'报告绘图使用现有Python 3.13与Matplotlib {matplotlib.__version__}，只在全部计时结束后使用；首个报告尝试因Python 3.12绘图库缺少pyparsing失败，原始退出码1和stderr在归档中保留。未安装或改动冻结实验运行时，未重跑实验。', '',
            '## 阶段结论', '',
            'DEV完成的成果是公平比较臂的门槛与可核验的开发证据。下一阶段才用独立final种子检验R6相对同布局LIST、只观察LIST、Event、Fixed和No-Idle的增量价值。本轮不支持“Adaptive提高吞吐”的论文结论，也不触发R6或成本表修改。', '']
    (S1/'DEV_实验报告.md').write_text('\n'.join(lines),encoding='utf8')
    for name in ('dev_scores.csv','dev_summary.csv','dev_by_case.csv','raw_native_all.csv','paired_all.csv'):
        shutil.copyfile(root/name,S1/('DEV_'+name))
    record={'schema':'S1.DEV.result.git.v1','status':'DEV_COMPLETE','result_git_tag':'s1-dev-v1','execution_git_commit':manifest['git_commit'],
            'engineering_tag':'s1-engineering-v1','normative_tag':'s0-freezable-v1','run_directory':str(root),
            'selected_theta':selected['selected_theta'],'selected_h':selected['selected_h'],
            'actual_DEV_children':960,'actual_AA_children':160,'program_failures':0,'DEV_COMPLETE':True,'FINAL_READY':False,
            'formal_children':0,'R6_modified':False,'AA_floor':done['AA_floor'],
            'selection_path':str(root/'dev_selection.json'),'complete_gate_path':str(root/'DEV_COMPLETE_GATE.json')}
    (S1/'DEV_结果记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'theta':selected['selected_theta'],'h':selected['selected_h'],'AA_floor':done['AA_floor'],
                      'scores':selected['scores'],'report':str(S1/'DEV_实验报告.md')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
