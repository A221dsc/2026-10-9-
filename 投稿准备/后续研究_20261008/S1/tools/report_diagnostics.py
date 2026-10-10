"""Reconstruct S1 diagnostics from sealed runs; never merges execution modes."""
from pathlib import Path
import argparse
import collections
import csv
import json
import shutil
import statistics
import sys
import time
import entry_gate as gate
from diagnostic_launch import S1, NATIVE, METHODS, check_binding, distribution, FINAL_TAG
from dev_launch import bind, dump


def write_csv(path, rows):
    with Path(path).open('x', encoding='utf8', newline='') as f:
        w = csv.DictWriter(f, list(rows[0]) if rows else ['status'])
        w.writeheader()
        w.writerows(rows)


def read_batch(root, count, mode):
    root = Path(root).resolve()
    complete = gate.load(root / 'COMPLETE.json')
    outer = gate.load(Path(str(root) + '_execution') / 'process.json')
    gate.require(complete['status'] == 'PASS' and complete['actual_completed'] == count
                 and complete['FAIL'] == 0 and complete['mode'] == mode
                 and outer['actual_exit_observed'] and outer['exit_code'] == 0, 'actual batch completion missing')
    records = []
    archives = []
    keys = set()
    for binding in complete['all_seals']:
        check_binding(binding)
        seal = gate.load(binding['path'])
        key = tuple(seal['cell'])
        gate.require(key not in keys, 'duplicate diagnostic cell')
        keys.add(key)
        for name in ('acceptance', 'archives', 'process', 'quiet'):
            check_binding(seal[name])
        accepted = gate.load(seal['acceptance']['path'])
        gate.require(accepted['status'] == 'PASS', 'acceptance status')
        accepted['evidence_path'] = seal['acceptance']['path']
        records.append(accepted)
        for name, receipt in gate.load(seal['archives']['path']).items():
            check_binding(receipt)
            gate.require(receipt['roundtrip_verified'], 'unverified compression')
            archives.append({'batch_mode': mode, 'case': key[0], 'seed': key[1], 'method': key[2],
                             'CSV': name, **receipt})
    gate.require(len(keys) == count, 'complete cell inventory')
    return records, archives


def resource_rows(records):
    rows = []
    for d in records:
        r = d['raw']
        final = d['resources'][-1]
        rows.append({'case_id': r['case_id'], 'seed': int(r['seed']), 'method': r['method'],
          'mode': 'resource', 'persistent_final': int(final['persistent_requested_bytes']),
          'whole_peak': d['summary']['whole_peak_requested_bytes'],
          **{f'{a}_final': final[a + '_current'] for a in ('pool', 'buckets', 'tree', 'manager')},
          **{k: r[k] for k in ('total_avoidable_work', 'promotions', 'scheduled_demotions',
               'cleanup_demotions', 'total_demotions', 'peak_tree_buckets', 'final_tree_buckets', 'cand_max', 'nodes_allocated')},
          'conversion_events': len(d['conversion_events']), 'API_samples': d['API_samples'],
          'owner_current_after_destroy': d['summary']['owner_current_after_destroy'], 'evidence': d['evidence_path']})
    return rows


def latency_rows(records):
    rows = []
    for d in records:
        r = d['raw']
        for kind, stats in [*d['API_distributions'].items(), ('all', d['all_API_distribution']),
                            ('conversion_body', d['conversion_body_distribution'])]:
            rows.append({'case_id': r['case_id'], 'seed': int(r['seed']), 'method': r['method'],
                         'mode': 'latency', 'API_type': kind, **stats,
                         'conversion_events': len(d['conversion_events']), 'evidence': d['evidence_path']})
    return rows


def paired_resources(rows):
    lookup = {(r['case_id'], r['seed'], r['method']): r for r in rows}
    out = []
    for case in sorted({r['case_id'] for r in rows}):
        for ref in ('M_LIST', 'M_EVENT_16', 'M_FIXED_2048', 'M_NO_IDLE'):
            for metric in ('persistent_final', 'whole_peak'):
                ratios = [lookup[case, s, 'R6'][metric] / lookup[case, s, ref][metric] for s in range(91001, 91011)]
                a = sorted(ratios)
                def q(p):
                    at = p * (len(a) - 1)
                    lo, hi = int(at), __import__('math').ceil(at)
                    return a[lo] + (a[hi] - a[lo]) * (at - lo)
                out.append({'case_id': case, 'candidate': 'R6', 'reference': ref, 'metric': metric,
                            'median_ratio': statistics.median(ratios), 'q25': q(.25), 'q75': q(.75),
                            'IQR': q(.75) - q(.25), 'wins': sum(v < 1 for v in ratios), 'total': 10,
                            'interpretation': 'descriptive_paired_resource_ratio_IQR_not_CI'})
    return out


def mechanism_rows(records):
    rows = []
    for d in records:
        r = d['raw']
        previous = 0
        for i, phase in enumerate(d['phases']):
            count = 2 * (int(phase['end_unit']) - int(phase['begin_unit'])) + int(phase['phase_query_count'])
            events = [e for e in d['conversion_events'] if previous < int(e['API_ordinal']) <= previous + count]
            endpoint = next(s for s in d['resources'] if 'phase' in s['snapshot_reason'] and int(s['phase']) == i)
            trees = set()
            for e in d['conversion_events']:
                if int(e['API_ordinal']) > previous + count:
                    break
                slot = int(e['slot'])
                if e['type'] == 'promotion':
                    trees.add(slot)
                else:
                    trees.remove(slot)
            rows.append({'seed': int(r['seed']), 'method': r['method'], 'phase': phase['phase'],
                'begin_unit': phase['begin_unit'], 'end_unit': phase['end_unit'],
                'tree_buckets': int(endpoint['tree_buckets']), 'tree_A': sum(s < 32 for s in trees),
                'tree_B': sum(32 <= s < 64 for s in trees),
                'promotions': sum(e['type'] == 'promotion' for e in events),
                'scheduled_demotions': sum(e['type'] == 'scheduled' for e in events),
                'cleanup_demotions': sum(e['type'] == 'cleanup' for e in events),
                'persistent_requested_bytes': int(endpoint['persistent_requested_bytes']),
                'whole_peak': int(endpoint['whole_peak']), 'diagnostic_phase_ns': int(phase['online_ns']),
                'phase_avoidable_work': 'NA_NOT_RECORDED_IN_FROZEN_INTERFACE', 'evidence': d['evidence_path']})
            previous += count
    return rows


def figures(root, mechanism, pairs, latency):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    for method in ('R6', 'M_EVENT_16', 'M_FIXED_2048', 'M_NO_IDLE'):
        d = next(r for r in mechanism if r['raw']['method'] == method and r['raw']['seed'] == '93001')
        snapshots = [s for s in d['resources'] if s['output_released'] == 'true']
        x = [int(s['completed_unit']) for s in snapshots]
        axes[0].plot(x, [int(s['tree_buckets']) for s in snapshots], label=method, linewidth=1.4)
        axes[1].plot(x, [int(s['whole_current']) / 2**20 for s in snapshots], linewidth=1.4)
    for ax in axes:
        for b in (32768, 49152, 81920, 98304):
            ax.axvline(b, color='grey', alpha=.4, linewidth=.8)
        ax.grid(alpha=.2)
    axes[0].legend(ncol=2, fontsize=9)
    axes[0].set_ylabel('TREE buckets')
    axes[1].set_ylabel('Current requested MiB')
    axes[1].set_xlabel('Completed update units; seed 93001, each line is one resource run')
    fig.suptitle('Registered A-hot / idle / B-hot / idle / A-return mechanism')
    fig.tight_layout()
    fig.savefig(root / 'S1_机制资源漂移.png', dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout='constrained')
    for ax, metric in zip(axes, ('persistent_final', 'whole_peak')):
        refs = ('M_LIST', 'M_EVENT_16', 'M_FIXED_2048', 'M_NO_IDLE')
        cases = [f'F{i:02}' for i in range(1, 8)]
        a = [[next(p['median_ratio'] for p in pairs if p['case_id'] == c and p['reference'] == ref and p['metric'] == metric)
              for ref in refs] for c in cases]
        im = ax.imshow(np.log2(a), cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
        ax.set_xticks(range(4), refs, rotation=35, ha='right')
        ax.set_yticks(range(7), cases)
        for i in range(7):
            for j in range(4):
                ax.text(j, i, f'{a[i][j]:.3f}', ha='center', va='center', fontsize=9)
        ax.set_title(metric + ': R6 / reference')
    fig.colorbar(im, ax=axes, label='log2 paired median ratio; lower means fewer requested bytes')
    fig.savefig(root / 'S1_资源配对.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4))
    cases = [f'F{i:02}' for i in range(1, 8)]
    for kind, metric, offset, label in [('all', 'p99', -.25, 'all API p99'), ('all', 'max', 0, 'all API max'),
                                       ('conversion_API', 'max', .25, 'conversion API max')]:
        values = []
        for case in cases:
            v = [r[metric] / 1000 for r in latency if r['case_id'] == case and r['method'] == 'R6'
                 and r['API_type'] == kind and r[metric] is not None]
            values.append(statistics.median(v) if v else float('nan'))
        ax.bar(np.arange(7) + offset, values, .25, label=label)
    ax.set_xticks(range(7), cases)
    ax.set_yscale('log')
    ax.set_ylabel('Microseconds: median of 10 per-run summaries')
    ax.set_title('R6 latency diagnostic only; no native throughput ranking')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=.2)
    fig.tight_layout()
    fig.savefig(root / 'S1_逐API与转换暂停.png', dpi=160)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    for arg in ('mechanism', 'resource', 'latency', 'cpu', 'output'):
        p.add_argument('--' + arg, type=Path, required=True)
    a = p.parse_args()
    root = a.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    mechanism, ma = read_batch(a.mechanism, 18, 'mechanism')
    resource, ra = read_batch(a.resource, 490, 'resource')
    latency, la = read_batch(a.latency, 490, 'latency')
    cpu = gate.load(a.cpu / 'COMPLETE.json')
    gate.require(cpu['actual_attempts'] == 4 and cpu['CPU_shares_fabricated'] is False, 'CPU attempts missing')
    rr, lr, mr = resource_rows(resource), latency_rows(latency), mechanism_rows(mechanism)
    pairs = paired_resources(rr)
    for name, rows in [('S1_resource_summary.csv', rr), ('S1_latency_summary.csv', lr),
                       ('S1_resource_paired.csv', pairs), ('S1_mechanism_phases.csv', mr), ('S1_raw_archive_index.csv', ma + ra + la)]:
        write_csv(root / name, rows)
    figures(root, mechanism, pairs, lr)
    count = collections.Counter(c['status'] for c in cpu['results'])
    def cell(case, ref, metric):
        return next(r for r in pairs if r['case_id'] == case and r['reference'] == ref and r['metric'] == metric)
    proof_table = '\n'.join(f'| {c} | {cell(c,"M_LIST","persistent_final")["median_ratio"]:.4f} | '
                  f'{cell(c,"M_EVENT_16","persistent_final")["median_ratio"]:.4f} | '
                  f'{cell(c,"M_NO_IDLE","persistent_final")["median_ratio"]:.4f} | '
                  f'{cell(c,"M_NO_IDLE","whole_peak")["median_ratio"]:.4f} |' for c in [f'F{i:02}' for i in range(1,8)])
    r6_cleanup = [(r['case_id'], r['seed'], r['cleanup_demotions']) for r in rr if r['method'] == 'R6' and int(r['cleanup_demotions']) > 0]
    pause_table = []
    for case in [f'F{i:02}' for i in range(1, 8)]:
        rows = [r for r in lr if r['case_id'] == case and r['method'] == 'R6']
        all_rows = [r for r in rows if r['API_type'] == 'all']
        ev_rows = [r for r in rows if r['API_type'] == 'conversion_API' and r['max'] is not None]
        med = lambda field: statistics.median(r[field] for r in all_rows) / 1000
        mx = max(r['max'] for r in all_rows) / 1000
        conv = f'{statistics.median(r["max"] for r in ev_rows)/1000:.3f}' if ev_rows else 'NA（无事件）'
        pause_table.append(f'| {case} | {med("p50"):.3f} | {med("p95"):.3f} | {med("p99"):.3f} | {med("max"):.3f} | {mx:.3f} | {conv} |')
    md = f'''# S1同布局归因与研究定位裁决报告

本轮完成冻结协议剩余诊断；不重跑 DEV/FINAL native，不重新选择门槛，不修改 R6、成本表、S0 或已发布结果。时间结论只引用 `{FINAL_TAG}` 的原生结果；本轮资源和 latency 都是独立批次。

## 1 执行与验收

| 批次 | 登记数 | 实际完成 | 验收 | 用途 |
|---|---:|---:|---|---|
| 容量工程试跑 | 2 | 2 | PASS | 排除于正式效果样本 |
| 机制 fixture | 18 | 18 | PASS，正式 FAIL=0 | 3种子×6匹配方法 |
| resource | 490 | 490 | PASS，正式 FAIL=0 | 168,113,400 API记录及独立请求空间追踪 |
| latency | 490 | 490 | PASS，正式 FAIL=0 | 168,113,400 逐API样本及完整事件 |
| CPU采样尝试 | 4 | 4 | {dict(count)} | 不使用墙钟差推导 CPU占比 |
| DEV/FINAL原生新增计时 | 0 | 0 | 冻结结果只读 | 旧3160个正式及A/A子进程保留 |

新入口先保存7项 RED 失败（入口缺失），随后7项入口单测和7项实际CSV损坏验收测试 GREEN。两种冻结诊断二进制完成6个小规模内部回放，共288 API。首次 GREEN 尝试有2个沙箱临时目录错误和1个浮点精确断言失败，完整保留，后续改用工作区测试目录及数值容差；这些不算正式实验失败或效果样本。

容量试跑每次F03产生约512–514 MB CSV，压缩约12 MB；两正式模式估算未压缩约220 GB，归档约5.4 GB。gzip保存全量记录，校验完整解压 SHA256 后才移除重复未压缩副本。每次执行记录真实命令、退出码、配置、输入和二进制身份、quiet及placement。无按结果择优重跑。

## 2 时间：原生结论保持原判

R6相对同布局LIST：7组online有2组明确更快、4组更慢、1组无法可靠区分；total为2/3/2。相对DEV选定Event_16：online为1/2/4，total为1/1/5；相对Fixed_2048：online为2/2/3，total为2/0/5。分组包括公开轨迹与合成输入；不能将总计称作7类真实生产访问。

成本代理的明确增量价值集中在F05低工作场景，避免简单门控树化；但R6仍慢于同布局LIST。F06/F07说明TREE表示可以降低昂贵链表定位成本，未证明成本信号普遍优于简单门控。F03优于选定Fixed_2048不能外推到任意固定门槛：该门槛在公开桶上不升级，Fixed_128诊断差异未可靠区分。

原生A/A online范围约0.9448–1.0584、total约0.9240–1.0823，是有限观测噪声包络，不是置信区间。既有强效应按冻结42比较族与相关性约束判定。本轮诊断时钟不加入原生速度排名，也不重新筛选原生结果。

原始证据：[{S1/'FINAL_同布局增量价值报告.md'}]({S1/'FINAL_同布局增量价值报告.md'})；`FINAL_group_summary.csv`、`FINAL_paired_all.csv`、`FINAL_raw_native_all.csv`；原生完成闸门 `{NATIVE/'FINAL_COMPLETE_GATE.json'}`。

## 3 机制：普通回收有效，但没有新增信号加速证明

三个种子的R6都得到32→0→32→0→32 TREE轨迹，96次promotion、64次scheduled、0次cleanup；A和B热点的32个桶分别升级，原热点非空回收后预算可供新热点，A_return能重新升级。每epoch最多1 promotion+1 scheduled；cooldown和TREE≤32均逐事件核验。

Event_16得到相同表示序列及转换总数。因此fixture支持共享调度、资源回收和再次升级，不能单独证明R6成本代理比事件信号有额外价值。Fixed_2048为104次升级、72次普通降级，端点空闲阶段有8次额外升级；M_NO_IDLE只有32次升级，始终保留A树，B热点被满预算阻挡。关闭回收并不破坏内容正确性，但阻止表示资源随热点转移。

M01固定每桶2048条，永不空桶，因此cleanup覆盖状态为 **NOT_EXERCISED**；不能把0次cleanup写成验证了即时清理。独立resource批次中R6有 {len(r6_cleanup)} 个输入实际产生cleanup，按事件n=0、erase API、表示成员、计数恒等式及配额豁免核验。详细输入列在资源汇总，不将它们拼接进M01轨迹。空树清理的生产/诊断一致性另有已审查SX24工程证据。

阶段可避免工作未被冻结快照接口记录，写NA；总工作、候选峰值、节点及转换数量来自各次同运行末尾原始计数。禁止从总值倒推出各阶段工作。

![机制与资源]({root/'S1_机制资源漂移.png'})

证据：`S1_mechanism_phases.csv`保留全部90个方法/种子/阶段，M01所有记录索引在`S1_raw_archive_index.csv`；每个值可追至`ACCEPTANCE.json`及对应原始CSV.gz。

## 4 资源：请求字节与常驻进程内存区分

下表为同输入同种子R6/reference配对比值中位数；小于1表示请求字节较少。IQR及wins/10见完整CSV，IQR不称置信区间。

| 场景 | final / LIST | final / Event_16 | final / NoIdle | whole peak / NoIdle |
|---|---:|---:|---:|---:|
{proof_table}

这是索引拥有者的同时存活请求字节，不是RSS。whole_peak包含被追踪的临时输出和转换暂存；不把四账户各自peak相加。Original无法对应四账户，逐项NA，仍报告独立whole current/peak；所有resource运行析构后owner current/live归零。桶预算32是数量预算，不是字节上限；LIST节点池仍保留分配容量，回收TREE不会释放既有池。

资源收益应以相对NoIdle/简单门控的实际配对结果表述，不能声称比纯LIST更省内存或把native计数代替空间证据。M01图中每条线的TREE与请求字节来自同一resource运行；多个方法是同输入的不同运行。

![资源配对]({root/'S1_资源配对.png'})

证据：490行`S1_resource_summary.csv`、56行`S1_resource_paired.csv`，完整periodic512、phase/final与conversion快照在原始resource.csv.gz。

## 5 逐API与转换暂停：稀有事件保留max

下面是独立latency模式R6的10个输入各自分位数/最大值再取中位数，单位µs；“全批最大”保留10次运行的实际最坏值，转换列仅对存在转换的运行计算。不池化10种子API后假称独立输入统计。

| 场景 | p50 | p95 | p99 | max中位数 | 全批最大 | 转换API max中位数 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(pause_table)}

`S1_latency_summary.csv`逐输入分别报告erase、insert、range、全API、包含转换的API及conversion_body的count/p50/p95/p99/max。转换类型、API序号、epoch、slot、n、body_ns和api_latency_ns保留全部明细。body不等于API全时延；稀有转换可能不出现在全API p99，不能只凭p99断言暂停低。

这些API时间含诊断Clock、观察事件与参考校验缓存影响，resource又额外包含账户追踪；两者均不代替native在线时间，不把资源运行的转换时延加入latency分布。不承诺此单机测量给出了生产服务SLA或长期最大暂停上界。

![逐API暂停]({root/'S1_逐API与转换暂停.png'})

## 6 CPU诊断与证据限制

四个登记场景均尝试R6、seed91001采样，状态为{dict(count)}。每次保留工具实际命令与返回码。若WPR启动不可用/权限不足，仅报告不可用；若ETL已捕获但缺乏经核验符号归因与导出流程，报告CAPTURED_UNANALYZED。CPU百分比保持NA，不能用观察臂时间差、墙钟差或转换Clock总和冒充CPU占比。

CPU原始证据：`{a.cpu.resolve()/'COMPLETE.json'}`及四个场景子目录。已发布P02只能说明共享布局下观察、缓冲与结构时钟的合计净开销。

## 7 研究定位裁决与论文边界

可以主张：冻结布局下，昂贵非输出链表定位有TREE表示收益；成本门控能在登记的低工作场景避免无收益升级；有限树桶预算配合普通回收允许资源随非空热点迁移，并在再次出现时重新升级；资源、转换事件与适用边界有可复现诊断证据。

不能主张：R6普遍快于PoolHBI、EventGate、所有固定门槛或TLX；S1证明真实生产访问性能；树/链混合或成本模型首次提出；较少avoidable_work必然等于同比CPU时间节省；更少TREE必然更低RSS；单机单线程的结果可直接推广到并发/其他硬件；未获得采样归因时给出管理器CPU百分比。

论文中心宜收敛为“有预算和回收的滑动窗口表示管理及其成本边界”，将成本代理的局部收益和公开轨迹负结果并列。机制必要性与成本信号的增量必要性是不同研究问题；当前证据强于笼统自适应吞吐主张。

## 8 S2/S3缩减建议（尚未启动）

S2只保留一个独立时间键来源、三类负载（端点稀疏、内部撤销、稀疏→乱序→稀疏）、四个方法（LIST、Event_16、R6、TLX）；运行长度用1/2/4窗口周转真实共同前缀，优先报告累计total与资源回收，不全面复制旧矩阵。外部时间数据加生成操作仍明确称合成访问。

S3先获得可靠CPU采样归因，再考虑诊断确认的实现开销优化；候选是range全目录观察缓冲初始化。任何改进另命名版本、另冻结与重新比较，不能覆写R6或套用旧结论。并发、ML、新预测模型、GPU及第二轮大矩阵暂缓。S2/S3只提出范围，没有自动执行。
'''
    (root / 'S1同布局归因与研究定位裁决报告.md').write_text(md, encoding='utf8')
    dump(root / 'S1_诊断完成记录.json', {'status': 'S1_DIAGNOSTICS_COMPLETE',
         'mechanism_runs': 18, 'resource_runs': 490, 'latency_runs': 490,
         'CPU_attempts': 4, 'CPU_statuses': dict(count), 'native_reruns': 0,
         'resource_API_samples': sum(d['API_samples'] for d in resource),
         'latency_API_samples': sum(d['API_samples'] for d in latency),
         'native_tag': FINAL_TAG, 'batch_receipts': [bind(p / 'COMPLETE.json') for p in (a.mechanism, a.resource, a.latency, a.cpu)],
         'capacity': bind(a.mechanism.parent / 'CAPACITY_20261011_01/CAPACITY.json'),
         'all_raw_archives_verified_again_by_compressed_sha': True,
         'report_files': [bind(p) for p in sorted(root.iterdir()) if p.is_file()], 'ended_ns': time.time_ns()})
    print('S1 report complete:', root, flush=True)


if __name__ == '__main__':
    main()
